"""Filesystem tools: read, write, edit, list."""

from pathlib import Path
from typing import Any

from core.agent.tools.base import Tool


def _safe_path(path_str: str, workspace: Path, allowed_dir: Path | None) -> Path | None:
    """Resolve path, ensure it's within allowed directory."""
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = workspace / p
    p = p.resolve()
    if allowed_dir:
        try:
            p.relative_to(allowed_dir.resolve())
        except ValueError:
            return None
    return p


class ReadFileTool(Tool):
    def __init__(self, workspace: Path, allowed_dir: Path | None = None):
        self.workspace = workspace
        self.allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file. Returns the file content as text."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read"},
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        p = _safe_path(path, self.workspace, self.allowed_dir)
        if p is None:
            return f"Error: Path '{path}' is outside the allowed directory."
        if not p.exists():
            return f"Error: File not found: {path}"
        if not p.is_file():
            return f"Error: Path is not a file: {path}"
        try:
            return p.read_text(encoding="utf-8")
        except Exception as e:
            return f"Error reading file: {e}"


class WriteFileTool(Tool):
    def __init__(self, workspace: Path, allowed_dir: Path | None = None):
        self.workspace = workspace
        self.allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file, creating it if it doesn't exist."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        p = _safe_path(path, self.workspace, self.allowed_dir)
        if p is None:
            return f"Error: Path '{path}' is outside the allowed directory."
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"File written successfully: {p}"
        except Exception as e:
            return f"Error writing file: {e}"


class EditFileTool(Tool):
    def __init__(self, workspace: Path, allowed_dir: Path | None = None):
        self.workspace = workspace
        self.allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Edit a file by replacing exact text. Old string must exist exactly once."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to edit"},
                "old_str": {"type": "string", "description": "Exact text to replace"},
                "new_str": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_str", "new_str"],
        }

    async def execute(self, path: str, old_str: str, new_str: str, **kwargs: Any) -> str:
        p = _safe_path(path, self.workspace, self.allowed_dir)
        if p is None:
            return f"Error: Path '{path}' is outside the allowed directory."
        if not p.exists():
            return f"Error: File not found: {path}"
        try:
            content = p.read_text(encoding="utf-8")
            count = content.count(old_str)
            if count == 0:
                return f"Error: Text not found in file: {old_str[:80]!r}"
            if count > 1:
                return f"Error: Text found {count} times (must be unique): {old_str[:80]!r}"
            p.write_text(content.replace(old_str, new_str, 1), encoding="utf-8")
            return f"File edited successfully: {p}"
        except Exception as e:
            return f"Error editing file: {e}"


class ListDirTool(Tool):
    def __init__(self, workspace: Path, allowed_dir: Path | None = None):
        self.workspace = workspace
        self.allowed_dir = allowed_dir

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List the contents of a directory."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the directory (default: workspace)"},
            },
            "required": [],
        }

    async def execute(self, path: str = ".", **kwargs: Any) -> str:
        p = _safe_path(path, self.workspace, self.allowed_dir)
        if p is None:
            return f"Error: Path '{path}' is outside the allowed directory."
        if not p.exists():
            return f"Error: Directory not found: {path}"
        if not p.is_dir():
            return f"Error: Not a directory: {path}"
        try:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            lines = []
            for entry in entries:
                prefix = "📄" if entry.is_file() else "📁"
                size = f" ({entry.stat().st_size} bytes)" if entry.is_file() else "/"
                lines.append(f"{prefix} {entry.name}{size}")
            return "\n".join(lines) if lines else "(empty directory)"
        except Exception as e:
            return f"Error listing directory: {e}"
