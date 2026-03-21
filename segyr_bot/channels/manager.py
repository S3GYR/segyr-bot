from __future__ import annotations

import asyncio
from typing import Any

from core.bus.events import OutboundMessage
from core.bus.queue import MessageBus
from segyr_bot.channels.logging import logger

from segyr_bot.channels.base import BaseChannel
from segyr_bot.channels.registry import discover_all


class ChannelManager:
    """Gestionnaire de channels SEGYR (builtin + plugins)."""

    def __init__(self, channels_config: dict[str, Any], bus: MessageBus):
        self.channels_config = channels_config
        self.bus = bus
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._start_tasks: list[asyncio.Task] = []
        self._init_channels()

    def _init_channels(self) -> None:
        for name, cls in discover_all().items():
            section = self.channels_config.get(name)
            if not isinstance(section, dict):
                continue
            if not bool(section.get("enabled", False)):
                continue
            try:
                channel = cls(section, self.bus)
                self.channels[name] = channel
                logger.info("Channel active: {} ({})", name, cls.__name__)
            except Exception as exc:
                logger.error("Channel {} non initialise: {}", name, exc)

        self._validate_allow_from()

    def _validate_allow_from(self) -> None:
        for name, channel in self.channels.items():
            allow_from = getattr(channel.config, "allow_from", None)
            if allow_from == []:
                raise SystemExit(
                    f'Configuration invalide: channel "{name}" a allowFrom vide ([]). '
                    'Utiliser ["*"] pour ouverture totale ou une liste d\'IDs explicites.'
                )

    async def _dispatch_outbound(self) -> None:
        logger.info("Dispatcher outbound channels demarre")
        while True:
            try:
                msg: OutboundMessage = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            channel = self.channels.get(msg.channel)
            if not channel:
                logger.warning("Message sortant pour channel inconnu: {}", msg.channel)
                continue
            try:
                await channel.send(msg)
            except Exception as exc:
                logger.error("Echec send channel {}: {}", msg.channel, exc)

    async def start_all(self) -> None:
        if not self.channels:
            logger.warning("Aucun channel active")
            return

        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        for name, channel in self.channels.items():
            logger.info("Demarrage channel {}...", name)
            task = asyncio.create_task(channel.start())
            self._start_tasks.append(task)

        await asyncio.gather(*self._start_tasks, return_exceptions=True)

    async def stop_all(self) -> None:
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass

        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info("Channel arrete: {}", name)
            except Exception as exc:
                logger.error("Erreur stop channel {}: {}", name, exc)

    def get_status(self) -> dict[str, Any]:
        return {
            name: {"enabled": True, "running": channel.is_running}
            for name, channel in self.channels.items()
        }
