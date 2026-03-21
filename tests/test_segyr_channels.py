from __future__ import annotations

import asyncio

import pytest

from core.bus.events import OutboundMessage
from core.bus.queue import MessageBus
from segyr_bot.channels.registry import discover_builtin
from segyr_bot.channels.segyr_internal.channel import SegyrInternalChannel


@pytest.mark.asyncio
async def test_discover_builtin_channels_contains_expected_names() -> None:
    names = set(discover_builtin().keys())
    assert {"segyr_internal", "telegram", "webhook"}.issubset(names)


@pytest.mark.asyncio
async def test_segyr_internal_start_is_long_running() -> None:
    bus = MessageBus()
    ch = SegyrInternalChannel({"enabled": True, "allowFrom": ["*"]}, bus)

    task = asyncio.create_task(ch.start())
    await asyncio.sleep(0.05)
    assert not task.done()

    await ch.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_segyr_internal_message_flow_and_send() -> None:
    bus = MessageBus()
    ch = SegyrInternalChannel({"enabled": True, "allowFrom": ["*"]}, bus)

    task = asyncio.create_task(ch.start())

    await ch.inject_message("alice", "room-1", "ping")
    inbound = await asyncio.wait_for(bus.consume_inbound(), timeout=2)
    assert inbound.channel == "segyr_internal"
    assert inbound.sender_id == "alice"
    assert inbound.chat_id == "room-1"
    assert inbound.content == "ping"

    await ch.send(OutboundMessage(channel="segyr_internal", chat_id="room-1", content="pong"))
    assert ch.sent_messages[-1].content == "pong"

    await ch.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_allow_from_empty_blocks_messages() -> None:
    bus = MessageBus()
    ch = SegyrInternalChannel({"enabled": True, "allowFrom": []}, bus)

    accepted = await ch._handle_message(sender_id="alice", chat_id="room", content="hello")
    assert accepted is False
    assert bus.inbound_size == 0
