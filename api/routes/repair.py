from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from config.settings import settings
from core.logging import logger
from core.monitoring.auto_repair import DEFAULT_HISTORY_PATH, VALID_CORRELATION_SOURCES, run_auto_repair_loop
from modules.auth.utils import decode_token, get_bearer_token

REPAIR_WAIT_TIMEOUT_S = 30.0
RECENT_RESULTS_LIMIT = 20
REPAIR_RATE_LIMIT_SECONDS = 30.0
AUDIT_LOG_PATH = Path("logs/repair_audit.jsonl")
AUDIT_LOG_MAX_BYTES = 5 * 1024 * 1024

router = APIRouter(prefix="/repair", tags=["repair"])

_STATE_LOCK = threading.RLock()
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="segyr-repair")
_CURRENT_FUTURE: Future[dict[str, Any]] | None = None
_CURRENT_MODE = "idle"
_CURRENT_STARTED_AT: str | None = None
_CURRENT_REQUESTED_BY: str | None = None
_CURRENT_CLIENT_IP: str | None = None
_CURRENT_ENDPOINT: str | None = None
_CURRENT_CORRELATION_ID: str | None = None
_CURRENT_SOURCE: str | None = None
_LAST_RESULT: dict[str, Any] | None = None
_LAST_ERROR: str | None = None
_RECENT_RESULTS: deque[dict[str, Any]] = deque(maxlen=RECENT_RESULTS_LIMIT)
_RATE_LIMIT_BY_IP: dict[str, float] = {}
_AUDIT_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_source(source: str | None) -> str:
    raw = str(source or "manual").strip().lower()
    if raw in VALID_CORRELATION_SOURCES:
        return raw
    return "manual"


def _base_payload(state: str) -> dict[str, Any]:
    return {
        "status": state,
        "score_before": None,
        "score_after": None,
        "actions": [],
    }


def _enforce_rate_limit(client_ip: str | None, window_seconds: float = REPAIR_RATE_LIMIT_SECONDS) -> None:
    now = time.monotonic()
    key = client_ip or "unknown"
    with _STATE_LOCK:
        last = _RATE_LIMIT_BY_IP.get(key)
        if last is not None and (now - last) < window_seconds:
            retry_after = max(0.0, window_seconds - (now - last))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit: 1 appel / {int(window_seconds)}s par IP",
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        _RATE_LIMIT_BY_IP[key] = now


def _rotate_audit_log_if_needed(path: Path = AUDIT_LOG_PATH, max_bytes: int = AUDIT_LOG_MAX_BYTES) -> None:
    try:
        if not path.exists():
            return
        if path.stat().st_size < max_bytes:
            return

        rotated = path.with_suffix(f"{path.suffix}.1")
        if rotated.exists():
            try:
                rotated.unlink()
            except Exception as exc:
                logger.warning("audit rotate cleanup failed path={} err={}", rotated, exc)
        path.replace(rotated)
    except Exception as exc:
        logger.warning("audit rotate failed path={} err={}", path, exc)


def append_audit_log(entry: dict[str, Any]) -> None:
    payload = dict(entry or {})
    payload.setdefault("timestamp", _now_iso())

    try:
        line = json.dumps(payload, ensure_ascii=False)
        with _AUDIT_LOCK:
            AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            _rotate_audit_log_if_needed(AUDIT_LOG_PATH, AUDIT_LOG_MAX_BYTES)
            with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.write("\n")
    except Exception as exc:
        logger.warning("append_audit_log failed err={}", exc)


def read_recent_audit_entries(limit: int = 20) -> list[dict[str, Any]]:
    wanted = max(0, int(limit))
    if wanted == 0:
        return []

    with _AUDIT_LOCK:
        if not AUDIT_LOG_PATH.exists():
            return []
        try:
            lines = AUDIT_LOG_PATH.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            logger.warning("read_recent_audit_entries failed path={} err={}", AUDIT_LOG_PATH, exc)
            return []

    results: list[dict[str, Any]] = []
    for raw in lines[-wanted:]:
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                results.append(obj)
        except Exception:
            continue
    return results


