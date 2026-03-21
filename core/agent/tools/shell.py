"""Shell execution tool with safety guards."""

import asyncio
import re
from pathlib import Path
from typing import Any

from loguru import logger

from core.agent.tools.base import Tool

_DENY_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bformat\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{.*\}",  # fork bomb
    r"\bdel\s+/[sq]",
    r"\brd\s+/[sq]",
    r"\bregdel\b",
    r"\bshutdown\b",
    r"\breboot\b",
]
_DENY_RE = re.compile("|".join(_DENY_PATTERNS), re.IGNORECASE)


class ExecTool(Tool):
    def __init__(
        self,
        working_dir: str | None = None,
        timeout: int = 60,
        restrict_to_workspace: bool = False,
        path_append: str = "",
    ):
        self.working_dir = working_dir
        self.timeout = min(timeout, 600)
        self.restrict_to_workspace = restrict_to_workspace
        self.path_append = path_append

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Use for file operations, git, pip, etc."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout": {
                    "type": "integer",
                    "description": f"Timeout in seconds (max {self.timeout})",
                    "default": 30,
                },
            },
            "required": ["command"],
        }

    async def execute(self, command: str, timeout: int = 30, **kwargs: Any) -> str:
        if _DENY_RE.search(command):
            return "Error: Command blocked by safety policy."

        timeout = min(timeout, self.timeout)
        logger.debug("Exec: {}", command[:200])

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.working_dir,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return f"Error: Command timed out after {timeout}s"

            out = stdout.decode("utf-8", errors="replace")
            err = stderr.decode("utf-8", errors="replace")
            parts = []
            if out:
                parts.append(out)
            if err:
                parts.append(f"[stderr]\n{err}")
            if proc.returncode != 0 and not out and not err:
                parts.append(f"[exit code: {proc.returncode}]")
            return "\n".join(parts) or f"[exit code: {proc.returncode}]"

        except Exception as e:
            return f"Error executing command: {e}"
