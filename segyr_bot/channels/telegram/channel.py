from __future__ import annotations

import asyncio
from typing import Any

from core.bus.events import OutboundMessage
from core.bus.queue import MessageBus
from segyr_bot.channels.logging import logger

from segyr_bot.channels.base import BaseChannel, ChannelConfigBase


class TelegramConfig(ChannelConfigBase):
    token: str = ""
    proxy: str | None = None
    poll_interval_s: float = 1.0


class TelegramChannel(BaseChannel):
    """Channel Telegram SEGYR (long polling)."""

    name = "telegram"
    display_name = "Telegram"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return TelegramConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = TelegramConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self._app = None
        self._chat_ids: dict[str, int] = {}

    async def start(self) -> None:
        if not self.config.token:
            logger.error("Telegram token manquant")
            return

        try:
            from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
        except Exception as exc:  # pragma: no cover - dependance optionnelle
            logger.error("python-telegram-bot indisponible: {}", exc)
            return

        self._running = True
        self._app = Application.builder().token(self.config.token).build()

        async def _on_start(update, context: ContextTypes.DEFAULT_TYPE) -> None:
            _ = context
            if update.message:
                await update.message.reply_text("SEGYR-BOT actif. Envoyez votre message.")

        async def _on_help(update, context: ContextTypes.DEFAULT_TYPE) -> None:
            _ = context
            if update.message:
                await update.message.reply_text("Commandes: /start, /help")

        async def _on_message(update, context: ContextTypes.DEFAULT_TYPE) -> None:
            _ = context
            if not update.message or not update.effective_user:
                return

            user = update.effective_user
            sender_id = str(user.id)
            chat_id = str(update.effective_chat.id)
            text = update.message.text or ""
            self._chat_ids[sender_id] = int(chat_id)

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=text,
                metadata={
                    "telegram_message_id": getattr(update.message, "message_id", None),
                    "username": getattr(user, "username", None),
                },
            )

        self._app.add_handler(CommandHandler("start", _on_start))
        self._app.add_handler(CommandHandler("help", _on_help))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))

        logger.info("Telegram channel started")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        while self._running:
            await asyncio.sleep(max(self.config.poll_interval_s, 0.1))

    async def stop(self) -> None:
        self._running = False
        if self._app is None:
            return

        try:
            if self._app.updater:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        finally:
            logger.info("Telegram channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        if self._app is None:
            logger.warning("Telegram send ignore: app non initialisee")
            return

        chat_id = None
        if str(msg.chat_id).isdigit():
            chat_id = int(msg.chat_id)
        elif str(msg.chat_id) in self._chat_ids:
            chat_id = self._chat_ids[str(msg.chat_id)]

        if chat_id is None:
            logger.warning("Telegram send ignore: chat_id inconnu {}", msg.chat_id)
            return

        await self._app.bot.send_message(chat_id=chat_id, text=msg.content)