def _summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    actions = result.get("actions_executed") if isinstance(result.get("actions_executed"), list) else []
    repaired = bool(result.get("repaired"))
    status_value = str(result.get("status") or "").strip().lower()
    if status_value == "skipped":
        status_final = "skipped"
    elif repaired:
        status_final = "success"
    else:
        status_final = "failed"

    policy_report = result.get("policy_report") if isinstance(result.get("policy_report"), dict) else {}
    if not policy_report and isinstance(result.get("policy"), dict):
        policy_report = dict(result.get("policy") or {})

    summary = _base_payload("completed" if repaired else "needs_attention")
    summary.update(
        {
            "status_final": status_final,
            "status": status_value or status_final,
            "reason": result.get("reason"),
            "score_before": _to_int(result.get("score_before"), default=0),
            "score_after": _to_int(result.get("score_after"), default=0),
            "score_delta_expected": _to_int(result.get("score_delta_expected"), default=0),
            "score_delta_actual": _to_int(result.get("score_delta_actual"), default=0),
            "actions": actions,
            "actions_planned": result.get("actions_planned") if isinstance(result.get("actions_planned"), list) else [],
            "repaired": repaired,
            "dry_run": bool(result.get("dry_run")),
            "started_at": result.get("started_at"),
            "ended_at": result.get("ended_at"),
            "attempt_counts": result.get("attempt_counts", {}),
            "policy_report": policy_report,
            "policy_reason": policy_report.get("reason") or result.get("reason"),
            "policy_decision": "execute" if bool(policy_report.get("should_repair")) else "skip",
            "recommended_actions": (
                policy_report.get("recommended_actions")
                if isinstance(policy_report.get("recommended_actions"), list)
                else []
            ),
            "correlation_id": result.get("correlation_id"),
            "source": result.get("source"),
        }
    )
    return summary


def _read_recent_history(limit: int = RECENT_RESULTS_LIMIT, history_path: Path = DEFAULT_HISTORY_PATH) -> list[dict[str, Any]]:
    path = Path(history_path)
    if not path.exists() or limit <= 0:
        return []

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        logger.warning("repair status history read failed path={} err={}", path, exc)
        return []

    items: list[dict[str, Any]] = []
    for raw in lines[-limit:]:
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                items.append(_summarize_result(obj))
        except Exception:
            continue
    return items


