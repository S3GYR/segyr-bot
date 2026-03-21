from __future__ import annotations

from datetime import date
from typing import Any

from loguru import logger

from core.tools import BaseTool
from modules.factures.schema import Facture
from modules.factures.service import InvoiceService


class InvoiceTool(BaseTool):
    name = "invoice_tool"
    description = "Gérer les factures (création, listing, mise à jour)."

    def __init__(self, service: InvoiceService) -> None:
        self.service = service

    async def run(self, **kwargs: Any) -> Any:
        action = kwargs.get("action", "process")
        payload = kwargs.get("payload", {}) or {}
        logger.info("InvoiceTool action=%s", action)

        if action == "create":
            data = payload.get("data") or {}
            facture = Facture(
                id=None,
                client_id=data.get("client_id"),
                montant_ht=float(data.get("montant_ht", 0)),
                due_date=data.get("due_date"),
                reference=data.get("reference"),
            )
            created = self.service.create(facture)
            return {"status": "created", "facture": created.__dict__}

        if action == "list":
            return {"factures": [f.__dict__ for f in self.service.list()]}

        if action == "update":
            fid = payload.get("id")
            if not fid:
                return {"error": "facture id manquant"}
            updated = self.service.update(int(fid), payload.get("data") or {})
            return {"status": "updated", "facture": updated.__dict__ if updated else None}

        if action == "relance":
            factures = self.service.list()
            overdue = []
            today = date.today()
            for f in factures:
                if f.due_date and f.due_date < today and f.statut != "payée":
                    overdue.append(f.__dict__)
            return {"relances": overdue, "message": "Relances à effectuer", "count": len(overdue)}

        return {"status": "noop", "message": "aucune action facture exécutée"}
