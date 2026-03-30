from __future__ import annotations

import asyncio
import uuid
from typing import Any

from core.bus.events import OutboundMessage
from core.bus.queue import MessageBus
from segyr_bot.channels.logging import logger

from segyr_bot.channels.base import BaseChannel, ChannelConfigBase


class WebhookConfig(ChannelConfigBase):
    host: str = "0.0.0.0"
    port: int = 8090
    route: str = "/message"
    response_timeout_s: float = 20.0


class WebhookChannel(BaseChannel):
    """Channel webhook HTTP pour integrations SI/outils externes."""

    name = "webhook"
    display_name = "Webhook"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WebhookConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WebhookConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WebhookConfig = config
        self._app: Any = None
        self._server: Any = None
        self._bootstrap_error: Exception | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        try:
            from fastapi import FastAPI

            self._app = FastAPI(title="SEGYR Webhook Channel")
            self._register_routes()
        except Exception as exc:
            self._bootstrap_error = exc

    def _register_routes(self) -> None:
        route = self.config.route

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

        @self._app.get("/health")
        async def _health() -> dict[str, str]:
            return {"status": "ok", "channel": self.name}

        @self._app.post(route)
        async def _receive(payload: dict[str, Any]) -> dict[str, Any]:
            parsed = _extract_message(payload)
            if not parsed:
                return {"ok": True, "ignored": True}
            sender, chat_id, text, media = parsed

            request_id = str(uuid.uuid4())
            fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
            self._pending[request_id] = fut

            accepted = await self._handle_message(
                sender_id=sender,
                chat_id=chat_id,
                content=text,
                media=media if isinstance(media, list) else [],
                metadata={
                    "request_id": request_id,
                    "raw_payload": payload,
                    "channel": self.name,
                },
            )
            if not accepted:
                self._pending.pop(request_id, None)
                return {"ok": False, "error": "sender not allowed"}

            try:
                response = await asyncio.wait_for(fut, timeout=self.config.response_timeout_s)
                return {"ok": True, **response}
            except asyncio.TimeoutError:
                self._pending.pop(request_id, None)
                return {
                    "ok": True,
                    "reply": "Traitement en cours",
                    "timeout": True,
                    "request_id": request_id,
                }

    async def start(self) -> None:
        if self._app is None:
            logger.error("Webhook channel indisponible (fastapi manquant?): {}", self._bootstrap_error)
            return

        try:
            import uvicorn
        except Exception as exc:
            logger.error("Webhook channel indisponible (uvicorn manquant?): {}", exc)
            return

        self._running = True
        logger.info("Webhook channel started host={} port={} route={}", self.config.host, self.config.port, self.config.route)

        uv_cfg = uvicorn.Config(
            self._app,
            host=self.config.host,
            port=self.config.port,
            log_level="info",
            access_log=False,
        )
        self._server = uvicorn.Server(uv_cfg)
        await self._server.serve()

    async def stop(self) -> None:
        self._running = False
        if self._server is not None:
            self._server.should_exit = True
        logger.info("Webhook channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        request_id = str((msg.metadata or {}).get("request_id") or "")
        if request_id and request_id in self._pending:
            fut = self._pending.pop(request_id)
            if not fut.done():
                fut.set_result(
                    {
                        "chat_id": msg.chat_id,
                        "reply": msg.content,
                        "metadata": msg.metadata,
                    }
                )
            return

        logger.info("Webhook outbound without request_id chat_id={}", msg.chat_id)