def _refresh_job_state() -> None:
    global _CURRENT_FUTURE, _CURRENT_MODE, _CURRENT_STARTED_AT, _CURRENT_REQUESTED_BY, _CURRENT_CLIENT_IP, _CURRENT_ENDPOINT, _CURRENT_CORRELATION_ID, _CURRENT_SOURCE, _LAST_RESULT, _LAST_ERROR

    with _STATE_LOCK:
        future = _CURRENT_FUTURE

    if future is None or not future.done():
        return

    current_mode = _CURRENT_MODE
    current_requested_by = _CURRENT_REQUESTED_BY
    current_client_ip = _CURRENT_CLIENT_IP
    current_endpoint = _CURRENT_ENDPOINT
    current_correlation_id = _CURRENT_CORRELATION_ID
    current_source = _CURRENT_SOURCE

    try:
        result = future.result()
        summary = _summarize_result(result)
        logger.info(
            "repair completed mode={} by={} ip={} correlation_id={} source={} repaired={} score_before={} score_after={}",
            current_mode,
            current_requested_by,
            current_client_ip,
            current_correlation_id,
            current_source,
            summary.get("repaired"),
            summary.get("score_before"),
            summary.get("score_after"),
        )
        with _STATE_LOCK:
            summary["requested_by"] = current_requested_by
            summary["client_ip"] = current_client_ip
            summary["endpoint"] = current_endpoint
            summary["correlation_id"] = summary.get("correlation_id") or current_correlation_id
            summary["source"] = summary.get("source") or current_source
            _LAST_RESULT = summary
            _LAST_ERROR = None
            _RECENT_RESULTS.append(summary)
            _CURRENT_FUTURE = None
            _CURRENT_MODE = "idle"
            _CURRENT_STARTED_AT = None
            _CURRENT_REQUESTED_BY = None
            _CURRENT_CLIENT_IP = None
            _CURRENT_ENDPOINT = None
            _CURRENT_CORRELATION_ID = None
            _CURRENT_SOURCE = None

        append_audit_log(
            {
                "endpoint": summary.get("endpoint") or "/repair/run",
                "requested_by": summary.get("requested_by"),
                "client_ip": summary.get("client_ip"),
                "mode": "dry_run" if summary.get("dry_run") else "real",
                "correlation_id": summary.get("correlation_id"),
                "source": summary.get("source"),
                "score_before": summary.get("score_before"),
                "score_after": summary.get("score_after"),
                "actions": summary.get("actions", []),
                "status_final": "success" if summary.get("repaired") else "failed",
            }
        )
    except Exception as exc:
        logger.exception("repair worker failed")
        failure = _base_payload("failed")
        failure["error"] = str(exc)
        failure["requested_by"] = current_requested_by
        failure["client_ip"] = current_client_ip
        failure["endpoint"] = current_endpoint
        failure["correlation_id"] = current_correlation_id
        failure["source"] = current_source
        with _STATE_LOCK:
            _LAST_RESULT = failure
            _LAST_ERROR = str(exc)
            _RECENT_RESULTS.append(failure)
            _CURRENT_FUTURE = None
            _CURRENT_MODE = "idle"
            _CURRENT_STARTED_AT = None
            _CURRENT_REQUESTED_BY = None
            _CURRENT_CLIENT_IP = None
            _CURRENT_ENDPOINT = None
            _CURRENT_CORRELATION_ID = None
            _CURRENT_SOURCE = None

        append_audit_log(
            {
                "endpoint": failure.get("endpoint") or "/repair/run",
                "requested_by": failure.get("requested_by"),
                "client_ip": failure.get("client_ip"),
                "mode": "dry_run" if current_mode == "dry-run" else "real",
                "correlation_id": failure.get("correlation_id"),
                "source": failure.get("source"),
                "score_before": None,
                "score_after": None,
                "actions": [],
                "status_final": "failed",
            }
        )


