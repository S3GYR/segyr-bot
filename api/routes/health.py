from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from core.logging import logger
from api.routes.metrics import update_metrics_from_health

HEALTH_TIMEOUT_S = 10.0

router = APIRouter(tags=["health"])


def _run_health_check() -> dict[str, Any]:
    # Lazy import to avoid loading monitoring code during API startup.
    from run_redis_e2e import get_system_health

    return get_system_health()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/full")
async def health_full() -> dict[str, Any]:
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
        timestamp = str(details.get("timestamp") or datetime.now(timezone.utc).isoformat())
        payload = {
            "status": status,
            "score": score,
            "timestamp": timestamp,
            "details": details,
        }
        update_metrics_from_health(payload)
        return payload
    except asyncio.TimeoutError:
        logger.warning("/health/full timeout after {}s", HEALTH_TIMEOUT_S)
    except Exception:
        logger.exception("/health/full failed")

    payload = {
        "status": "critical",
        "score": 0,
        "error": "health check failed",
    }
    update_metrics_from_health(payload)
    return payload
