from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# Keep script runnable even when env is not fully configured.
os.environ.setdefault("SEGYR_JWT_SECRET", "dev-secret")
os.environ.setdefault("SEGYR_DB_PASSWORD", "dev-db")

from config.settings import settings
from core.queue.queue import FALLBACK_QUEUE_KEY, enqueue_task, queue as rq_runtime_queue, redis_conn
from core.redis.client import get_redis
from core.redis_memory import get_history

COMPONENT_WEIGHTS = {
    "redis": 15,
    "gateway": 15,
    "skill": 10,
    "cache": 25,
    "memory": 20,
    "queue": 15,
}

VALID_SOURCES = {"ci", "manual", "alerting"}


def queue_probe_write(marker_key: str, token: str) -> bool:
    """Callable used by queue test to prove real execution."""
    redis = get_redis()
    return bool(redis.setex(marker_key, 120, token))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_source(source: str | None) -> str:
    raw = str(source or "manual").strip().lower()
    if raw in VALID_SOURCES:
        return raw
    return "manual"


def _percentile(values: list[float], p: int) -> float | None:
    if not values:
        return None
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100)
    low = int(k)
    high = min(low + 1, len(ordered) - 1)
    if low == high:
        return ordered[low]
    frac = k - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


def _count_keys(pattern: str) -> int:
    try:
        redis = get_redis()
        return sum(1 for _ in redis.scan_iter(match=pattern, count=200))
    except Exception:
        return 0


def _post_message(base_url: str, sender: str, chat_id: str, text: str, timeout: int) -> tuple[int, dict[str, Any], float]:
    url = f"{base_url.rstrip('/')}/message"
    payload = {"sender": sender, "chat_id": chat_id, "text": text}
    t0 = time.perf_counter()
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        dt = time.perf_counter() - t0
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text}
        return resp.status_code, body, dt
    except Exception as exc:
        dt = time.perf_counter() - t0
        return 0, {"error": str(exc)}, dt


def check_gateway(base_url: str, timeout: int = 5) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        t0 = time.perf_counter()
        resp = requests.get(f"{base_url.rstrip('/')}/health", timeout=timeout)
        dt = time.perf_counter() - t0
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text}
        ok = resp.status_code == 200
        if not ok:
            warnings.append(f"Gateway health HTTP {resp.status_code}")
        return {
            "ok": ok,
            "status": resp.status_code,
            "latency_s": round(dt, 4),
            "info": body,
            "warnings": warnings,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": 0,
            "latency_s": None,
            "info": str(exc),
            "warnings": [f"Gateway indisponible: {exc}"],
        }


def check_redis() -> dict[str, Any]:
    warnings: list[str] = []
    t0 = time.perf_counter()
    try:
        ok = bool(get_redis().ping())
        dt = time.perf_counter() - t0
        if not ok:
            warnings.append("Redis ping false")
        if dt > 0.25:
            warnings.append(f"Latence Redis élevée: {dt:.3f}s")
        return {
            "ok": ok,
            "latency_s": round(dt, 4),
            "error": None,
            "warnings": warnings,
        }
    except Exception as exc:
        dt = time.perf_counter() - t0
        return {
            "ok": False,
            "latency_s": round(dt, 4),
            "error": str(exc),
            "warnings": [f"Redis indisponible: {exc}"],
        }


def test_skill(base_url: str, sender: str, chat_id: str, timeout: int = 30) -> dict[str, Any]:
    status, body, dt = _post_message(base_url, sender, chat_id, "echo bonjour", timeout=timeout)
    reply = str(body.get("reply", ""))
    ok = status == 200 and "bonjour" in reply.lower()
    warnings: list[str] = []
    if not ok:
        warnings.append("Skill echo ne répond pas comme attendu")
    return {
        "ok": ok,
        "status": status,
        "reply": reply,
        "duration_s": round(dt, 4),
        "warnings": warnings,
    }


