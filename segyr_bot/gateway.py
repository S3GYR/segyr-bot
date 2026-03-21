from __future__ import annotations

import argparse
import asyncio
import json
import signal
from pathlib import Path
from typing import Any

from core.agent.loop import AgentLoop
from core.bus.queue import MessageBus
from core.providers.base import GenerationSettings
from core.providers.registry import get_provider
from segyr_bot.channels.logging import logger
from segyr_bot.channels.manager import ChannelManager
from segyr_bot.channels.registry import discover_all


def _get_settings():
    from config.settings import settings

    return settings


def _default_channels_config_path() -> Path:
    settings = _get_settings()
    workspace_cfg = settings.workspace / "channels.json"
    if workspace_cfg.exists():
        return workspace_cfg

    # Fallback to bundled example config.
    return Path(__file__).parent / "channels" / "config.example.json"


def load_channels_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        logger.warning("Fichier de config channels introuvable: {}", config_path)
        return {}

    with open(config_path, encoding="utf-8") as fh:
        raw = json.load(fh)

    channels = raw.get("channels", raw)
    if not isinstance(channels, dict):
        raise ValueError("Configuration channels invalide: objet attendu")

    return channels


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event) -> None:
    def _request_shutdown(sig_name: str) -> None:
        if not stop_event.is_set():
            logger.warning("Signal {} recu: arret du gateway...", sig_name)
            stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown, sig.name)
        except (NotImplementedError, RuntimeError, ValueError):
            def _handler(_signum: int, _frame: object, sig_name: str = sig.name) -> None:
                loop.call_soon_threadsafe(_request_shutdown, sig_name)

            signal.signal(sig, _handler)


async def run_gateway(channels_config_path: Path | None = None) -> None:
    settings = _get_settings()
    config_path = channels_config_path or _default_channels_config_path()
    channels_config = load_channels_config(config_path)

    discovered = sorted(discover_all().keys())

    bus = MessageBus()
    provider = get_provider(
        model=settings.llm.model,
        api_key=settings.llm.api_key or None,
        api_base=settings.llm.api_base or None,
    )
    provider.generation = GenerationSettings(
        temperature=settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
    )

    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=settings.workspace,
        model=settings.llm.model,
        max_iterations=settings.agent.max_iterations,
        context_window_tokens=settings.llm.context_window_tokens,
        exec_timeout=settings.agent.exec_timeout,
        restrict_to_workspace=settings.agent.restrict_to_workspace,
    )

    channels = ChannelManager(channels_config=channels_config, bus=bus)

    logger.info("Gateway started")
    logger.info("Channels discovered: {}", discovered)
    logger.info("Channels enabled: {}", sorted(channels.channels.keys()))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop, stop_event)

    agent_task = asyncio.create_task(agent.run(), name="agent-loop")
    channels_task = asyncio.create_task(channels.start_all(), name="channels-manager")

    logger.info("Agent loop running")
    logger.info("Channels started")

    def _task_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Tache {} en echec: {}", task.get_name(), exc)
            if not stop_event.is_set():
                stop_event.set()

    agent_task.add_done_callback(_task_done)
    channels_task.add_done_callback(_task_done)

    await stop_event.wait()

    logger.info("Arret du gateway en cours...")
    agent.stop()
    await channels.stop_all()

    for task in (agent_task, channels_task):
        if not task.done():
            task.cancel()

    await asyncio.gather(agent_task, channels_task, return_exceptions=True)
    logger.info("Gateway stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="SEGYR-BOT Gateway")
    parser.add_argument(
        "--channels-config",
        type=str,
        default=None,
        help="Chemin du fichier JSON de configuration des channels",
    )
    args = parser.parse_args()

    path = Path(args.channels_config).expanduser().resolve() if args.channels_config else None
    asyncio.run(run_gateway(path))


if __name__ == "__main__":
    main()
