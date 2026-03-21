from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from core.logging import logger
from core.monitoring.auto_repair import DEFAULT_BASE_URL, DEFAULT_MIN_SCORE, run_auto_repair_loop
from core.monitoring.policy_engine import decide_actions, evaluate_policy, should_repair

DEFAULT_ALERT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_HEALTH_PATH = "/health/full"
DEFAULT_POLL_INTERVAL_SECONDS = 30.0
DEFAULT_COOLDOWN_SECONDS = 300.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 8.0
ALERT_HISTORY_LIMIT = 500
DEFAULT_AUDIT_HISTORY_PATH = "logs/repair_audit.jsonl"
DEFAULT_AUDIT_HISTORY_LIMIT = 200
DEFAULT_ERROR_WINDOW_SECONDS = 5 * 60

_ALERT_LEVELS = {"OK", "WARNING", "CRITICAL"}

_STATE_LOCK = threading.RLock()
_ALERT_COUNTERS: dict[str, int] = {"OK": 0, "WARNING": 0, "CRITICAL": 0}
_ALERT_HISTORY: deque[dict[str, Any]] = deque(maxlen=ALERT_HISTORY_LIMIT)
_LAST_AUTO_REPAIR_RESULT: dict[str, Any] | None = None
_LAST_POLICY_REPORT: dict[str, Any] | None = None
_LAST_AUTO_REPAIR_TRIGGER_TS: float = 0.0
_AUTO_REPAIR_IN_PROGRESS = False
_AUTO_REPAIR_THREAD: threading.Thread | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _to_ts(value: Any) -> float | None:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _extract_details(health_data: dict[str, Any]) -> dict[str, Any]:
    details = health_data.get("details")
    if not isinstance(details, dict):
        return {}

    nested = details.get("details")
    if isinstance(nested, dict):
        return nested

    return details


def _component_ok(health_data: dict[str, Any], details: dict[str, Any], name: str) -> bool | None:
    components = health_data.get("components")
    if isinstance(components, dict) and name in components:
        return bool(components.get(name))

    payload_details = health_data.get("details")
    if isinstance(payload_details, dict):
        nested_components = payload_details.get("components")
        if isinstance(nested_components, dict) and name in nested_components:
            return bool(nested_components.get(name))

    item = details.get(name)
    if isinstance(item, dict) and "ok" in item:
        return bool(item.get("ok"))

    return None


def _is_redis_error(health_data: dict[str, Any]) -> bool:
    details = _extract_details(health_data)
    redis_ok = _component_ok(health_data, details, "redis")
    if redis_ok is False:
        return True

    warnings = health_data.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            if "redis" in str(warning).lower():
                return True

    return False


def _recent_redis_error_count(window_seconds: int = DEFAULT_ERROR_WINDOW_SECONDS) -> int:
    if window_seconds <= 0:
        return 0

    now_ts = datetime.now(timezone.utc).timestamp()
    floor_ts = now_ts - float(window_seconds)

    with _STATE_LOCK:
        snapshot = list(_ALERT_HISTORY)

    count = 0
    for event in snapshot:
        ts = _to_ts(event.get("ts"))
        if ts is None or ts < floor_ts:
            continue
        health = event.get("health")
        if isinstance(health, dict) and _is_redis_error(health):
            count += 1
    return count


def _read_recent_audit_history(
    *,
    path: str = DEFAULT_AUDIT_HISTORY_PATH,
    limit: int = DEFAULT_AUDIT_HISTORY_LIMIT,
) -> list[dict[str, Any]]:
    max_items = max(0, int(limit))
    if max_items <= 0:
        return []

    file_path = Path(path)
    if not file_path.exists():
        return []

    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        logger.warning("alerting audit history read failed path={} err={}", file_path, exc)
        return []

    items: list[dict[str, Any]] = []
    for raw in lines[-max_items:]:
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                items.append(obj)
        except Exception:
            continue
    return items