def _build_loop_cache_key(chat_id: str, model: str, message: str) -> str:
    payload = {
        "session": f"webhook:{chat_id}",
        "channel": "webhook",
        "chat_id": chat_id,
        "model": model,
        "message": (message or "").strip(),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"segyr:llm_cache:{digest}"


def test_cache(
    base_url: str,
    sender: str,
    chat_id: str,
    prompt: str,
    timeout: int,
    settle_seconds: int,
    model: str,
) -> dict[str, Any]:
    warnings: list[str] = []
    redis = get_redis()
    cache_key = _build_loop_cache_key(chat_id=chat_id, model=model, message=prompt)

    cache_count_before = _count_keys("segyr:llm_cache:*")
    first_status, first_body, first_dt = _post_message(base_url, sender, chat_id, prompt, timeout=timeout)

    time.sleep(max(0, settle_seconds))

    cached_value = None
    try:
        cached_value = redis.get(cache_key)
    except Exception as exc:
        warnings.append(f"Lecture cache directe impossible: {exc}")

    cache_count_after = _count_keys("segyr:llm_cache:*")
    second_status, second_body, second_dt = _post_message(base_url, sender, chat_id, prompt, timeout=timeout)

    first_reply = str(first_body.get("reply", ""))
    second_reply = str(second_body.get("reply", ""))

    latency_ratio = (second_dt / first_dt) if first_dt > 0 else None
    fast_enough = second_dt <= 0.3 or (latency_ratio is not None and latency_ratio <= 0.8)
    cache_stored = bool(cached_value) or (cache_count_after > cache_count_before)

    if not cache_stored:
        warnings.append("Aucune preuve de stockage cache détectée")
    if latency_ratio is not None and latency_ratio > 0.7:
        warnings.append(f"Cache peu efficace (ratio latence={latency_ratio:.2f})")
    if second_reply.strip().lower() == "traitement en cours":
        warnings.append("Deuxième réponse encore en timeout (cache probablement non utilisé)")

    ok = (
        first_status == 200
        and second_status == 200
        and cache_stored
        and fast_enough
    )

    return {
        "ok": ok,
        "model": model,
        "cache_key": cache_key,
        "cached_value_present": bool(cached_value),
        "cache_count_before": cache_count_before,
        "cache_count_after": cache_count_after,
        "latency_ratio": round(latency_ratio, 4) if latency_ratio is not None else None,
        "first": {
            "status": first_status,
            "reply": first_reply,
            "duration_s": round(first_dt, 4),
        },
        "second": {
            "status": second_status,
            "reply": second_reply,
            "duration_s": round(second_dt, 4),
        },
        "warnings": warnings,
    }


def _contains_sequence(entries: list[dict[str, str]], expected: list[tuple[str, str | None]]) -> bool:
    idx = 0
    for role, fragment in expected:
        found = False
        while idx < len(entries):
            cur = entries[idx]
            idx += 1
            if cur.get("role") != role:
                continue
            content = str(cur.get("content", "")).strip()
            if not content:
                continue
            if fragment is None or fragment.lower() in content.lower():
                found = True
                break
        if not found:
            return False
    return True


def test_memory(chat_id: str, prompt: str) -> dict[str, Any]:
    history = get_history(chat_id, limit=30)
    warnings: list[str] = []

    structure_ok = True
    for i, row in enumerate(history):
        role = row.get("role")
        content = row.get("content")
        if not isinstance(role, str) or not role.strip() or not isinstance(content, str) or not content.strip():
            structure_ok = False
            warnings.append(f"Entrée mémoire invalide index={i}")
            break

    expected_sequence = [
        ("user", "echo bonjour"),
        ("assistant", "bonjour"),
        ("user", prompt),
        ("assistant", None),
        ("user", prompt),
        ("assistant", None),
    ]
    order_ok = _contains_sequence(history, expected_sequence)

    pending_users = 0
    for row in history:
        role = row.get("role")
        if role == "user":
            pending_users += 1
        elif role == "assistant" and pending_users > 0:
            pending_users -= 1
    coherence_ok = pending_users == 0 and any(r.get("role") == "assistant" for r in history)

    if not order_ok:
        warnings.append("Ordre conversationnel Redis inattendu")
    if not coherence_ok:
        warnings.append("Incohérence user/assistant dans l'historique Redis")

    ok = structure_ok and order_ok and coherence_ok
    return {
        "ok": ok,
        "structure_ok": structure_ok,
        "order_ok": order_ok,
        "coherence_ok": coherence_ok,
        "entries_count": len(history),
        "entries": history,
        "warnings": warnings,
    }


def _resolve_callable(path: str):
    module_name, func_name = path.split(":", 1)
    module = __import__(module_name, fromlist=["*"])
    target = module
    for attr in func_name.split("."):
        target = getattr(target, attr)
    return target


def _consume_fallback_job(job_id: str) -> tuple[bool, str | None]:
    try:
        items = redis_conn.lrange(FALLBACK_QUEUE_KEY, 0, -1)
    except Exception as exc:
        return False, f"Lecture fallback queue impossible: {exc}"

    for raw in items:
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if str(payload.get("id")) != str(job_id):
            continue
        try:
            redis_conn.lrem(FALLBACK_QUEUE_KEY, 1, raw)
            fn = _resolve_callable(str(payload["callable"]))
            args = payload.get("args") or []
            kwargs = payload.get("kwargs") or {}
            fn(*args, **kwargs)
            return True, None
        except Exception as exc:
            return False, f"Exécution fallback locale échouée: {exc}"

    return False, "Job introuvable dans la fallback queue"


def test_queue(wait_seconds: float = 6.0, allow_local_fallback_consume: bool = True) -> dict[str, Any]:
    mode = "rq" if rq_runtime_queue is not None else "redis_fallback"
    warnings: list[str] = []

    marker_key = f"segyr:queue:probe:{uuid.uuid4().hex[:8]}"
    marker_token = uuid.uuid4().hex

    try:
        redis_conn.delete(marker_key)
    except Exception:
        pass

    try:
        pending_before = redis_conn.llen(FALLBACK_QUEUE_KEY)
    except Exception:
        pending_before = None

    enqueued = False
    executed = False
    local_fallback_executed = False
    queue_status: str | None = None
    job_id: str | None = None

    try:
        job = enqueue_task(queue_probe_write, marker_key, marker_token)
        job_id = str(job.id)
        enqueued = True
        if hasattr(job, "get_status"):
            try:
                queue_status = job.get_status(refresh=True)
            except Exception:
                queue_status = None
    except Exception as exc:
        return {
            "ok": False,
            "mode": mode,
            "enqueued": False,
            "executed": False,
            "job_id": None,
            "queue_status": None,
            "pending_before": pending_before,
            "pending_after": pending_before,
            "local_fallback_executed": False,
            "warnings": [f"Enqueue queue échoué: {exc}"],
            "error": str(exc),
        }

    deadline = time.time() + max(0.5, wait_seconds)
    while time.time() < deadline:
        try:
            if redis_conn.get(marker_key) == marker_token:
                executed = True
                break
        except Exception:
            pass
        time.sleep(0.25)

    if not executed and mode == "redis_fallback" and allow_local_fallback_consume and job_id:
        local_fallback_executed, err = _consume_fallback_job(job_id)
        if err:
            warnings.append(err)
        time.sleep(0.1)
        try:
            executed = redis_conn.get(marker_key) == marker_token
        except Exception:
            executed = False

    if not executed:
        if mode == "rq":
            warnings.append("Job RQ non exécuté (worker probablement absent)")
        else:
            warnings.append("Job fallback queue non exécuté")

    try:
        pending_after = redis_conn.llen(FALLBACK_QUEUE_KEY)
    except Exception:
        pending_after = pending_before

    ok = enqueued and executed
    return {
        "ok": ok,
        "mode": mode,
        "enqueued": enqueued,
        "executed": executed,
        "job_id": job_id,
        "queue_status": queue_status,
        "pending_before": pending_before,
        "pending_after": pending_after,
        "local_fallback_executed": local_fallback_executed,
        "warnings": warnings,
    }


def run_stress_test(
    base_url: str,
    sender: str,
    chat_id: str,
    prompt: str,
    timeout: int,
    iterations: int,
) -> dict[str, Any]:
    if iterations <= 0:
        return {
            "enabled": False,
            "ok": True,
            "iterations": 0,
            "warnings": [],
        }

    latencies: list[float] = []
    statuses: list[int] = []
    errors = 0

    for _ in range(iterations):
        status, _, dt = _post_message(base_url, sender, chat_id, prompt, timeout=timeout)
        statuses.append(status)
        if status == 200:
            latencies.append(dt)
        else:
            errors += 1

    avg = (sum(latencies) / len(latencies)) if latencies else None
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)
    fast_hits = sum(1 for x in latencies if x <= 0.35)
    hit_ratio = (fast_hits / len(latencies)) if latencies else 0.0

    warnings: list[str] = []
    if errors > 0:
        warnings.append(f"Stress: {errors}/{iterations} requêtes en erreur")
    if p95 is not None and p95 > 1.0:
        warnings.append(f"Stress: p95 latence élevée ({p95:.3f}s)")
    if hit_ratio < 0.7:
        warnings.append(f"Stress: ratio réponses rapides faible ({hit_ratio:.2f})")

    ok = errors == 0 and (p95 is None or p95 <= 1.0)
    return {
        "enabled": True,
        "ok": ok,
        "iterations": iterations,
        "errors": errors,
        "avg_s": round(avg, 4) if avg is not None else None,
        "p95_s": round(p95, 4) if p95 is not None else None,
        "p99_s": round(p99, 4) if p99 is not None else None,
        "fast_hit_ratio": round(hit_ratio, 4),
        "status_codes": statuses,
        "warnings": warnings,
    }