def _submit_repair_job(
    *,
    dry_run: bool,
    requested_by: str | None,
    client_ip: str | None,
    endpoint: str,
    correlation_id: str,
    source: str,
) -> dict[str, Any]:
    global _CURRENT_FUTURE, _CURRENT_MODE, _CURRENT_STARTED_AT, _CURRENT_REQUESTED_BY, _CURRENT_CLIENT_IP, _CURRENT_ENDPOINT, _CURRENT_CORRELATION_ID, _CURRENT_SOURCE, _LAST_ERROR

    _refresh_job_state()
    with _STATE_LOCK:
        if _CURRENT_FUTURE is not None and not _CURRENT_FUTURE.done():
            running = _base_payload("running")
            running.update(
                {
                    "mode": _CURRENT_MODE,
                    "started_at": _CURRENT_STARTED_AT,
                    "requested_by": _CURRENT_REQUESTED_BY,
                    "client_ip": _CURRENT_CLIENT_IP,
                    "endpoint": _CURRENT_ENDPOINT,
                    "correlation_id": _CURRENT_CORRELATION_ID,
                    "source": _CURRENT_SOURCE,
                }
            )
            return running

        mode = "dry-run" if dry_run else "run"
        try:
            _CURRENT_MODE = mode
            _CURRENT_STARTED_AT = _now_iso()
            _CURRENT_REQUESTED_BY = requested_by
            _CURRENT_CLIENT_IP = client_ip
            _CURRENT_ENDPOINT = endpoint
            _CURRENT_CORRELATION_ID = correlation_id
            _CURRENT_SOURCE = _normalize_source(source)
            _CURRENT_FUTURE = _EXECUTOR.submit(
                run_auto_repair_loop,
                dry_run=dry_run,
                correlation_id=_CURRENT_CORRELATION_ID,
                source=_CURRENT_SOURCE,
            )
            _LAST_ERROR = None
            logger.warning(
                "repair started mode={} started_at={} by={} ip={} correlation_id={} source={}",
                mode,
                _CURRENT_STARTED_AT,
                _CURRENT_REQUESTED_BY,
                _CURRENT_CLIENT_IP,
                _CURRENT_CORRELATION_ID,
                _CURRENT_SOURCE,
            )
            payload = _base_payload("started")
            payload.update(
                {
                    "mode": mode,
                    "started_at": _CURRENT_STARTED_AT,
                    "requested_by": _CURRENT_REQUESTED_BY,
                    "client_ip": _CURRENT_CLIENT_IP,
                    "endpoint": _CURRENT_ENDPOINT,
                    "correlation_id": _CURRENT_CORRELATION_ID,
                    "source": _CURRENT_SOURCE,
                }
            )
            return payload
        except Exception as exc:
            logger.exception("repair start failed")
            _CURRENT_FUTURE = None
            _CURRENT_MODE = "idle"
            _CURRENT_STARTED_AT = None
            _CURRENT_REQUESTED_BY = None
            _CURRENT_CLIENT_IP = None
            _CURRENT_ENDPOINT = None
            _CURRENT_CORRELATION_ID = None
            _CURRENT_SOURCE = None
            _LAST_ERROR = str(exc)
            failed = _base_payload("failed")
            failed["error"] = str(exc)
            failed["endpoint"] = endpoint
            failed["requested_by"] = requested_by
            failed["client_ip"] = client_ip
            failed["correlation_id"] = correlation_id
            failed["source"] = _normalize_source(source)
            failed["mode"] = "dry_run" if dry_run else "real"
            append_audit_log(
                {
                    "endpoint": endpoint,
                    "requested_by": requested_by,
                    "client_ip": client_ip,
                    "mode": "dry_run" if dry_run else "real",
                    "correlation_id": correlation_id,
                    "source": _normalize_source(source),
                    "score_before": None,
                    "score_after": None,
                    "actions": [],
                    "status_final": "failed",
                }
            )
            return failed


async def _wait_current_job(timeout_s: float = REPAIR_WAIT_TIMEOUT_S) -> dict[str, Any]:
    with _STATE_LOCK:
        future = _CURRENT_FUTURE
        mode = _CURRENT_MODE
        started_at = _CURRENT_STARTED_AT
        requested_by = _CURRENT_REQUESTED_BY
        client_ip = _CURRENT_CLIENT_IP
        endpoint = _CURRENT_ENDPOINT
        correlation_id = _CURRENT_CORRELATION_ID
        source = _CURRENT_SOURCE

    if future is None:
        return _LAST_RESULT or _base_payload("idle")

    try:
        result = await asyncio.to_thread(future.result, timeout_s)
        summary = _summarize_result(result)
        _refresh_job_state()
        return summary
    except FuturesTimeoutError:
        payload = _base_payload("running")
        payload.update(
            {
                "mode": mode,
                "started_at": started_at,
                "requested_by": requested_by,
                "client_ip": client_ip,
                "endpoint": endpoint,
                "correlation_id": correlation_id,
                "source": source,
            }
        )
        return payload
    except Exception as exc:
        logger.exception("repair wait failed")
        failure = _base_payload("failed")
        failure["error"] = str(exc)
        with _STATE_LOCK:
            _LAST_ERROR = str(exc)
        return failure


async def require_repair_access(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None, alias=settings.api_token_header),
) -> dict[str, Any]:
    client_ip = request.client.host if request.client else None

    if not x_api_token and not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise")

    if x_api_token:
        if not settings.api_auth_token or x_api_token != settings.api_auth_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token API invalide")
        _enforce_rate_limit(client_ip)
        return {
            "auth": "api_token",
            "identity": "api_token",
            "client_ip": client_ip,
        }

    try:
        token = get_bearer_token(authorization)
        payload = decode_token(token)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="JWT invalide") from exc
        raise

    _enforce_rate_limit(client_ip)
    user_id = str(payload.get("user_id") or "unknown")
    return {
        "auth": "jwt",
        "user_id": user_id,
        "identity": f"jwt:{user_id}",
        "client_ip": client_ip,
    }


