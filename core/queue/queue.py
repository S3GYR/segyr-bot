from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass

from redis import Redis
from redis.exceptions import RedisError

from config.settings import settings
from loguru import logger

FALLBACK_QUEUE_KEY = "segyr:queue:segyr"

try:
    from rq import Queue as RQQueue

    _RQ_IMPORT_ERROR: Exception | None = None
except Exception as exc:
    RQQueue = None
    _RQ_IMPORT_ERROR = exc
    logger.warning("RQ indisponible, fallback Redis list activé: {}", exc)

redis_conn = Redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)
queue = RQQueue("segyr", connection=redis_conn) if RQQueue is not None else None


@dataclass
class FallbackJob:
    id: str


def _serialize_payload(func, args: tuple, kwargs: dict) -> str:
    payload = {
        "id": str(uuid.uuid4()),
        "callable": f"{func.__module__}:{getattr(func, '__qualname__', func.__name__)}",
        "args": args,
        "kwargs": kwargs,
        "enqueued_at": time.time(),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def enqueue_task(func, *args, **kwargs):
    if queue is not None:
        job = queue.enqueue(func, *args, **kwargs)
        logger.info("Task enqueue: queue=segyr job_id={}", job.id)
        return job

    body = _serialize_payload(func, args, kwargs)
    try:
        redis_conn.rpush(FALLBACK_QUEUE_KEY, body)
        job = json.loads(body)
        logger.info("Task enqueue: queue=segyr:fallback job_id={}", job["id"])
        return FallbackJob(id=job["id"])
    except RedisError as exc:
        logger.warning("Task enqueue failed (Redis indisponible): {}", exc)
        raise
