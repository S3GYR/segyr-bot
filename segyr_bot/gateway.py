from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request

from core.agent.loop import AgentLoop
from core.bus.events import InboundMessage, OutboundMessage
from core.bus.queue import MessageBus
from core.providers.base import GenerationSettings
from core.providers.registry import get_provider
from segyr_bot.channels.logging import logger


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


def _ensure_webhook_defaults(channels_config: dict[str, Any]) -> dict[str, Any]:
    webhook = channels_config.get("webhook")
    if not isinstance(webhook, dict):
        webhook = {}

    webhook.setdefault("enabled", True)
    webhook["host"] = "0.0.0.0"
    webhook["port"] = 8090
    webhook["route"] = "/message"
    webhook.setdefault("allowFrom", ["*"])

    channels_config["webhook"] = webhook
    return channels_config


def _extract_message(payload: dict[str, Any]) -> tuple[str, str, str, list[str]] | None:
    sender = str(payload.get("sender") or payload.get("sender_id") or "").strip()
    chat_id = str(payload.get("chat_id") or payload.get("conversation_id") or sender).strip()
    text = str(payload.get("text") or payload.get("message") or "").strip()
    media = payload.get("media") or []

    if text and chat_id:
        return sender or chat_id, chat_id, text, media if isinstance(media, list) else []

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    message_block = data.get("message") if isinstance(data, dict) and isinstance(data.get("message"), dict) else {}
    key_block = message_block.get("key") if isinstance(message_block.get("key"), dict) else {}
    message_data = message_block.get("message") if isinstance(message_block.get("message"), dict) else {}
    extended = message_data.get("extendedTextMessage") if isinstance(message_data.get("extendedTextMessage"), dict) else {}

    evo_text = str(
        message_data.get("conversation")
        or extended.get("text")
        or (data.get("text") if isinstance(data, dict) else None)
        or payload.get("message")
        or ""
    ).strip()
    evo_chat_id = str(
        key_block.get("remoteJid")
        or (data.get("chat_id") if isinstance(data, dict) else None)
        or payload.get("chat_id")
        or ""
    ).strip()
    evo_sender = str(
        key_block.get("participant")
        or key_block.get("remoteJid")
        or payload.get("sender")
        or evo_chat_id
    ).strip()

    if evo_text and evo_chat_id:
        return evo_sender or evo_chat_id, evo_chat_id, evo_text, []
    return None