def _policy_reason_codes(policy_report: dict[str, Any], decision: bool) -> str:
    key = "issues" if decision else "suppressions"
    values = policy_report.get(key)
    if not isinstance(values, list):
        return "n/a"

    codes = [str(item.get("code") or "").strip() for item in values if isinstance(item, dict)]
    compact = [code for code in codes if code]
    if compact:
        return ",".join(compact[:8])

    return "no_actionable_issue" if not decision else "policy_trigger"


def _normalize_level(status: str) -> str:
    s = (status or "").strip().lower()
    if s in {"ok", "healthy"}:
        return "OK"
    if s in {"warning", "warn", "degraded"}:
        return "WARNING"
    return "CRITICAL"


def _record_alert(level: str, health_data: dict[str, Any]) -> None:
    score = _to_int(health_data.get("score"), default=0)
    status = str(health_data.get("status") or "unknown")
    event = {
        "ts": _now_iso(),
        "level": level,
        "status": status,
        "score": score,
        "health": health_data,
    }
    with _STATE_LOCK:
        if level not in _ALERT_COUNTERS:
            _ALERT_COUNTERS[level] = 0
        _ALERT_COUNTERS[level] += 1
        _ALERT_HISTORY.append(event)


def fetch_health(
    *,
    base_url: str = DEFAULT_ALERT_BASE_URL,
    path: str = DEFAULT_HEALTH_PATH,
    timeout_s: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    try:
        resp = requests.get(url, timeout=timeout_s)
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw": resp.text}

        if not isinstance(payload, dict):
            payload = {"payload": payload}

        if resp.status_code >= 400:
            payload.setdefault("status", "critical")
            payload.setdefault("score", 0)
            payload.setdefault("error", f"health endpoint HTTP {resp.status_code}")
        return payload
    except Exception as exc:
        logger.warning("fetch_health failed url={} err={}", url, exc)
        return {
            "timestamp": _now_iso(),
            "status": "critical",
            "score": 0,
            "error": str(exc),
            "source": url,
        }


def evaluate_status(health_data: dict[str, Any]) -> str:
    status = str(health_data.get("status") or "critical")
    score = _to_int(health_data.get("score"), default=0)

    level = _normalize_level(status)

    # Score-driven safety net when upstream status is optimistic or missing.
    if score < 60:
        return "CRITICAL"
    if score < 85 and level == "OK":
        return "WARNING"
    return level


def _run_auto_repair_task(
    *,
    health_data: dict[str, Any],
    planned_actions: list[str] | None,
    policy_report: dict[str, Any] | None,
    correlation_id: str,
    source: str,
    auto_repair_base_url: str,
    auto_repair_min_score: int,
    auto_repair_dry_run: bool,
    auto_repair_safe_mode: bool,
) -> None:
    global _AUTO_REPAIR_IN_PROGRESS, _AUTO_REPAIR_THREAD, _LAST_AUTO_REPAIR_RESULT

    score_before = _to_int(health_data.get("score"), default=0)
    logger.warning(
        "[ACTION] trigger_auto_repair score_before={} actions={} correlation_id={} source={}",
        score_before,
        planned_actions or [],
        correlation_id,
        source,
    )

    try:
        result = run_auto_repair_loop(
            health_data=health_data,
            dry_run=auto_repair_dry_run,
            safe_mode=auto_repair_safe_mode,
            base_url=auto_repair_base_url,
            min_score=auto_repair_min_score,
            planned_actions=planned_actions,
            correlation_id=correlation_id,
            source=source,
        )
        score_after = _to_int(result.get("score_after"), default=score_before)
        logger.info(
            "[RESULT] auto_repair repaired={} score_before={} score_after={} correlation_id={} source={}",
            bool(result.get("repaired")),
            score_before,
            score_after,
            correlation_id,
            source,
        )
        if isinstance(policy_report, dict):
            result.setdefault("policy", policy_report)
        _LAST_AUTO_REPAIR_RESULT = result
    except Exception as exc:
        logger.exception("trigger_auto_repair failed: {}", exc)
        _LAST_AUTO_REPAIR_RESULT = {
            "ts": _now_iso(),
            "repaired": False,
            "score_before": score_before,
            "score_after": score_before,
            "error": str(exc),
            "correlation_id": correlation_id,
            "source": source,
            "policy": policy_report,
        }
    finally:
        with _STATE_LOCK:
            _AUTO_REPAIR_IN_PROGRESS = False
            _AUTO_REPAIR_THREAD = None


def trigger_auto_repair(
    *,
    health_data: dict[str, Any],
    planned_actions: list[str] | None = None,
    policy_report: dict[str, Any] | None = None,
    source: str = "alerting",
    correlation_id: str | None = None,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    auto_repair_base_url: str = DEFAULT_BASE_URL,
    auto_repair_min_score: int = DEFAULT_MIN_SCORE,
    auto_repair_dry_run: bool = False,
    auto_repair_safe_mode: bool = False,
) -> dict[str, Any]:
    global _AUTO_REPAIR_IN_PROGRESS, _AUTO_REPAIR_THREAD, _LAST_AUTO_REPAIR_TRIGGER_TS

    now = time.monotonic()
    with _STATE_LOCK:
        if _AUTO_REPAIR_IN_PROGRESS:
            logger.warning("[ACTION] auto_repair skipped (already running)")
            return {
                "triggered": False,
                "reason": "already_running",
            }

        elapsed = now - _LAST_AUTO_REPAIR_TRIGGER_TS
        if _LAST_AUTO_REPAIR_TRIGGER_TS > 0 and elapsed < cooldown_seconds:
            remaining = max(0.0, cooldown_seconds - elapsed)
            logger.warning("[ACTION] auto_repair skipped (cooldown {:.1f}s)", remaining)
            return {
                "triggered": False,
                "reason": "cooldown",
                "cooldown_remaining_s": round(remaining, 2),
            }

        _AUTO_REPAIR_IN_PROGRESS = True
        _LAST_AUTO_REPAIR_TRIGGER_TS = now
        correlation_value = str(correlation_id or uuid.uuid4().hex)
        actions = [str(action).strip() for action in (planned_actions or []) if str(action).strip()]
        thread = threading.Thread(
            target=_run_auto_repair_task,
            kwargs={
                "health_data": dict(health_data),
                "planned_actions": actions,
                "policy_report": dict(policy_report or {}),
                "correlation_id": correlation_value,
                "source": str(source or "alerting"),
                "auto_repair_base_url": auto_repair_base_url,
                "auto_repair_min_score": auto_repair_min_score,
                "auto_repair_dry_run": auto_repair_dry_run,
                "auto_repair_safe_mode": auto_repair_safe_mode,
            },
            name="segyr-auto-repair",
            daemon=True,
        )
        _AUTO_REPAIR_THREAD = thread
        thread.start()

    return {
        "triggered": True,
        "reason": "started",
        "thread_name": thread.name,
        "score_before": _to_int(health_data.get("score"), default=0),
        "actions": actions,
        "correlation_id": correlation_value,
        "source": str(source or "alerting"),
    }


def get_alert_state() -> dict[str, Any]:
    with _STATE_LOCK:
        return {
            "counters": dict(_ALERT_COUNTERS),
            "auto_repair_in_progress": bool(_AUTO_REPAIR_IN_PROGRESS),
            "last_auto_repair_trigger_monotonic": _LAST_AUTO_REPAIR_TRIGGER_TS,
            "last_auto_repair_result": _LAST_AUTO_REPAIR_RESULT,
            "last_policy_report": _LAST_POLICY_REPORT,
            "history": list(_ALERT_HISTORY),
        }


def run_alert_loop(
    *,
    base_url: str = DEFAULT_ALERT_BASE_URL,
    path: str = DEFAULT_HEALTH_PATH,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    auto_repair_base_url: str = DEFAULT_BASE_URL,
    auto_repair_min_score: int = DEFAULT_MIN_SCORE,
    auto_repair_dry_run: bool = False,
    auto_repair_safe_mode: bool = False,
    audit_history_path: str = DEFAULT_AUDIT_HISTORY_PATH,
    audit_history_limit: int = DEFAULT_AUDIT_HISTORY_LIMIT,
    stop_event: threading.Event | None = None,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    global _LAST_POLICY_REPORT

    stop_event = stop_event or threading.Event()
    iterations = 0

    logger.info(
        "alert loop started base_url={} interval={}s cooldown={}s",
        base_url,
        poll_interval_seconds,
        cooldown_seconds,
    )

    while not stop_event.is_set():
        health_data = fetch_health(base_url=base_url, path=path, timeout_s=request_timeout_s)
        level = evaluate_status(health_data)
        if level not in _ALERT_LEVELS:
            level = "CRITICAL"

        _record_alert(level, health_data)

        score = _to_int(health_data.get("score"), default=0)
        status = str(health_data.get("status") or "unknown")

        audit_history = _read_recent_audit_history(path=audit_history_path, limit=audit_history_limit)
        error_frequency = {
            "redis_errors_5m": _recent_redis_error_count(window_seconds=DEFAULT_ERROR_WINDOW_SECONDS),
        }
        policy_report = evaluate_policy(
            health_data=health_data,
            audit_history=audit_history,
            error_frequency=error_frequency,
        )
        with _STATE_LOCK:
            _LAST_POLICY_REPORT = policy_report

        decision = should_repair(policy_report)
        reason_codes = _policy_reason_codes(policy_report, decision=decision)
        logger.warning("[POLICY] decision={} reason={}", "repair" if decision else "skip", reason_codes)

        if level == "OK":
            logger.info("[OK] status={} score={}", status, score)
        elif level == "WARNING":
            logger.warning("[WARNING] status={} score={}", status, score)
        else:
            logger.error("[CRITICAL] status={} score={}", status, score)

        if decision:
            planned_actions = decide_actions(policy_report)
            trigger_result = trigger_auto_repair(
                health_data=health_data,
                planned_actions=planned_actions,
                policy_report=policy_report,
                source="alerting",
                cooldown_seconds=cooldown_seconds,
                auto_repair_base_url=auto_repair_base_url,
                auto_repair_min_score=auto_repair_min_score,
                auto_repair_dry_run=auto_repair_dry_run,
                auto_repair_safe_mode=auto_repair_safe_mode,
            )
            logger.warning("[ACTION] trigger_auto_repair -> {}", trigger_result)

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break

        stop_event.wait(max(0.0, poll_interval_seconds))

    logger.info("alert loop stopped iterations={}", iterations)
    state = get_alert_state()
    state["iterations"] = iterations
    return state


async def run_alert_loop_async(**kwargs: Any) -> dict[str, Any]:
    return await asyncio.to_thread(run_alert_loop, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description="SEGYR alerting loop with auto-repair integration")
    parser.add_argument("--base-url", default=DEFAULT_ALERT_BASE_URL)
    parser.add_argument("--path", default=DEFAULT_HEALTH_PATH)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--cooldown", type=float, default=DEFAULT_COOLDOWN_SECONDS)
    parser.add_argument("--request-timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--auto-repair-base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--auto-repair-min-score", type=int, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--auto-repair-dry-run", action="store_true")
    parser.add_argument("--auto-repair-safe-mode", action="store_true")
    parser.add_argument("--audit-history-path", default=DEFAULT_AUDIT_HISTORY_PATH)
    parser.add_argument("--audit-history-limit", type=int, default=DEFAULT_AUDIT_HISTORY_LIMIT)
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    stop_event = threading.Event()
    try:
        result = run_alert_loop(
            base_url=str(args.base_url),
            path=str(args.path),
            poll_interval_seconds=float(args.poll_interval),
            cooldown_seconds=float(args.cooldown),
            request_timeout_s=float(args.request_timeout),
            auto_repair_base_url=str(args.auto_repair_base_url),
            auto_repair_min_score=int(args.auto_repair_min_score),
            auto_repair_dry_run=bool(args.auto_repair_dry_run),
            auto_repair_safe_mode=bool(args.auto_repair_safe_mode),
            audit_history_path=str(args.audit_history_path),
            audit_history_limit=int(args.audit_history_limit),
            stop_event=stop_event,
            max_iterations=args.max_iterations,
        )
    except KeyboardInterrupt:
        stop_event.set()
        result = get_alert_state()
        result["interrupted"] = True

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