@router.post("/run")
async def repair_run(auth_ctx: dict[str, Any] = Depends(require_repair_access)) -> dict[str, Any]:
    endpoint = "/repair/run"
    correlation_id = uuid.uuid4().hex
    source = "manual"
    try:
        start_state = _submit_repair_job(
            dry_run=False,
            requested_by=str(auth_ctx.get("identity") or "unknown"),
            client_ip=auth_ctx.get("client_ip"),
            endpoint=endpoint,
            correlation_id=correlation_id,
            source=source,
        )
        if start_state.get("status") == "failed":
            return start_state
        if start_state.get("status") == "running":
            append_audit_log(
                {
                    "endpoint": endpoint,
                    "requested_by": auth_ctx.get("identity"),
                    "client_ip": auth_ctx.get("client_ip"),
                    "mode": "real",
                    "correlation_id": correlation_id,
                    "source": source,
                    "score_before": None,
                    "score_after": None,
                    "actions": [],
                    "status_final": "failed",
                }
            )
            return start_state
        return await _wait_current_job(timeout_s=REPAIR_WAIT_TIMEOUT_S)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("/repair/run failed")
        payload = _base_payload("failed")
        payload["error"] = str(exc)
        return payload


@router.post("/dry-run")
async def repair_dry_run(auth_ctx: dict[str, Any] = Depends(require_repair_access)) -> dict[str, Any]:
    endpoint = "/repair/dry-run"
    correlation_id = uuid.uuid4().hex
    source = "manual"
    try:
        start_state = _submit_repair_job(
            dry_run=True,
            requested_by=str(auth_ctx.get("identity") or "unknown"),
            client_ip=auth_ctx.get("client_ip"),
            endpoint=endpoint,
            correlation_id=correlation_id,
            source=source,
        )
        if start_state.get("status") == "failed":
            return start_state
        if start_state.get("status") == "running":
            append_audit_log(
                {
                    "endpoint": endpoint,
                    "requested_by": auth_ctx.get("identity"),
                    "client_ip": auth_ctx.get("client_ip"),
                    "mode": "dry_run",
                    "correlation_id": correlation_id,
                    "source": source,
                    "score_before": None,
                    "score_after": None,
                    "actions": [],
                    "status_final": "failed",
                }
            )
            return start_state
        return await _wait_current_job(timeout_s=REPAIR_WAIT_TIMEOUT_S)
    except Exception as exc:
        logger.exception("/repair/dry-run failed")
        payload = _base_payload("failed")
        payload["error"] = str(exc)
        return payload


@router.get("/status")
async def repair_status(limit: int = 10) -> dict[str, Any]:
    try:
        _refresh_job_state()
        history_limit = max(1, min(int(limit), 100))
        with _STATE_LOCK:
            running = _CURRENT_FUTURE is not None and not _CURRENT_FUTURE.done()
            state = {
                "status": "running" if running else "idle",
                "mode": _CURRENT_MODE,
                "started_at": _CURRENT_STARTED_AT,
                "requested_by": _CURRENT_REQUESTED_BY,
                "client_ip": _CURRENT_CLIENT_IP,
                "correlation_id": _CURRENT_CORRELATION_ID,
                "source": _CURRENT_SOURCE,
                "last_result": _LAST_RESULT,
                "last_error": _LAST_ERROR,
                "recent_results": list(_RECENT_RESULTS)[-history_limit:],
            }

        state["recent_history"] = _read_recent_history(limit=history_limit)
        state["recent_audit"] = read_recent_audit_entries(limit=history_limit)
        return state
    except Exception as exc:
        logger.exception("/repair/status failed")
        return {
            "status": "failed",
            "error": str(exc),
            "last_result": _LAST_RESULT,
            "recent_results": list(_RECENT_RESULTS),
            "recent_history": [],
            "recent_audit": [],
        }
