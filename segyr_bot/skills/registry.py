from __future__ import annotations

from segyr_bot.skills.base import BaseSkill


class SkillsRegistry:
    """Registre des skills disponibles."""

    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        self._skills[skill.name.lower()] = skill

    def get(self, name: str) -> BaseSkill | None:
        return self._skills.get(name.lower())

    def list(self) -> list[str]:
        return sorted(self._skills.keys())
