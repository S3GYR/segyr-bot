from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

SEVERITY_ORDER = {"critical": 0, "degraded": 1, "warning": 2, "info": 3}

DEFAULT_POLICY_RULES: dict[str, Any] = {
    "min_score": 70,
    "redis_error_threshold": 3,
    "redis_error_window_seconds": 5 * 60,
    "cache_gain_min": 5.0,
    "cache_inefficient_recurrent_threshold": 3,
    "cache_inefficient_window_seconds": 30 * 60,
    "repair_cooldown_seconds": 2 * 60,
    "max_repairs_in_window": 4,
    "max_repairs_window_seconds": 15 * 60,
    "allow_purge_cache": True,
    "allowed_actions": [
        "restart_redis",
        "restart_gateway",
        "restart_queue_worker",
        "purge_cache",
    ],
    "issue_action_map": {
        "redis_down": "restart_redis",
        "redis_error_spike": "restart_redis",
        "gateway_down": "restart_gateway",
        "queue_down": "restart_queue_worker",
        "low_score": "restart_gateway",
        "cache_inefficient_recurrent": "purge_cache",
    },
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(current, value)
        else:
            merged[key] = value
    return merged


def _resolve_rules(rules: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(rules, dict):
        return deepcopy(DEFAULT_POLICY_RULES)
    return _deep_merge_dict(DEFAULT_POLICY_RULES, rules)


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

    part = details.get(name)
    if isinstance(part, dict) and "ok" in part:
        return bool(part.get("ok"))

    return None


def _cache_gain(details: dict[str, Any]) -> float | None:
    cache_data = details.get("cache") if isinstance(details.get("cache"), dict) else {}

    latency_ratio = _to_float(cache_data.get("latency_ratio"))
    if latency_ratio is not None and latency_ratio > 0:
        return 1.0 / latency_ratio

    first_duration = _to_float((cache_data.get("first") or {}).get("duration_s"))
    second_duration = _to_float((cache_data.get("second") or {}).get("duration_s"))
    if first_duration is not None and second_duration is not None and second_duration > 0:
        return first_duration / second_duration

    return None


def _parse_entry_ts(entry: dict[str, Any]) -> float | None:
    for key in ("timestamp", "ts", "ended_at", "started_at"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            if isinstance(raw, (int, float)):
                return float(raw)
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts.timestamp()
        except Exception:
            continue
    return None


def _iter_action_names(entry: dict[str, Any]) -> list[str]:
    actions = entry.get("actions")
    if not isinstance(actions, list):
        return []

    names: list[str] = []
    for item in actions:
        if isinstance(item, dict):
            name = str(item.get("action") or "").strip()
        else:
            name = str(item).strip()
        if name:
            names.append(name)
    return names


def _count_action_in_window(audit_history: list[dict[str, Any]], action_name: str, now_ts: float, window_s: int) -> int:
    if window_s <= 0:
        return 0

    floor_ts = now_ts - float(window_s)
    count = 0
    for entry in audit_history:
        ts = _parse_entry_ts(entry)
        if ts is None or ts < floor_ts:
            continue
        if action_name in _iter_action_names(entry):
            count += 1
    return count


def _count_repairs_in_window(audit_history: list[dict[str, Any]], now_ts: float, window_s: int) -> int:
    if window_s <= 0:
        return 0

    floor_ts = now_ts - float(window_s)
    count = 0
    for entry in audit_history:
        ts = _parse_entry_ts(entry)
        if ts is None or ts < floor_ts:
            continue
        endpoint = str(entry.get("endpoint") or "")
        if endpoint.startswith("/repair/"):
            count += 1
            continue
        if "status_final" in entry:
            count += 1
    return count


def _last_repair_ts(audit_history: list[dict[str, Any]]) -> float | None:
    latest: float | None = None
    for entry in audit_history:
        endpoint = str(entry.get("endpoint") or "")
        if endpoint and not endpoint.startswith("/repair/"):
            continue
        if "status_final" not in entry and not endpoint:
            continue
        ts = _parse_entry_ts(entry)
        if ts is None:
            continue
        if latest is None or ts > latest:
            latest = ts
    return latest


def _resolve_redis_error_frequency(
    error_frequency: dict[str, Any],
    audit_history: list[dict[str, Any]],
    now_ts: float,
    ruleset: dict[str, Any],
) -> int:
    for key in ("redis_errors_5m", "redis_errors", "redis_error_count", "redis"):
        if key in error_frequency:
            return max(0, _to_int(error_frequency.get(key), default=0))

    return _count_action_in_window(
        audit_history,
        action_name="restart_redis",
        now_ts=now_ts,
        window_s=_to_int(ruleset.get("redis_error_window_seconds"), default=300),
    )


def _resolve_cache_ineff_frequency(
    error_frequency: dict[str, Any],
    audit_history: list[dict[str, Any]],
    now_ts: float,
    ruleset: dict[str, Any],
) -> int:
    for key in ("cache_inefficient_count", "cache_inefficient", "cache_errors"):
        if key in error_frequency:
            return max(0, _to_int(error_frequency.get(key), default=0))

    return _count_action_in_window(
        audit_history,
        action_name="purge_cache",
        now_ts=now_ts,
        window_s=_to_int(ruleset.get("cache_inefficient_window_seconds"), default=1800),
    )


def _compute_learning_stats(audit_history: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(audit_history)
    if total == 0:
        return {
            "total_runs": 0,
            "success_rate": 0.0,
            "failure_rate": 0.0,
            "avg_score_delta": 0.0,
            "action_counts": {},
        }

    success = 0
    failures = 0
    score_deltas: list[float] = []
    action_counts: dict[str, int] = {}

    for entry in audit_history:
        status_final = str(entry.get("status_final") or "").strip().lower()
        if status_final == "success":
            success += 1
        elif status_final == "failed":
            failures += 1

        sb = _to_float(entry.get("score_before"))
        sa = _to_float(entry.get("score_after"))
        if sb is not None and sa is not None:
            score_deltas.append(sa - sb)

        for action in _iter_action_names(entry):
            action_counts[action] = action_counts.get(action, 0) + 1

    avg_delta = (sum(score_deltas) / len(score_deltas)) if score_deltas else 0.0
    return {
        "total_runs": total,
        "success_rate": round(success / total, 4),
        "failure_rate": round(failures / total, 4),
        "avg_score_delta": round(avg_delta, 4),
        "action_counts": action_counts,
    }


def decide_actions(
    issues_or_report: list[dict[str, Any]] | dict[str, Any],
    *,
    rules: dict[str, Any] | None = None,
    audit_history: list[dict[str, Any]] | None = None,
) -> list[str]:
    del audit_history  # reserved for future weighting heuristics

    ruleset = _resolve_rules(rules)
    if isinstance(issues_or_report, dict):
        existing_actions = issues_or_report.get("recommended_actions")
        if isinstance(existing_actions, list):
            return [str(action).strip() for action in existing_actions if str(action).strip()]
        issues = issues_or_report.get("issues") if isinstance(issues_or_report.get("issues"), list) else []
    else:
        issues = issues_or_report

    issue_action_map = ruleset.get("issue_action_map") if isinstance(ruleset.get("issue_action_map"), dict) else {}
    allowed_actions = set(str(a) for a in (ruleset.get("allowed_actions") or []) if str(a).strip())
    allow_purge_cache = bool(ruleset.get("allow_purge_cache", True))

    sorted_issues = sorted(
        issues,
        key=lambda item: SEVERITY_ORDER.get(str(item.get("severity") or "warning").lower(), 99),
    )

    actions: list[str] = []
    seen: set[str] = set()
    for issue in sorted_issues:
        code = str(issue.get("code") or "").strip()
        if not code:
            continue

        action = str(issue_action_map.get(code) or "").strip()
        if not action or action in seen:
            continue
        if allowed_actions and action not in allowed_actions:
            continue
        if action == "purge_cache" and not allow_purge_cache:
            continue

        actions.append(action)
        seen.add(action)

    return actions


def evaluate_policy(
    *,
    health_data: dict[str, Any],
    audit_history: list[dict[str, Any]] | None = None,
    error_frequency: dict[str, Any] | None = None,
    rules: dict[str, Any] | None = None,
    learning_mode: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    ruleset = _resolve_rules(rules)
    history = [h for h in (audit_history or []) if isinstance(h, dict)]
    freq = dict(error_frequency or {})

    now_dt = now or _now_utc()
    now_ts = now_dt.timestamp()

    details = _extract_details(health_data or {})
    status = str((health_data or {}).get("status") or "critical").strip().lower()
    score = _to_int((health_data or {}).get("score"), default=0)

    issues: list[dict[str, Any]] = []

    min_score = _to_int(ruleset.get("min_score"), default=70)
    if score < min_score:
        issues.append(
            {
                "code": "low_score",
                "severity": "degraded",
                "message": f"Score below threshold ({score} < {min_score})",
                "evidence": {"score": score, "min_score": min_score},
            }
        )

    redis_ok = _component_ok(health_data, details, "redis")
    if redis_ok is False:
        issues.append(
            {
                "code": "redis_down",
                "severity": "critical",
                "message": "Redis unavailable",
                "evidence": {"redis": details.get("redis")},
            }
        )

    gateway_ok = _component_ok(health_data, details, "gateway")
    if gateway_ok is False:
        issues.append(
            {
                "code": "gateway_down",
                "severity": "critical",
                "message": "Gateway unavailable",
                "evidence": {"gateway": details.get("gateway")},
            }
        )

    queue_ok = _component_ok(health_data, details, "queue")
    if queue_ok is False:
        issues.append(
            {
                "code": "queue_down",
                "severity": "critical",
                "message": "Queue worker unavailable",
                "evidence": {"queue": details.get("queue")},
            }
        )

    redis_errors = _resolve_redis_error_frequency(freq, history, now_ts, ruleset)
    redis_threshold = _to_int(ruleset.get("redis_error_threshold"), default=3)
    redis_window_s = _to_int(ruleset.get("redis_error_window_seconds"), default=300)
    if redis_errors >= redis_threshold:
        issues.append(
            {
                "code": "redis_error_spike",
                "severity": "critical",
                "message": f"Redis errors spike ({redis_errors} in {redis_window_s}s)",
                "evidence": {
                    "count": redis_errors,
                    "threshold": redis_threshold,
                    "window_seconds": redis_window_s,
                },
            }
        )

    gain = _cache_gain(details)
    gain_threshold = _to_float(ruleset.get("cache_gain_min"), default=5.0) or 5.0
    if gain is not None and gain < gain_threshold:
        issues.append(
            {
                "code": "cache_inefficient",
                "severity": "warning",
                "message": f"Cache gain too low (x{gain:.2f} < x{gain_threshold:.2f})",
                "evidence": {"gain": round(gain, 4), "threshold": gain_threshold},
            }
        )

        cache_count = _resolve_cache_ineff_frequency(freq, history, now_ts, ruleset)
        cache_threshold = _to_int(ruleset.get("cache_inefficient_recurrent_threshold"), default=3)
        cache_window_s = _to_int(ruleset.get("cache_inefficient_window_seconds"), default=1800)
        if cache_count >= cache_threshold:
            issues.append(
                {
                    "code": "cache_inefficient_recurrent",
                    "severity": "degraded",
                    "message": (
                        f"Cache inefficiency recurrent ({cache_count} signals in {cache_window_s}s)"
                    ),
                    "evidence": {
                        "count": cache_count,
                        "threshold": cache_threshold,
                        "window_seconds": cache_window_s,
                    },
                }
            )

    if status == "critical" and not any(i.get("code") in {"redis_down", "gateway_down", "queue_down"} for i in issues):
        issues.append(
            {
                "code": "system_critical",
                "severity": "critical",
                "message": "System status is critical",
                "evidence": {"status": status, "score": score},
            }
        )

    actions = decide_actions(issues, rules=ruleset, audit_history=history)

    suppressions: list[dict[str, Any]] = []
    cooldown_s = _to_int(ruleset.get("repair_cooldown_seconds"), default=120)
    last_repair_ts = _last_repair_ts(history)
    if cooldown_s > 0 and last_repair_ts is not None:
        elapsed = now_ts - last_repair_ts
        if elapsed < cooldown_s:
            suppressions.append(
                {
                    "code": "repair_cooldown_active",
                    "message": f"Cooldown active ({round(cooldown_s - elapsed, 2)}s remaining)",
                    "evidence": {
                        "cooldown_seconds": cooldown_s,
                        "elapsed_seconds": round(elapsed, 2),
                    },
                }
            )

    max_repairs = _to_int(ruleset.get("max_repairs_in_window"), default=4)
    repair_window_s = _to_int(ruleset.get("max_repairs_window_seconds"), default=900)
    repairs_in_window = _count_repairs_in_window(history, now_ts, repair_window_s)
    if max_repairs > 0 and repairs_in_window >= max_repairs:
        suppressions.append(
            {
                "code": "repair_rate_limited",
                "message": f"Too many repairs ({repairs_in_window} in {repair_window_s}s)",
                "evidence": {
                    "count": repairs_in_window,
                    "threshold": max_repairs,
                    "window_seconds": repair_window_s,
                },
            }
        )

    if issues and not actions:
        suppressions.append(
            {
                "code": "no_permitted_action",
                "message": "Issues detected but no action allowed by current rules",
                "evidence": {},
            }
        )

    relevant_issues = [
        i
        for i in issues
        if str(i.get("severity") or "warning").lower() in {"critical", "degraded"}
    ]
    should_repair_now = bool(relevant_issues and actions and not suppressions)

    report: dict[str, Any] = {
        "timestamp": now_dt.isoformat(),
        "status": status,
        "score": score,
        "issues": issues,
        "recommended_actions": actions,
        "suppressions": suppressions,
        "should_repair": should_repair_now,
        "signals": {
            "redis_errors": redis_errors,
            "cache_gain": round(gain, 4) if gain is not None else None,
            "repairs_in_window": repairs_in_window,
        },
        "rules": ruleset,
    }

    if learning_mode:
        report["learning"] = _compute_learning_stats(history)

    return report


def should_repair(
    policy_report: dict[str, Any] | None = None,
    *,
    health_data: dict[str, Any] | None = None,
    audit_history: list[dict[str, Any]] | None = None,
    error_frequency: dict[str, Any] | None = None,
    rules: dict[str, Any] | None = None,
    learning_mode: bool = False,
) -> bool:
    if isinstance(policy_report, dict):
        return bool(policy_report.get("should_repair"))

    if not isinstance(health_data, dict):
        return False

    report = evaluate_policy(
        health_data=health_data,
        audit_history=audit_history,
        error_frequency=error_frequency,
        rules=rules,
        learning_mode=learning_mode,
    )
    return bool(report.get("should_repair"))
