from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from api.routes.metrics import update_metrics_from_health
from api.routes.repair import repair_status
from core.logging import logger
from core.monitoring.policy_engine import decide_actions, evaluate_policy, should_repair

HEALTH_TIMEOUT_S = 10.0
DEFAULT_HISTORY_LIMIT = 20

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_health_check() -> dict[str, Any]:
    from run_redis_e2e import get_system_health

    return get_system_health()


def _policy_reason(policy_report: dict[str, Any]) -> str:
    suppressions = policy_report.get("suppressions")
    if isinstance(suppressions, list) and suppressions:
        first = suppressions[0] if isinstance(suppressions[0], dict) else {}
        code = str(first.get("code") or "").strip()
        if code:
            return code

    issues = policy_report.get("issues")
    if isinstance(issues, list) and issues:
        first = issues[0] if isinstance(issues[0], dict) else {}
        code = str(first.get("code") or "").strip()
        if code:
            return code

    return "policy_skip"


def _build_policy_payload(health_payload: dict[str, Any], repair_payload: dict[str, Any]) -> dict[str, Any]:
    recent_audit = repair_payload.get("recent_audit") if isinstance(repair_payload.get("recent_audit"), list) else []

    policy_report = evaluate_policy(health_data=health_payload, audit_history=recent_audit)
    recommended_actions = decide_actions(policy_report)
    decision_execute = should_repair(policy_report)
    reason = str(policy_report.get("reason") or _policy_reason(policy_report))
    policy_report["reason"] = reason

    return {
        "decision": "execute" if decision_execute else "skip",
        "reason": reason,
        "recommended_actions": recommended_actions,
        "report": policy_report,
    }


def _build_policy_history(repair_payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = repair_payload.get("recent_history")
    if not isinstance(rows, list):
        return []

    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        items.append(
            {
                "timestamp": row.get("ended_at") or row.get("started_at") or row.get("timestamp"),
                "decision": row.get("policy_decision") or ("execute" if row.get("repaired") else "skip"),
                "reason": row.get("policy_reason") or row.get("reason"),
                "recommended_actions": row.get("recommended_actions") if isinstance(row.get("recommended_actions"), list) else [],
                "correlation_id": row.get("correlation_id"),
            }
        )
    return items


@router.get("/summary")
async def dashboard_summary(limit: int = DEFAULT_HISTORY_LIMIT) -> dict[str, Any]:
    history_limit = max(1, min(int(limit), 100))

    try:
        loop = asyncio.get_running_loop()
        details = await asyncio.wait_for(
            loop.run_in_executor(None, _run_health_check),
            timeout=HEALTH_TIMEOUT_S,
        )
        status = str(details.get("status") or "critical")
        try:
            score = int(details.get("score", 0))
        except Exception:
            score = 0
        health_payload = {
            "status": status,
            "score": score,
            "timestamp": str(details.get("timestamp") or _now_iso()),
            "details": details,
        }
    except asyncio.TimeoutError:
        logger.warning("/dashboard/summary health timeout after {}s", HEALTH_TIMEOUT_S)
        health_payload = {
            "status": "critical",
            "score": 0,
            "timestamp": _now_iso(),
            "error": "health timeout",
        }
    except Exception:
        logger.exception("/dashboard/summary health failed")
        health_payload = {
            "status": "critical",
            "score": 0,
            "timestamp": _now_iso(),
            "error": "health check failed",
        }

    update_metrics_from_health(health_payload)

    try:
        repair_payload = await repair_status(limit=history_limit)
    except Exception as exc:
        logger.exception("/dashboard/summary repair status failed")
        repair_payload = {
            "status": "failed",
            "error": str(exc),
            "last_result": None,
            "recent_results": [],
            "recent_history": [],
            "recent_audit": [],
        }

    policy_payload = _build_policy_payload(health_payload, repair_payload)

    return {
        "health": health_payload,
        "policy": policy_payload,
        "repair": repair_payload,
        "history": {
            "repairs": repair_payload.get("recent_history", []),
            "audit": repair_payload.get("recent_audit", []),
            "policy": _build_policy_history(repair_payload),
        },
    }
