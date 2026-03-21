from __future__ import annotations

from typing import Any

from loguru import logger

from core.memory import MemoryStore
from core.tools import BaseTool
from modules.finance.cashflow import compute_cashflow


class FinanceTool(BaseTool):
    name = "finance_tool"
    description = "Calculer le cashflow en cours (factures clients/fournisseurs impayées)."

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def run(self, **kwargs: Any) -> Any:
        action = kwargs.get("action", "cashflow")
        payload = kwargs.get("payload", {}) or {}
        entreprise_id = payload.get("entreprise_id")
        logger.info("FinanceTool action=%s entreprise_id=%s", action, entreprise_id)

        if action in {"cashflow", "get_cashflow", "read"}:
            factures_clients = self.store.get_unpaid_client_invoices(entreprise_id=entreprise_id)
            factures_fournisseurs = self.store.get_unpaid_supplier_invoices(entreprise_id=entreprise_id)
            data = compute_cashflow(factures_clients, factures_fournisseurs)
            return {"cashflow": data}

        return {"status": "noop", "message": "aucune action finance exécutée"}
