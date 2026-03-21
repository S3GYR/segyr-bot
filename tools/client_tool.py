from __future__ import annotations

from typing import Any

from loguru import logger

from core.tools import BaseTool
from modules.clients.schema import Client
from modules.clients.service import ClientService


class ClientTool(BaseTool):
    name = "client_tool"
    description = "Gérer les clients (création, listing, mise à jour)."

    def __init__(self, service: ClientService) -> None:
        self.service = service

    async def run(self, **kwargs: Any) -> Any:
        action = kwargs.get("action", "manage")
        payload = kwargs.get("payload", {}) or {}
        logger.info("ClientTool action=%s", action)

        if action == "create":
            data = payload.get("data") or {}
            client = Client(id=None, name=data.get("name", "Client"), email=data.get("email"), phone=data.get("phone"))
            created = self.service.create(client)
            return {"status": "created", "client": created.__dict__}

        if action == "list":
            return {"clients": [c.__dict__ for c in self.service.list()]}

        if action == "update":
            cid = payload.get("id")
            if not cid:
                return {"error": "client id manquant"}
            updated = self.service.update(int(cid), payload.get("data") or {})
            return {"status": "updated", "client": updated.__dict__ if updated else None}

        return {"status": "noop", "message": "aucune action client exécutée"}
