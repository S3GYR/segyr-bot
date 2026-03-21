from __future__ import annotations

import asyncio
from typing import Any

from core.bus.events import OutboundMessage
from core.bus.queue import MessageBus
from segyr_bot.channels.logging import logger

from segyr_bot.channels.base import BaseChannel, ChannelConfigBase


class SegyrInternalConfig(ChannelConfigBase):
    enabled: bool = True


class SegyrInternalChannel(BaseChannel):
    """Channel interne SEGYR pour tests, debug et integration systeme."""

    name = "segyr_internal"
    display_name = "SEGYR Internal"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return SegyrInternalConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = SegyrInternalConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: SegyrInternalConfig = config
        self._inbound_simulator: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent_messages: list[OutboundMessage] = []

    async def inject_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Injecte un message entrant simulé (utile en test)."""

        await self._inbound_simulator.put(
            {
                "sender_id": sender_id,
                "chat_id": chat_id,
                "content": content,
                "metadata": metadata or {},
            }
        )

    async def start(self) -> None:
        self._running = True
        logger.info("SegyrInternal channel started")

        while self._running:
            try:
                payload = await asyncio.wait_for(self._inbound_simulator.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            await self._handle_message(
                sender_id=str(payload["sender_id"]),
                chat_id=str(payload["chat_id"]),
                content=str(payload["content"]),
                metadata=dict(payload.get("metadata") or {}),
            )

    async def stop(self) -> None:
        self._running = False
        logger.info("SegyrInternal channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        self.sent_messages.append(msg)
        logger.info("SegyrInternal outbound chat_id={} content_len={}", msg.chat_id, len(msg.content))