def compute_score(results: dict[str, Any]) -> dict[str, Any]:
    redis_res = results.get("redis", {})
    gateway_res = results.get("gateway", {})
    skill_res = results.get("skill", {})
    cache_res = results.get("cache", {})
    memory_res = results.get("memory", {})
    queue_res = results.get("queue", {})
    stress_res = results.get("stress", {"enabled": False, "ok": True})

    component_scores: dict[str, int] = {
        "redis": COMPONENT_WEIGHTS["redis"] if redis_res.get("ok") else 0,
        "gateway": COMPONENT_WEIGHTS["gateway"] if gateway_res.get("ok") else 0,
        "skill": COMPONENT_WEIGHTS["skill"] if skill_res.get("ok") else 0,
        "cache": 0,
        "memory": 0,
        "queue": 0,
    }

    if cache_res.get("ok"):
        component_scores["cache"] = COMPONENT_WEIGHTS["cache"]
    elif cache_res.get("cached_value_present") or (
        cache_res.get("cache_count_after", 0) > cache_res.get("cache_count_before", 0)
    ):
        component_scores["cache"] = 12

    if memory_res.get("ok"):
        component_scores["memory"] = COMPONENT_WEIGHTS["memory"]
    elif memory_res.get("structure_ok"):
        component_scores["memory"] = 10

    if queue_res.get("executed"):
        component_scores["queue"] = COMPONENT_WEIGHTS["queue"]
    elif queue_res.get("enqueued"):
        component_scores["queue"] = 7

    score = sum(component_scores.values())

    warnings: list[str] = []
    for key in ("redis", "gateway", "skill", "cache", "memory", "queue", "stress"):
        part = results.get(key, {})
        warnings.extend([str(w) for w in part.get("warnings", [])])

    critical_components = []
    if not redis_res.get("ok"):
        critical_components.append("redis")
    if not gateway_res.get("ok"):
        critical_components.append("gateway")

    if critical_components or score < 60:
        status = "critical"
    elif score < 85 or warnings:
        status = "degraded"
    else:
        status = "healthy"

    all_ok = bool(
        redis_res.get("ok")
        and gateway_res.get("ok")
        and skill_res.get("ok")
        and cache_res.get("ok")
        and memory_res.get("ok")
        and queue_res.get("ok")
        and (not stress_res.get("enabled") or stress_res.get("ok"))
    )

    return {
        "score": score,
        "status": status,
        "component_scores": component_scores,
        "warnings": warnings,
        "all_ok": all_ok,
    }


