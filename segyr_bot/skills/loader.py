from __future__ import annotations

import importlib
import inspect
import pkgutil

from segyr_bot.channels.logging import logger
from segyr_bot.skills.base import BaseSkill
from segyr_bot.skills.registry import SkillsRegistry


class SkillsLoader:
    """Chargeur automatique des skills builtin."""

    def __init__(self, registry: SkillsRegistry | None = None) -> None:
        self.registry = registry or SkillsRegistry()

    def load_builtin(self) -> SkillsRegistry:
        import segyr_bot.skills.builtin as builtin_pkg

        for _, module_name, ispkg in pkgutil.iter_modules(builtin_pkg.__path__):
            if ispkg:
                continue
            full_module = f"segyr_bot.skills.builtin.{module_name}"
            try:
                module = importlib.import_module(full_module)
            except Exception as exc:
                logger.warning("Skill module ignore {}: {}", full_module, exc)
                continue

            loaded = 0
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if not issubclass(cls, BaseSkill) or cls is BaseSkill:
                    continue
                try:
                    instance = cls()
                    self.registry.register(instance)
                    loaded += 1
                    logger.info("Skill chargée: {} ({})", instance.name, cls.__name__)
                except Exception as exc:
                    logger.warning("Skill class ignore {}.{}: {}", full_module, cls.__name__, exc)

            if loaded == 0:
                logger.debug("Aucune skill detectee dans {}", full_module)

        return self.registry
