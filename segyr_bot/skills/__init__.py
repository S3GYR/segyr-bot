"""Système de skills SEGYR-BOT."""

from segyr_bot.skills.base import BaseSkill
from segyr_bot.skills.loader import SkillsLoader
from segyr_bot.skills.registry import SkillsRegistry
from segyr_bot.skills.router import SkillsRouter

__all__ = ["BaseSkill", "SkillsLoader", "SkillsRegistry", "SkillsRouter"]
