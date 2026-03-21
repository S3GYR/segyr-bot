from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logging import logger
from core.monitoring.policy_engine import decide_actions, evaluate_policy, should_repair

MAX_ATTEMPTS_PER_ACTION = 2
DEFAULT_MIN_SCORE = 70
DEFAULT_BASE_URL = "http://127.0.0.1:8090"
DEFAULT_HISTORY_PATH = Path("logs/auto_repair_history.jsonl")
DEFAULT_POLICY_HISTORY_LIMIT = 200
VALID_CORRELATION_SOURCES = {"ci", "manual", "alerting"}

CRITICAL_ISSUES = {"redis_down", "gateway_down", "queue_down"}
DESTRUCTIVE_ACTIONS = {"purge_cache"}

ISSUE_TO_ACTION = {
    "redis_down": "restart_redis",
    "gateway_down": "restart_gateway",
    "queue_down": "restart_queue_worker",
    "cache_inefficient": "purge_cache",
    "llm_latency_high": "restart_gateway",
    "low_score": "restart_gateway",
}

ACTION_COMMANDS: dict[str, list[str]] = {
    "restart_redis": [
        "docker restart segyr-redis",
        "docker restart redis",
        "docker compose restart redis",
        "systemctl restart redis",
        "sc.exe stop redis && sc.exe start redis",
    ],
    "restart_gateway": [
        "docker restart segyr-api",
        "docker restart api",
        "docker compose restart api",
        "systemctl restart segyr-api",
        "systemctl restart segyr-api.service",
    ],
    "restart_queue_worker": [
        "docker restart segyr-worker",
        "docker restart worker",
        "docker compose restart worker",
        "systemctl restart segyr-worker",
        "systemctl restart segyr-worker.service",
    ],
}

ACTION_LABELS = {
    "restart_redis": "Restart Redis service/container",
    "restart_gateway": "Restart gateway service/container",
    "restart_queue_worker": "Restart queue worker service/container",
    "purge_cache": "Purge Redis cache keys",
}


@dataclass(slots=True)
class DetectedIssue:
    code: str
    severity: str
    message: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_source(source: str | None) -> str:
    raw = str(source or "manual").strip().lower()
    if raw in VALID_CORRELATION_SOURCES:
        return raw
    return "manual"


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _extract_details(health_data: dict[str, Any]) -> dict[str, Any]:
    details = health_data.get("details")
    if isinstance(details, dict):
        return details

    # Compatibility with richer payloads where sections are top-level.
    merged: dict[str, Any] = {}
    for key in ("redis", "gateway", "cache", "queue", "memory", "skill", "stress"):
        part = health_data.get(key)
        if isinstance(part, dict):
            merged[key] = part
    return merged


def _component_ok(health_data: dict[str, Any], details: dict[str, Any], name: str) -> bool | None:
    components = health_data.get("components")
    if isinstance(components, dict) and name in components:
        return bool(components.get(name))

    part = details.get(name)
    if isinstance(part, dict) and "ok" in part:
        return bool(part.get("ok"))

    return None


