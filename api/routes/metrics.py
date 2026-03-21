from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from core.logging import logger

router = APIRouter(tags=["metrics"])

_REPAIR_AUDIT_PATH = Path("logs/repair_audit.jsonl")

_METRICS_LOCK = threading.RLock()
_METRICS_STATE: dict[str, Any] = {
    "updated_at": None,
    "segyr_metrics_last_update_timestamp": float("nan"),
    "segyr_health_score": 0.0,
    "segyr_health_status": 2.0,
    "segyr_llm_latency_seconds": float("nan"),
    "segyr_cache_gain": float("nan"),
    "segyr_queue_status": 0.0,
    "segyr_last_repair_success": 0.0,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _status_to_metric(status: str | None) -> float:
    raw = str(status or "critical").strip().lower()
    if raw in {"ok", "healthy"}:
        return 0.0
    if raw in {"warn", "warning", "degraded"}:
        return 1.0
    return 2.0


def _extract_details(health_payload: dict[str, Any]) -> dict[str, Any]:
    details = health_payload.get("details")
    if not isinstance(details, dict):
        return {}

    nested = details.get("details")
    if isinstance(nested, dict):
        return nested

    return details


def _component_ok(health_payload: dict[str, Any], details: dict[str, Any], name: str) -> bool | None:
    components = health_payload.get("components")
    if isinstance(components, dict) and name in components:
        return bool(components.get(name))

    payload_details = health_payload.get("details")
    if isinstance(payload_details, dict):
        nested_components = payload_details.get("components")
        if isinstance(nested_components, dict) and name in nested_components:
            return bool(nested_components.get(name))

    part = details.get(name)
    if isinstance(part, dict) and "ok" in part:
        return bool(part.get("ok"))

    return None


def _compute_llm_latency_seconds(details: dict[str, Any]) -> float:
    cache_data = details.get("cache") if isinstance(details.get("cache"), dict) else {}
    first_duration = _to_float((cache_data.get("first") or {}).get("duration_s"))
    if first_duration is not None:
        return first_duration

    direct_latency = _to_float(details.get("llm_latency_seconds"))
    if direct_latency is not None:
        return direct_latency

    return float("nan")


def _compute_cache_gain(details: dict[str, Any]) -> float:
    cache_data = details.get("cache") if isinstance(details.get("cache"), dict) else {}
    latency_ratio = _to_float(cache_data.get("latency_ratio"))
    if latency_ratio is not None and latency_ratio > 0:
        return 1.0 / latency_ratio

    first_duration = _to_float((cache_data.get("first") or {}).get("duration_s"))
    second_duration = _to_float((cache_data.get("second") or {}).get("duration_s"))
    if first_duration is not None and second_duration is not None and second_duration > 0:
        return first_duration / second_duration

    return float("nan")


def _read_last_jsonl_entry(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None

    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            if size <= 0:
                return None
            read_size = min(size, 64 * 1024)
            fh.seek(size - read_size)
            chunk = fh.read(read_size).decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.warning("metrics read audit failed path={} err={}", path, exc)
        return None

    for line in reversed(chunk.splitlines()):
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue

    return None


def _last_repair_success_value() -> float:
    entry = _read_last_jsonl_entry(_REPAIR_AUDIT_PATH)
    if not isinstance(entry, dict):
        return 0.0

    status = str(entry.get("status_final") or "").strip().lower()
    if status == "success":
        return 1.0
    if status == "failed":
        return 0.0

    return 0.0


def update_metrics_from_health(health_payload: dict[str, Any]) -> None:
    if not isinstance(health_payload, dict):
        return

    details = _extract_details(health_payload)

    score = _to_float(health_payload.get("score"))
    if score is None and isinstance(health_payload.get("details"), dict):
        score = _to_float((health_payload.get("details") or {}).get("score"))
    if score is None:
        score = 0.0

    status = str(health_payload.get("status") or (health_payload.get("details") or {}).get("status") or "critical")
    queue_ok = _component_ok(health_payload, details, "queue")
    now_ts = datetime.now(timezone.utc).timestamp()

    with _METRICS_LOCK:
        _METRICS_STATE["updated_at"] = _now_iso()
        _METRICS_STATE["segyr_metrics_last_update_timestamp"] = now_ts
        _METRICS_STATE["segyr_health_score"] = score
        _METRICS_STATE["segyr_health_status"] = _status_to_metric(status)
        _METRICS_STATE["segyr_llm_latency_seconds"] = _compute_llm_latency_seconds(details)
        _METRICS_STATE["segyr_cache_gain"] = _compute_cache_gain(details)
        _METRICS_STATE["segyr_queue_status"] = 1.0 if queue_ok else 0.0
        _METRICS_STATE["segyr_last_repair_success"] = _last_repair_success_value()


def _prom_value(value: Any) -> str:
    if isinstance(value, float) and math.isnan(value):
        return "nan"
    return str(value)


def get_metrics_snapshot() -> dict[str, Any]:
    with _METRICS_LOCK:
        snapshot = dict(_METRICS_STATE)
    return snapshot


def render_metrics_text(snapshot: dict[str, Any]) -> str:
    lines = [
        "# HELP segyr_metrics_last_update_timestamp Unix timestamp of the last metrics refresh.",
        "# TYPE segyr_metrics_last_update_timestamp gauge",
        f"segyr_metrics_last_update_timestamp {_prom_value(snapshot.get('segyr_metrics_last_update_timestamp', float('nan')))}",
        "# HELP segyr_health_score Current SEGYR health score.",
        "# TYPE segyr_health_score gauge",
        f"segyr_health_score {_prom_value(snapshot.get('segyr_health_score', 0))}",
        "# HELP segyr_health_status Health status mapped to 0=ok,1=warn,2=critical.",
        "# TYPE segyr_health_status gauge",
        f"segyr_health_status {_prom_value(snapshot.get('segyr_health_status', 2))}",
        "# HELP segyr_llm_latency_seconds LLM latency observed from health checks.",
        "# TYPE segyr_llm_latency_seconds gauge",
        f"segyr_llm_latency_seconds {_prom_value(snapshot.get('segyr_llm_latency_seconds', float('nan')))}",
        "# HELP segyr_cache_gain Cache gain ratio from health checks.",
        "# TYPE segyr_cache_gain gauge",
        f"segyr_cache_gain {_prom_value(snapshot.get('segyr_cache_gain', float('nan')))}",
        "# HELP segyr_queue_status Queue status where 1=up and 0=down.",
        "# TYPE segyr_queue_status gauge",
        f"segyr_queue_status {_prom_value(snapshot.get('segyr_queue_status', 0))}",
        "# HELP segyr_last_repair_success Last repair final status where 1=success and 0=failed.",
        "# TYPE segyr_last_repair_success gauge",
        f"segyr_last_repair_success {_prom_value(snapshot.get('segyr_last_repair_success', 0))}",
    ]
    return "\n".join(lines) + "\n"


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    snapshot = get_metrics_snapshot()
    body = render_metrics_text(snapshot)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")
