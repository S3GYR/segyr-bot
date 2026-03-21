from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict


class BaseTool(ABC):
    """Interface minimale des tools SEGYR-BOT."""

    name: str
    description: str = ""

    @abstractmethod
    async def run(self, **kwargs: Any) -> Any:  # pragma: no cover - interface
        raise NotImplementedError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    async def execute(self, name: str, **kwargs: Any) -> Any:
        tool = self.get(name)
        if not tool:
            raise ValueError(f"Tool '{name}' non trouvé")
        return await tool.run(**kwargs)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())
