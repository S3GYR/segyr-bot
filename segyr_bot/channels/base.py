from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from core.bus.events import InboundMessage, OutboundMessage
from core.bus.queue import MessageBus
from segyr_bot.channels.logging import logger


class ChannelConfigBase(BaseModel):
    """Base de configuration partagee des channels SEGYR."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")

    enabled: bool = False
    allow_from: list[str] = Field(default_factory=lambda: ["*"])


class BaseChannel(ABC):
    """Interface commune des channels SEGYR."""

    name: str = "base"
    display_name: str = "Base"

    def __init__(self, config: Any, bus: MessageBus):
        self.config = config
        self.bus = bus
        self._running = False

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return ChannelConfigBase().model_dump(by_alias=True)

    def is_allowed(self, sender_id: str) -> bool:
        """Controle d'acces par allowFrom.

        - []: bloque tout
        - ["*"]: autorise tout
        - liste explicite: filtre par sender_id exact
        """

        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list:
            logger.warning("{}: allow_from vide -> acces refuse", self.name)
            return False
        if "*" in allow_list:
            return True
        return str(sender_id) in {str(v) for v in allow_list}

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> bool:
        """Valide le sender puis publie le message entrant dans le bus."""

        if not self.is_allowed(sender_id):
            logger.warning(
                "Acces refuse sender={} channel={} (verifier allowFrom)",
                sender_id,
                self.name,
            )
            return False

        msg = InboundMessage(
            channel=self.name,
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            media=media or [],
            metadata=metadata or {},
            session_key_override=session_key,
        )
        await self.bus.publish_inbound(msg)
        return True

    async def transcribe_audio(self, file_path: str | Path) -> str:
        """Point d'extension futur pour transcription audio."""

        _ = file_path
        return ""

    @property
    def is_running(self) -> bool:
        return self._running

    @abstractmethod
    async def start(self) -> None:
        """Demarre le channel (tache longue duree)."""

    @abstractmethod
    async def stop(self) -> None:
        """Arrete le channel proprement."""

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """Envoie un message sortant vers le canal externe."""