class GatewayRuntime:
    def __init__(self) -> None:
        self.channels_config_path: Path | None = None
        self.started = False
        self.bus: MessageBus | None = None
        self.agent: AgentLoop | None = None
        self.agent_task: asyncio.Task | None = None
        self.outbound_task: asyncio.Task | None = None
        self.response_timeout_s = 20.0
        self.allow_from: set[str] = {"*"}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_lock = asyncio.Lock()

    async def start(self) -> None:
        try:
            if self.started:
                return

            settings = _get_settings()
            config_path = self.channels_config_path or _default_channels_config_path()
            channels_config = _ensure_webhook_defaults(load_channels_config(config_path))
            webhook_cfg = channels_config.get("webhook") if isinstance(channels_config.get("webhook"), dict) else {}
            allow_from = webhook_cfg.get("allowFrom") or webhook_cfg.get("allow_from") or ["*"]
            self.allow_from = {str(v) for v in allow_from} if isinstance(allow_from, list) else {"*"}

            response_timeout = webhook_cfg.get("responseTimeoutS") or webhook_cfg.get("response_timeout_s") or 20.0
            try:
                self.response_timeout_s = max(float(response_timeout), 1.0)
            except Exception:
                self.response_timeout_s = 20.0

            self.bus = MessageBus()
            provider = get_provider(
                model=settings.llm.model,
                provider=settings.llm.provider,
                api_key=settings.llm.api_key or None,
                api_base=settings.llm.api_base or None,
            )
            provider.generation = GenerationSettings(
                temperature=settings.llm.temperature,
                max_tokens=settings.llm.max_tokens,
            )

            self.agent = AgentLoop(
                bus=self.bus,
                provider=provider,
                workspace=settings.workspace,
                model=provider.get_default_model(),
                max_iterations=settings.agent.max_iterations,
                context_window_tokens=settings.llm.context_window_tokens,
                exec_timeout=settings.agent.exec_timeout,
                restrict_to_workspace=settings.agent.restrict_to_workspace,
            )

            self.agent_task = asyncio.create_task(self.agent.run(), name="gateway-agent-loop")
            self.outbound_task = asyncio.create_task(self._dispatch_outbound(), name="gateway-outbound-dispatcher")
            self.started = True
            logger.info("Gateway started (FastAPI) host=0.0.0.0 port=8090")
            print("✅ Runtime started")
        except Exception as e:
            print(f"❌ Runtime failed: {e}")
            raise

    async def stop(self) -> None:
        if not self.started:
            return

        self.started = False

        if self.agent is not None:
            self.agent.stop()

        tasks = [t for t in (self.agent_task, self.outbound_task) if t is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        async with self._pending_lock:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(asyncio.CancelledError())
            self._pending.clear()

        logger.info("Gateway stopped")

    def _is_allowed(self, sender_id: str) -> bool:
        if not self.allow_from:
            return False
        if "*" in self.allow_from:
            return True
        return str(sender_id) in self.allow_from

    async def _dispatch_outbound(self) -> None:
        while self.started:
            if self.bus is None:
                await asyncio.sleep(0.05)
                continue
            try:
                msg: OutboundMessage = await self.bus.consume_outbound()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Dispatcher outbound en echec: {}", exc)
                await asyncio.sleep(0.1)
                continue

            metadata = msg.metadata or {}
            if metadata.get("_progress"):
                continue

            request_id = str(metadata.get("request_id") or "").strip()
            if not request_id:
                continue

            async with self._pending_lock:
                fut = self._pending.pop(request_id, None)
            if fut is not None and not fut.done():
                fut.set_result(
                    {
                        "ok": True,
                        "chat_id": msg.chat_id,
                        "reply": msg.content,
                        "metadata": metadata,
                    }
                )

    async def handle_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.started or self.bus is None:
            return {"ok": False, "error": "gateway not ready"}

        parsed = _extract_message(payload)
        if not parsed:
            return {"ok": True, "ignored": True}

        sender, chat_id, text, media = parsed
        if not self._is_allowed(sender):
            return {"ok": False, "error": "sender not allowed"}

        request_id = str(uuid.uuid4())
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

        async with self._pending_lock:
            self._pending[request_id] = fut

        inbound = InboundMessage(
            channel="webhook",
            sender_id=sender,
            chat_id=chat_id,
            content=text,
            media=media if isinstance(media, list) else [],
            metadata={
                "request_id": request_id,
                "raw_payload": payload,
                "channel": "webhook",
            },
        )
        await self.bus.publish_inbound(inbound)

        try:
            return await asyncio.wait_for(fut, timeout=self.response_timeout_s)
        except asyncio.TimeoutError:
            async with self._pending_lock:
                self._pending.pop(request_id, None)
            return {
                "ok": True,
                "reply": "Traitement en cours",
                "timeout": True,
                "request_id": request_id,
                "chat_id": chat_id,
            }


runtime = GatewayRuntime()
app = FastAPI(title="SEGYR Gateway", version="1.0.0")
_startup_task: asyncio.Task | None = None


@app.on_event("startup")
async def _on_startup() -> None:
    global _startup_task

    def _on_runtime_started(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        if task.exception() is None:
            print("🚀 Gateway fully initialized")

    _startup_task = asyncio.create_task(runtime.start())
    _startup_task.add_done_callback(_on_runtime_started)


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    global _startup_task

    if _startup_task is not None and not _startup_task.done():
        _startup_task.cancel()
        await asyncio.gather(_startup_task, return_exceptions=True)
    await runtime.stop()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/message")
async def message(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload must be a JSON object"}
    return await runtime.handle_message(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="SEGYR-BOT Gateway")
    parser.add_argument(
        "--channels-config",
        type=str,
        default=None,
        help="Chemin du fichier JSON de configuration des channels",
    )
    args = parser.parse_args()

    runtime.channels_config_path = Path(args.channels_config).expanduser().resolve() if args.channels_config else None
    try:
        if asyncio.get_event_loop().is_running():
            print("⚠️ Event loop déjà actif")
    except RuntimeError:
        pass
    print("⏳ Gateway booting...")
    time.sleep(1)
    print("🚀 Starting Gateway container...")
    print("🚀 Gateway started on port 8090")
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="info", loop="asyncio")


if __name__ == "__main__":
    main()