def get_system_health(
    results: dict[str, Any] | None = None,
    *,
    correlation_id: str | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    correlation_value = str((results or {}).get("correlation_id") or correlation_id or uuid.uuid4().hex)
    source_value = _normalize_source((results or {}).get("source") or source)

    if results is None:
        redis_result = check_redis()
        redis_ok = bool(redis_result.get("ok"))
        status = "healthy" if redis_ok else "critical"
        score = 100 if redis_ok else 0
        warnings = list(redis_result.get("warnings", []))
        if redis_result.get("error"):
            warnings.append(str(redis_result["error"]))
        return {
            "timestamp": _now_iso(),
            "correlation_id": correlation_value,
            "source": source_value,
            "status": status,
            "score": score,
            "all_ok": redis_ok,
            "warnings": warnings,
            "warnings_count": len(warnings),
            "components": {
                "api": True,
                "redis": redis_ok,
            },
            "details": {
                "redis": redis_result,
            },
        }

    return {
        "timestamp": _now_iso(),
        "correlation_id": correlation_value,
        "source": source_value,
        "status": results.get("status", "unknown"),
        "score": results.get("score", 0),
        "all_ok": bool(results.get("all_ok", False)),
        "warnings_count": len(results.get("warnings", [])),
        "components": {
            "redis": bool(results.get("redis", {}).get("ok")),
            "gateway": bool(results.get("gateway", {}).get("ok")),
            "skill": bool(results.get("skill", {}).get("ok")),
            "cache": bool(results.get("cache", {}).get("ok")),
            "memory": bool(results.get("memory", {}).get("ok")),
            "queue": bool(results.get("queue", {}).get("ok")),
        },
    }


def export_results(results: dict[str, Any], export_dir: str = "logs", enabled: bool = True) -> str | None:
    if not enabled:
        return None
    path = Path(export_dir)
    path.mkdir(parents=True, exist_ok=True)
    filename = f"redis_e2e_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    target = path / filename
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def main() -> int:
    parser = argparse.ArgumentParser(description="SEGYR Redis E2E (cache + memory + queue)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--sender", default="redis-e2e")
    parser.add_argument("--prompt", default="capitale france")
    parser.add_argument("--settle-seconds", type=int, default=25)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--model", default=os.getenv("SEGYR_LLM_MODEL") or settings.llm_model)
    parser.add_argument("--queue-wait-seconds", type=float, default=6.0)
    parser.add_argument("--stress", type=int, default=0, help="Nombre d'itérations supplémentaires")
    parser.add_argument("--export-dir", default="logs")
    parser.add_argument("--no-export", action="store_true")
    parser.add_argument("--disable-local-fallback-consume", action="store_true")
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument("--source", default="manual", choices=sorted(VALID_SOURCES))
    args = parser.parse_args()

    correlation_value = str(args.correlation_id or uuid.uuid4().hex)
    source_value = _normalize_source(args.source)

    redis_result = check_redis()
    gateway_result = check_gateway(args.base_url)
    chat_id = f"redis-e2e-{uuid.uuid4().hex[:8]}"
    memory_key = f"segyr:memory:{chat_id}"
    redis = get_redis()

    try:
        redis.delete(memory_key)
    except Exception:
        pass

    if gateway_result.get("ok"):
        skill_result = test_skill(args.base_url, args.sender, chat_id)
        cache_result = test_cache(
            base_url=args.base_url,
            sender=args.sender,
            chat_id=chat_id,
            prompt=args.prompt,
            timeout=args.timeout,
            settle_seconds=args.settle_seconds,
            model=args.model,
        )
        memory_result = test_memory(chat_id=chat_id, prompt=args.prompt)
        stress_result = run_stress_test(
            base_url=args.base_url,
            sender=args.sender,
            chat_id=chat_id,
            prompt=args.prompt,
            timeout=args.timeout,
            iterations=args.stress,
        )
    else:
        skill_result = {
            "ok": False,
            "warnings": ["Test skill ignoré: gateway indisponible"],
        }
        cache_result = {
            "ok": False,
            "warnings": ["Test cache ignoré: gateway indisponible"],
        }
        memory_result = {
            "ok": False,
            "warnings": ["Test mémoire ignoré: gateway indisponible"],
            "entries": [],
            "entries_count": 0,
            "structure_ok": False,
            "order_ok": False,
            "coherence_ok": False,
        }
        stress_result = {
            "enabled": args.stress > 0,
            "ok": False if args.stress > 0 else True,
            "iterations": args.stress,
            "warnings": ["Stress ignoré: gateway indisponible"] if args.stress > 0 else [],
        }

    queue_result = test_queue(
        wait_seconds=args.queue_wait_seconds,
        allow_local_fallback_consume=not args.disable_local_fallback_consume,
    )

    result = {
        "timestamp": _now_iso(),
        "correlation_id": correlation_value,
        "source": source_value,
        "chat_id": chat_id,
        "redis": redis_result,
        "gateway": gateway_result,
        "skill": skill_result,
        "cache": cache_result,
        "memory": memory_result,
        "queue": queue_result,
        "stress": stress_result,
    }

    eval_result = compute_score(result)
    result.update(eval_result)
    result["system_health"] = get_system_health(
        result,
        correlation_id=correlation_value,
        source=source_value,
    )

    export_path = export_results(
        result,
        export_dir=args.export_dir,
        enabled=not args.no_export,
    )
    result["export_path"] = export_path

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if bool(result.get("all_ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
