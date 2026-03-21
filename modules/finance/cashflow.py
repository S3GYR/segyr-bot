from __future__ import annotations

from datetime import date
from typing import Dict, List, TypedDict


class CashflowData(TypedDict):
    total_in: float
    total_out: float
    balance: float
    impayes_total: float
    encaissements: float
    decaissements: float
    solde: float


def compute_cashflow(
    factures_clients: List[Dict[str, object]],
    factures_fournisseurs: List[Dict[str, object]],
) -> CashflowData:
    total_in = sum(float(f.get("montant_ht") or 0) for f in factures_clients)
    total_out = sum(float(f.get("montant_ht") or 0) for f in factures_fournisseurs)
    balance = total_in - total_out

    today_str = str(date.today())
    impayees_retard = [
        f
        for f in factures_clients
        if str(f.get("statut") or "").lower() not in {"payée", "paye"}
        and f.get("due_date")
        and str(f.get("due_date")) < today_str
    ]
    impayes_total = sum(float(f.get("montant_ht") or 0) for f in impayees_retard)

    return {
        "total_in": total_in,
        "total_out": total_out,
        "balance": balance,
        "impayes_total": impayes_total,
        # Backward-compatible aliases used by existing endpoints/frontend.
        "encaissements": total_in,
        "decaissements": total_out,
        "solde": balance,
    }
