from __future__ import annotations

import shlex
import subprocess
import time
from typing import Iterable

from core.logging import logger

DEFAULT_ACTION_COMMANDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "restart_redis": (
        ("docker", "restart", "redis"),
        ("docker", "compose", "restart", "redis"),
        ("systemctl", "restart", "redis"),
    ),
    "restart_gateway": (
        ("docker", "restart", "segyr-gateway"),
        ("docker", "compose", "restart", "segyr-gateway"),
        ("systemctl", "restart", "segyr-gateway"),
        ("systemctl", "restart", "segyr-gateway.service"),
    ),
    "restart_queue_worker": (
        ("docker", "restart", "worker"),
        ("docker", "compose", "restart", "worker"),
        ("systemctl", "restart", "segyr-worker"),
        ("systemctl", "restart", "segyr-worker.service"),
    ),
}


class ActionExecutor:
    """Controlled executor for operational actions (no shell interpolation)."""

    def __init__(self, command_map: dict[str, tuple[tuple[str, ...], ...]] | None = None) -> None:
        self._command_map = command_map or DEFAULT_ACTION_COMMANDS

    def execute(self, action: str, *, timeout_s: int) -> dict[str, object]:
        commands = self._command_map.get(action)
        if not commands:
            return {
                "action": action,
                "ok": False,
                "status": "unknown_action",
                "attempts": [],
            }

        attempts: list[dict[str, object]] = []
        for command in commands:
            result = self._run(action=action, command=command, timeout_s=timeout_s)
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

    def _run(self, *, action: str, command: Iterable[str], timeout_s: int) -> dict[str, object]:
        argv = tuple(str(part).strip() for part in command if str(part).strip())
        rendered = " ".join(shlex.quote(part) for part in argv)
        t0 = time.perf_counter()

        if not argv:
            return {
                "action": action,
                "ok": False,
                "returncode": None,
                "command": rendered,
                "duration_s": 0.0,
                "stdout": "",
                "stderr": "empty command",
            }

        try:
            proc = subprocess.run(
                list(argv),
                capture_output=True,
                text=True,
                timeout=max(1, int(timeout_s)),
                check=False,
            )
            duration_s = round(time.perf_counter() - t0, 3)
            payload = {
                "action": action,
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "command": rendered,
                "duration_s": duration_s,
                "stdout": (proc.stdout or "").strip()[:2000],
                "stderr": (proc.stderr or "").strip()[:2000],
            }
            if not payload["ok"]:
                logger.warning("auto_repair command failed action={} command={} rc={}", action, rendered, proc.returncode)
            return payload
        except Exception as exc:
            duration_s = round(time.perf_counter() - t0, 3)
            logger.warning("auto_repair command exception action={} command={} err={}", action, rendered, exc)
            return {
                "action": action,
                "ok": False,
                "returncode": None,
                "command": rendered,
                "duration_s": duration_s,
                "stdout": "",
                "stderr": str(exc),
            }
