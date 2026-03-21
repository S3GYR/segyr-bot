from __future__ import annotations

import importlib
import pkgutil
from importlib.metadata import entry_points

from segyr_bot.channels.logging import logger

from segyr_bot.channels.base import BaseChannel

_INTERNAL_MODULES = frozenset({"base", "manager", "registry"})
_PLUGIN_GROUPS = ("segyr_bot.channels", "nanobot.channels")


def _iter_builtin_modules() -> list[str]:
    import segyr_bot.channels as pkg

    modules: list[str] = []
    for _, name, ispkg in pkgutil.walk_packages(pkg.__path__, prefix="segyr_bot.channels."):
        if not ispkg and name.rsplit(".", 1)[-1] == "channel":
            modules.append(name)
    return modules


def _load_channel_class(module_name: str) -> type[BaseChannel]:
    mod = importlib.import_module(module_name)
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, BaseChannel) and obj is not BaseChannel:
            return obj
    raise ImportError(f"No BaseChannel subclass in {module_name}")


def discover_builtin() -> dict[str, type[BaseChannel]]:
    channels: dict[str, type[BaseChannel]] = {}
    for module_name in _iter_builtin_modules():
        short = module_name.rsplit(".", 2)[-2]
        if short in _INTERNAL_MODULES:
            continue
        try:
            cls = _load_channel_class(module_name)
            channels[cls.name or short] = cls
        except Exception as exc:
            logger.warning("Channel builtin ignore {}: {}", module_name, exc)
    return channels


def discover_plugins() -> dict[str, type[BaseChannel]]:
    plugins: dict[str, type[BaseChannel]] = {}
    for group in _PLUGIN_GROUPS:
        for ep in entry_points(group=group):
            try:
                cls = ep.load()
                if not isinstance(cls, type) or not issubclass(cls, BaseChannel):
                    logger.warning("Plugin {} ({}) ignore: BaseChannel attendu", ep.name, group)
                    continue
                plugins[ep.name] = cls
            except Exception as exc:
                logger.warning("Plugin channel load failed {} ({}): {}", ep.name, group, exc)
    return plugins


def discover_all() -> dict[str, type[BaseChannel]]:
    builtin = discover_builtin()
    external = discover_plugins()

    shadowed = set(external).intersection(builtin)
    if shadowed:
        logger.warning("Plugins ignores (shadowes par builtin): {}", sorted(shadowed))

    return {**external, **builtin}
