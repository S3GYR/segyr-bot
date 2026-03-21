from __future__ import annotations

import os
from typing import Any, Iterable, List

from redis import Redis
from rq import Connection, Queue, Worker

from config.settings import settings
from core.memory import MemoryStore
from modules.notifications.service import send_notification
from modules.copilot.daily import generate_daily_copilot


def get_redis_connection() -> Redis:
    return Redis.from_url(settings.redis.url)


def enqueue_default(func, *args, **kwargs):
    with Connection(get_redis_connection()):
        q = Queue("default")
        return q.enqueue(func, *args, **kwargs)


def send_notifications(notifications: Iterable[dict[str, Any]] | None) -> int:
    count = 0
    for notif in notifications or []:
        notif_type = notif.get("type") or "finance"
        message = notif.get("message") or "Alerte"
        meta = {k: v for k, v in notif.items() if k not in {"type", "message"}}
        if send_notification(notif_type, message, meta=meta):
            count += 1
    return count


def run_daily_copilot(entreprise_id: str | None = None) -> dict[str, Any]:
    store = MemoryStore()
    report = generate_daily_copilot(store, entreprise_id=entreprise_id)
    return report


def relance_factures(entreprise_id: str | None = None) -> int:
    store = MemoryStore()
    factures = store.get_unpaid_client_invoices(entreprise_id=entreprise_id) or []
    count = 0
    for f in factures:
        client = store.get_client(f.get("client_id")) if f.get("client_id") else None
        email = (client.get("email") or client.get("contact")) if client else None
        msg = f"Relance facture {f.get('reference') or f.get('id')} - montant {f.get('montant_ht')}"
        if email and send_notification("finance", msg, meta={"email": email}):
            count += 1
    return count


def run_worker(queues: List[str] | None = None) -> None:
    queues = queues or ["default"]
    with Connection(get_redis_connection()):
        worker = Worker([Queue(name) for name in queues])
        worker.work()


if __name__ == "__main__":
    qs = os.getenv("RQ_QUEUES", "default").split(",")
    run_worker(qs)
