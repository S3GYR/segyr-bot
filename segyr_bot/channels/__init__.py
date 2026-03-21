"""Channels SEGYR-BOT (base, manager, registry et implementations)."""

from segyr_bot.channels.base import BaseChannel, ChannelConfigBase
from segyr_bot.channels.manager import ChannelManager
from segyr_bot.channels.registry import discover_all, discover_builtin, discover_plugins

__all__ = [
    "BaseChannel",
    "ChannelConfigBase",
    "ChannelManager",
    "discover_all",
    "discover_builtin",
    "discover_plugins",
]
