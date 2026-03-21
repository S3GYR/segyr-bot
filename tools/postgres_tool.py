from __future__ import annotations

from typing import Any

from loguru import logger

from core.memory import MemoryStore
from core.tools import BaseTool


class PostgresTool(BaseTool):
    name = "postgres_tool"
    description = "CRUD Postgres sécurisé (clients, factures, projets, select restreint)."

    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    async def run(self, **kwargs: Any) -> Any:
        action = kwargs.get("action", "info")
        payload = kwargs.get("payload", {}) or {}
        logger.info("PostgresTool action=%s payload=%s", action, payload)

        if action == "query":
            sql = payload.get("sql")
            params = payload.get("params") or []
            return {"rows": self.store.raw_query(sql, params)}

        if action == "add_client":
            data = payload.get("data") or {}
            return {"client": self.store.add_client(data.get("name", "Client"), data.get("email"), data.get("phone"), data.get("notes"))}

        if action == "list_clients":
            return {"clients": self.store.list_clients()}

        if action == "add_facture":
            data = payload.get("data") or {}
            return {"facture": self.store.add_facture(data.get("client_id"), float(data.get("montant_ht", 0)), data.get("due_date"), data.get("reference"), data.get("notes"))}

        if action == "list_factures":
            return {"factures": self.store.list_factures()}

        if action == "add_project":
            data = payload.get("data") or {}
            return {
                "projet": self.store.add_project(
                    data.get("titre", "Projet"),
                    data.get("client_id"),
                    data.get("montant_ht"),
                    data.get("echeance"),
                    data.get("statut", "brouillon"),
                    data.get("avancement", 0.0),
                    data.get("notes"),
                )
            }

        if action == "list_projects":
            return {"projets": self.store.list_projects()}

        return {"status": "noop", "message": "action Postgres non reconnue"}
