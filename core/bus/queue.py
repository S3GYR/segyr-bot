"""Async message queue for decoupled communication."""

import asyncio
from asyncio import QueueFull

from core.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """
    Async message bus decoupling input channels from the agent core.

    Channels push messages to the inbound queue.
    The agent processes them and pushes responses to the outbound queue.
    """

    def __init__(self, max_inbound: int = 1000, max_outbound: int = 1000):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=max_inbound)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=max_outbound)
        self._max_inbound = max_inbound
        self._max_outbound = max_outbound

    async def publish_inbound(self, msg: InboundMessage) -> None:
        try:
            self.inbound.put_nowait(msg)
        except QueueFull:
            raise

    async def consume_inbound(self) -> InboundMessage:
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        try:
            self.outbound.put_nowait(msg)
        except QueueFull:
            raise

    async def consume_outbound(self) -> OutboundMessage:
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        return self.outbound.qsize()

    @property
    def inbound_max(self) -> int:
        return self._max_inbound

    @property
    def outbound_max(self) -> int:
        return self._max_outbound