def _collect_health_snapshot(
    base_url: str = DEFAULT_BASE_URL,
    include_queue: bool = True,
    correlation_id: str | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    from run_redis_e2e import check_gateway, check_redis, get_system_health, test_queue

    try:
        data = get_system_health(correlation_id=correlation_id, source=source)
    except Exception as exc:
        logger.exception("auto_repair health snapshot failed")
        return {
            "timestamp": _now_iso(),
            "status": "critical",
            "score": 0,
            "details": {},
            "errors": [str(exc)],
        }

    if not isinstance(data, dict):
        data = {"status": "critical", "score": 0, "details": {}, "errors": ["invalid health payload"]}

    details = _extract_details(data)
    components = data.get("components") if isinstance(data.get("components"), dict) else {}

    try:
        redis_result = check_redis()
        details["redis"] = redis_result
        components["redis"] = bool(redis_result.get("ok"))
    except Exception:
        logger.exception("auto_repair redis probe failed")

    try:
        gateway_result = check_gateway(base_url=base_url, timeout=5)
        details["gateway"] = gateway_result
        components["gateway"] = bool(gateway_result.get("ok"))
    except Exception:
        logger.exception("auto_repair gateway probe failed")

    if include_queue:
        try:
            queue_result = test_queue(wait_seconds=2.0)
            details["queue"] = queue_result
            components["queue"] = bool(queue_result.get("ok"))
        except Exception:
            logger.exception("auto_repair queue probe failed")

    data["details"] = details
    data["components"] = components

    score = int(data.get("score", 0) or 0)
    if components.get("redis") is False:
        score = min(score, 20)
    if components.get("gateway") is False:
        score = min(score, 50)
    if components.get("queue") is False:
        score = min(score, 65)
    data["score"] = score

    status = str(data.get("status") or "unknown")
    if components.get("redis") is False or components.get("gateway") is False:
        status = "critical"
    elif score < 85 and status == "healthy":
        status = "degraded"
    data["status"] = status
    return data


def analyze_health(health_data: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[DetectedIssue] = []
    details = _extract_details(health_data)

    redis_ok = _component_ok(health_data, details, "redis")
    if redis_ok is False:
        issues.append(
            DetectedIssue(
                code="redis_down",
                severity="critical",
                message="Redis unavailable",
                evidence={"redis": details.get("redis")},
            )
        )

    gateway_ok = _component_ok(health_data, details, "gateway")
    if gateway_ok is False:
        issues.append(
            DetectedIssue(
                code="gateway_down",
                severity="critical",
                message="Gateway unavailable",
                evidence={"gateway": details.get("gateway")},
            )
        )

    score = int(health_data.get("score", 0) or 0)
    if score < DEFAULT_MIN_SCORE:
        issues.append(
            DetectedIssue(
                code="low_score",
                severity="degraded",
                message=f"System score below threshold ({score} < {DEFAULT_MIN_SCORE})",
                evidence={"score": score},
            )
        )

    cache_data = details.get("cache") if isinstance(details.get("cache"), dict) else {}
    first_duration = _to_float((cache_data.get("first") or {}).get("duration_s"))
    second_duration = _to_float((cache_data.get("second") or {}).get("duration_s"))
    latency_ratio = _to_float(cache_data.get("latency_ratio"))

    if first_duration is not None and first_duration > 25.0:
        issues.append(
            DetectedIssue(
                code="llm_latency_high",
                severity="critical",
                message=f"LLM latency too high ({first_duration:.2f}s > 25s)",
                evidence={"first_duration_s": first_duration, "cache": cache_data},
            )
        )

    gain: float | None = None
    if latency_ratio is not None and latency_ratio > 0:
        gain = 1.0 / latency_ratio
    elif first_duration is not None and second_duration is not None and second_duration > 0:
        gain = first_duration / second_duration

    if gain is not None and gain < 5.0:
        issues.append(
            DetectedIssue(
                code="cache_inefficient",
                severity="warning",
                message=f"Cache gain too low (x{gain:.2f} < x5)",
                evidence={"gain": round(gain, 4), "cache": cache_data},
            )
        )

    queue_ok = _component_ok(health_data, details, "queue")
    if queue_ok is False:
        issues.append(
            DetectedIssue(
                code="queue_down",
                severity="critical",
                message="Queue worker not functional",
                evidence={"queue": details.get("queue")},
            )
        )

    for issue in issues:
        level = issue.severity.upper()
        logger.warning("[{}] {}", level, issue.message)

    return [i.to_dict() for i in issues]


def decide_action(issues: list[dict[str, Any]]) -> list[str]:
    severity_rank = {"critical": 0, "degraded": 1, "warning": 2}
    sorted_issues = sorted(issues, key=lambda x: severity_rank.get(str(x.get("severity", "warning")).lower(), 9))

    actions: list[str] = []
    seen: set[str] = set()
    for issue in sorted_issues:
        code = str(issue.get("code") or "")
        action = ISSUE_TO_ACTION.get(code)
        if not action or action in seen:
            continue
        actions.append(action)
        seen.add(action)

    return actions


def _run_shell(command: str, timeout_s: int) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        dt = round(time.perf_counter() - t0, 3)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "command": command,
            "duration_s": dt,
            "stdout": (proc.stdout or "").strip()[:2000],
            "stderr": (proc.stderr or "").strip()[:2000],
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": None,
            "command": command,
            "duration_s": round(time.perf_counter() - t0, 3),
            "stdout": "",
            "stderr": str(exc),
        }


def _execute_shell_action(action: str, timeout_s: int) -> dict[str, Any]:
    commands = ACTION_COMMANDS.get(action, [])
    attempts: list[dict[str, Any]] = []
    for command in commands:
        result = _run_shell(command=command, timeout_s=timeout_s)
        attempts.append(result)
        if result.get("ok"):
            return {
                "action": action,
                "ok": True,
                "status": "completed",
                "attempts": attempts,
            }
    return {
        "action": action,
        "ok": False,
        "status": "failed",
        "attempts": attempts,
    }


def _purge_cache_keys() -> dict[str, Any]:
    from core.redis.client import get_redis

    redis = get_redis()
    patterns = ["segyr:cache:*", "segyr:llm_cache:*"]
    deleted = 0
    errors: list[str] = []

    for pattern in patterns:
        try:
            keys = list(redis.scan_iter(match=pattern, count=200))
        except Exception as exc:
            errors.append(f"scan {pattern} failed: {exc}")
            continue

        if not keys:
            continue

        try:
            deleted += int(redis.delete(*keys))
        except Exception as exc:
            errors.append(f"delete {pattern} failed: {exc}")

    return {
        "ok": not errors,
        "deleted_keys": deleted,
        "errors": errors,
    }


def restart_redis(*, timeout_s: int = 20) -> dict[str, Any]:
    return _execute_shell_action("restart_redis", timeout_s=timeout_s)


def restart_gateway(*, timeout_s: int = 20) -> dict[str, Any]:
    return _execute_shell_action("restart_gateway", timeout_s=timeout_s)


def restart_queue_worker(*, timeout_s: int = 20) -> dict[str, Any]:
    return _execute_shell_action("restart_queue_worker", timeout_s=timeout_s)


def purge_cache() -> dict[str, Any]:
    result = _purge_cache_keys()
    result.update({"action": "purge_cache", "status": "completed" if result.get("ok") else "failed"})
    return result


def execute_action(
    action: str,
    *,
    dry_run: bool = False,
    safe_mode: bool = False,
    timeout_s: int = 20,
) -> dict[str, Any]:
    logger.warning("[ACTION] {} - {}", action, ACTION_LABELS.get(action, "custom action"))

    if safe_mode and action in DESTRUCTIVE_ACTIONS:
        return {
            "action": action,
            "ok": True,
            "status": "skipped_safe_mode",
            "attempts": [],
            "dry_run": dry_run,
            "safe_mode": safe_mode,
        }

    if dry_run:
        return {
            "action": action,
            "ok": True,
            "status": "dry_run",
            "attempts": [],
            "dry_run": True,
            "safe_mode": safe_mode,
        }

    if action == "restart_redis":
        return restart_redis(timeout_s=timeout_s)
    if action == "restart_gateway":
        return restart_gateway(timeout_s=timeout_s)
    if action == "restart_queue_worker":
        return restart_queue_worker(timeout_s=timeout_s)
    if action == "purge_cache":
        return purge_cache()

    return {
        "action": action,
        "ok": False,
        "status": "unknown_action",
        "attempts": [],
    }


def verify_fix(
    *,
    previous_health: dict[str, Any] | None = None,
    base_url: str = DEFAULT_BASE_URL,
    min_score: int = DEFAULT_MIN_SCORE,
    correlation_id: str | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    health = _collect_health_snapshot(
        base_url=base_url,
        include_queue=True,
        correlation_id=correlation_id,
        source=source,
    )
    issues = analyze_health(health)

    score_after = int(health.get("score", 0) or 0)
    score_before = int((previous_health or {}).get("score", 0) or 0)
    critical_issues = [i for i in issues if str(i.get("code")) in CRITICAL_ISSUES]

    fixed = (score_after >= int(min_score)) and not critical_issues
    logger.info(
        "[VERIFY] status={} score_before={} score_after={} fixed={}",
        health.get("status"),
        score_before,
        score_after,
        fixed,
    )

    return {
        "fixed": fixed,
        "score_before": score_before,
        "score_after": score_after,
        "issues": issues,
        "health": health,
    }


def _append_history(record: dict[str, Any], history_path: Path) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _safe_append_history(record: dict[str, Any], history_path: Path) -> None:
    try:
        _append_history(record, history_path)
    except Exception as exc:
        logger.warning("auto_repair history write failed: {}", exc)


def _read_recent_history(path: Path, limit: int = DEFAULT_POLICY_HISTORY_LIMIT) -> list[dict[str, Any]]:
    if limit <= 0 or not path.exists():
        return []

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        logger.warning("auto_repair history read failed path={} err={}", path, exc)
        return []

    items: list[dict[str, Any]] = []
    for raw in lines[-limit:]:
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                items.append(payload)
        except Exception:
            continue
    return items


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


def _expected_score_delta(policy_report: dict[str, Any], score_before: int, min_score: int) -> int:
    if not should_repair(policy_report):
        return 0
    target = max(int(min_score), int(score_before))
    return max(0, target - int(score_before))


def run_auto_repair_loop(
    *,
    health_data: dict[str, Any] | None = None,
    dry_run: bool = False,
    safe_mode: bool = False,
    max_attempts_per_action: int = MAX_ATTEMPTS_PER_ACTION,
    min_score: int = DEFAULT_MIN_SCORE,
    base_url: str = DEFAULT_BASE_URL,
    cooldown_seconds: float = 2.0,
    timeout_s: int = 20,
    history_path: str = str(DEFAULT_HISTORY_PATH),
    store_history: bool = True,
    planned_actions: list[str] | None = None,
    correlation_id: str | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    started_at = _now_iso()
    correlation_value = str(correlation_id or uuid.uuid4().hex)
    source_value = _normalize_source(source)
    attempts_cap = max(1, min(int(max_attempts_per_action), MAX_ATTEMPTS_PER_ACTION))
    repair_log: list[dict[str, Any]] = []
    attempt_counts: dict[str, int] = {}
    history_file = Path(history_path)
    policy_report: dict[str, Any] = {}
    score_before = 0
    expected_score_delta = 0

    logger.info(
        "auto_repair started correlation_id={} source={} dry_run={} safe_mode={}",
        correlation_value,
        source_value,
        dry_run,
        safe_mode,
    )

    try:
        initial_health = (
            health_data
            if isinstance(health_data, dict)
            else _collect_health_snapshot(
                base_url=base_url,
                correlation_id=correlation_value,
                source=source_value,
            )
        )
        current_health = initial_health
        initial_issues = analyze_health(initial_health)
        score_before = int(initial_health.get("score", 0) or 0)
        audit_history = _read_recent_history(history_file)
        policy_report = evaluate_policy(health_data=initial_health, audit_history=audit_history)
        policy_report["analyzed_issues"] = initial_issues
        policy_report["reason"] = str(policy_report.get("reason") or _policy_reason(policy_report))

        recommended_actions = decide_actions(policy_report)
        logger.info("[POLICY] recommended_actions={}", recommended_actions)

        decision = should_repair(policy_report)
        logger.info("[POLICY] decision={}", "execute" if decision else "skip")

        requested_actions = [
            str(action).strip()
            for action in (planned_actions or [])
            if str(action).strip()
        ]
        if requested_actions:
            requested_set = set(requested_actions)
            planned_actions_resolved = [action for action in recommended_actions if action in requested_set]
        else:
            planned_actions_resolved = list(recommended_actions)

        if not decision or not planned_actions_resolved:
            reason_value = str(policy_report.get("reason") or "policy_skip")
            result = {
                "started_at": started_at,
                "ended_at": _now_iso(),
                "status": "skipped",
                "reason": reason_value,
                "dry_run": dry_run,
                "safe_mode": safe_mode,
                "max_attempts_per_action": attempts_cap,
                "actions_planned": [],
                "actions_executed": [],
                "attempt_counts": {},
                "issues_before": initial_issues,
                "issues_after": initial_issues,
                "score_before": score_before,
                "score_after": int(current_health.get("score", 0) or 0),
                "score_delta_expected": 0,
                "score_delta_actual": 0,
                "status_before": initial_health.get("status"),
                "status_after": current_health.get("status"),
                "repaired": False,
                "health": current_health,
                "policy_report": policy_report,
                "policy": policy_report,
                "correlation_id": correlation_value,
                "source": source_value,
            }
            if store_history:
                _safe_append_history(result, history_file)
            return result

        expected_score_delta = _expected_score_delta(policy_report, score_before, min_score)

        for action in planned_actions_resolved:
            for attempt in range(1, attempts_cap + 1):
                attempt_counts[action] = attempt
                action_result = execute_action(
                    action,
                    dry_run=dry_run,
                    safe_mode=safe_mode,
                    timeout_s=timeout_s,
                )
                action_result["attempt"] = attempt
                repair_log.append(action_result)
                logger.info("[RESULT] action={} ok={} status={}", action, action_result.get("ok"), action_result.get("status"))

                verify_result = verify_fix(
                    previous_health=current_health,
                    base_url=base_url,
                    min_score=min_score,
                    correlation_id=correlation_value,
                    source=source_value,
                )
                current_health = verify_result["health"]

                unresolved = [i for i in verify_result["issues"] if str(i.get("code")) in CRITICAL_ISSUES]
                if verify_result.get("fixed") and not unresolved:
                    break

                if attempt < attempts_cap:
                    time.sleep(max(0.0, cooldown_seconds))

            post_issues = analyze_health(current_health)
            post_critical = [i for i in post_issues if str(i.get("code")) in CRITICAL_ISSUES]
            if not post_critical and int(current_health.get("score", 0) or 0) >= int(min_score):
                break

        final_issues = analyze_health(current_health)
        final_critical = [i for i in final_issues if str(i.get("code")) in CRITICAL_ISSUES]
        score_after = int(current_health.get("score", 0) or 0)

        result = {
            "started_at": started_at,
            "ended_at": _now_iso(),
            "status": "completed",
            "dry_run": dry_run,
            "safe_mode": safe_mode,
            "max_attempts_per_action": attempts_cap,
            "actions_planned": planned_actions_resolved,
            "actions_executed": repair_log,
            "attempt_counts": attempt_counts,
            "issues_before": initial_issues,
            "issues_after": final_issues,
            "score_before": score_before,
            "score_after": score_after,
            "score_delta_expected": expected_score_delta,
            "score_delta_actual": score_after - score_before,
            "status_before": initial_health.get("status"),
            "status_after": current_health.get("status"),
            "repaired": (not final_critical) and int(current_health.get("score", 0) or 0) >= int(min_score),
            "health": current_health,
            "policy_report": policy_report,
            "policy": policy_report,
            "correlation_id": correlation_value,
            "source": source_value,
        }

        if store_history:
            _safe_append_history(result, history_file)

        return result
    except Exception as exc:
        logger.exception("auto_repair loop failed")
        result = {
            "started_at": started_at,
            "ended_at": _now_iso(),
            "status": "failed",
            "reason": "auto_repair_exception",
            "dry_run": dry_run,
            "safe_mode": safe_mode,
            "max_attempts_per_action": attempts_cap,
            "actions_planned": [],
            "actions_executed": repair_log,
            "attempt_counts": attempt_counts,
            "issues_before": [],
            "issues_after": [{"code": "auto_repair_exception", "severity": "critical", "message": str(exc), "evidence": {}}],
            "score_before": score_before,
            "score_after": 0,
            "score_delta_expected": 0,
            "score_delta_actual": -int(score_before),
            "status_before": "unknown",
            "status_after": "critical",
            "repaired": False,
            "error": str(exc),
            "health": {},
            "policy_report": policy_report,
            "policy": policy_report,
            "correlation_id": correlation_value,
            "source": source_value,
        }
        if store_history:
            _safe_append_history(result, history_file)
        return result


async def run_auto_repair_loop_async(**kwargs: Any) -> dict[str, Any]:
    return await asyncio.to_thread(run_auto_repair_loop, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description="SEGYR auto-repair loop")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--max-attempts-per-action", type=int, default=MAX_ATTEMPTS_PER_ACTION)
    parser.add_argument("--cooldown-seconds", type=float, default=2.0)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--history-path", default=str(DEFAULT_HISTORY_PATH))
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--safe-mode", action="store_true")
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument("--source", default="manual", choices=sorted(VALID_CORRELATION_SOURCES))
    parser.add_argument("--json", action="store_true", help="print compact JSON")
    args = parser.parse_args()

    result = run_auto_repair_loop(
        dry_run=bool(args.dry_run),
        safe_mode=bool(args.safe_mode),
        max_attempts_per_action=int(args.max_attempts_per_action),
        min_score=int(args.min_score),
        base_url=str(args.base_url),
        cooldown_seconds=float(args.cooldown_seconds),
        timeout_s=int(args.timeout),
        history_path=str(args.history_path),
        store_history=not bool(args.no_history),
        correlation_id=(str(args.correlation_id) if args.correlation_id else None),
        source=str(args.source),
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if bool(result.get("repaired")) else 1


if __name__ == "__main__":
    os.environ.setdefault("SEGYR_JWT_SECRET", "dev-secret")
    os.environ.setdefault("SEGYR_DB_PASSWORD", "dev-db")
    raise SystemExit(main())
