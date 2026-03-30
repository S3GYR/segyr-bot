from __future__ import annotations

from core.monitoring import auto_repair
from core.monitoring.action_executor import DEFAULT_ACTION_COMMANDS


def test_restart_gateway_targets_gateway_service() -> None:
    commands = DEFAULT_ACTION_COMMANDS["restart_gateway"]
    rendered = [" ".join(cmd) for cmd in commands]
    assert any("segyr-gateway" in cmd for cmd in rendered)
    assert all("segyr-api" not in cmd for cmd in rendered)


def test_execute_action_skipped_when_kill_switch_disabled() -> None:
    result = auto_repair.execute_action(
        "restart_gateway",
        auto_repair_enabled=False,
        execution_mode="run",
    )
    assert result["status"] == "skipped_disabled"
    assert result["ok"] is True


def test_execute_action_requires_approval_mode() -> None:
    result = auto_repair.execute_action(
        "restart_gateway",
        auto_repair_enabled=True,
        execution_mode="approval_required",
    )
    assert result["status"] == "approval_required"
    assert result["ok"] is True


def test_run_auto_repair_loop_returns_skipped_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(auto_repair, "analyze_health", lambda _health: [{"code": "gateway_down", "severity": "critical"}])
    monkeypatch.setattr(
        auto_repair,
        "evaluate_policy",
        lambda **_kwargs: {
            "should_repair": True,
            "reason": "gateway_down",
            "recommended_actions": ["restart_gateway"],
            "issues": [{"code": "gateway_down", "severity": "critical"}],
            "suppressions": [],
        },
    )
    monkeypatch.setattr(auto_repair, "decide_actions", lambda _report: ["restart_gateway"])
    monkeypatch.setattr(auto_repair, "should_repair", lambda _report: True)

    result = auto_repair.run_auto_repair_loop(
        health_data={"status": "critical", "score": 10, "details": {}},
        store_history=False,
        auto_repair_enabled=False,
        execution_mode="run",
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "auto_repair_disabled"
    assert result["actions_executed"] == []


def test_run_auto_repair_loop_returns_approval_required(monkeypatch) -> None:
    monkeypatch.setattr(auto_repair, "analyze_health", lambda _health: [{"code": "gateway_down", "severity": "critical"}])
    monkeypatch.setattr(
        auto_repair,
        "evaluate_policy",
        lambda **_kwargs: {
            "should_repair": True,
            "reason": "gateway_down",
            "recommended_actions": ["restart_gateway"],
            "issues": [{"code": "gateway_down", "severity": "critical"}],
            "suppressions": [],
        },
    )
    monkeypatch.setattr(auto_repair, "decide_actions", lambda _report: ["restart_gateway"])
    monkeypatch.setattr(auto_repair, "should_repair", lambda _report: True)

    result = auto_repair.run_auto_repair_loop(
        health_data={"status": "critical", "score": 10, "details": {}},
        store_history=False,
        auto_repair_enabled=True,
        execution_mode="approval_required",
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "approval_required"
    assert result["actions_pending"] == ["restart_gateway"]
