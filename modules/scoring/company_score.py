from __future__ import annotations

from typing import Any, Dict, Iterable


def _avg(values: Iterable[float]) -> float:
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def compute_company_score(
    clients: list[Dict[str, Any]] | None = None,
    chantiers: list[Dict[str, Any]] | None = None,
    cashflow: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    clients = clients or []
    chantiers = chantiers or []
    cashflow = cashflow or {}

    score = 100
    details: Dict[str, Any] = {
        "finance": 0,
        "chantier": 0,
        "clients": 0,
    }

    # Finance
    total_in = float(cashflow.get("total_in") or cashflow.get("encaissements") or 0)
    balance = float(cashflow.get("balance") or cashflow.get("solde") or 0)
    impayes_total = float(cashflow.get("impayes_total") or cashflow.get("impayes", 0) or 0)
    if balance < 0:
        score -= 30
        details["finance"] -= 30
    impayes_threshold = max(5000.0, total_in * 0.15) if total_in > 0 else 5000.0
    if impayes_total >= impayes_threshold:
        score -= 20
        details["finance"] += -20

    # Chantier
    avg_risk = _avg(c.get("risk_score") for c in chantiers)
    avg_derive = _avg(c.get("derive_pourcentage") for c in chantiers)
    if avg_risk > 60:
        score -= 25
        details["chantier"] += -25
    if avg_derive > 10:
        score -= 15
        details["chantier"] += -15

    # Clients
    avg_client_score = _avg(c.get("score_client") for c in clients)
    if avg_client_score and avg_client_score < 60:
        score -= 20
        details["clients"] += -20

    score = max(0, min(100, score))
    if score >= 70:
        niveau = "sain"
    elif score >= 50:
        niveau = "surveillé"
    else:
        niveau = "critique"

    return {
        "score": score,
        "niveau": niveau,
        "details": details,
    }
