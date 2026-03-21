from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from modules.copilot.engine import generate_chantier_insights
from modules.finance.cashflow import compute_cashflow


def _dedupe(seq: List[str]) -> List[str]:
    return list(dict.fromkeys([s for s in seq if s]))


def generate_daily_copilot(store, entreprise_id: str | None = None) -> Dict[str, Any]:
    """Génère un rapport quotidien copilote agrégé."""

    chantiers = store.list_projects(entreprise_id=entreprise_id)
    clients = store.list_clients(entreprise_id=entreprise_id)
    factures = store.list_factures(entreprise_id=entreprise_id)

    cashflow = compute_cashflow(
        store.get_unpaid_client_invoices(entreprise_id=entreprise_id),
        store.get_unpaid_supplier_invoices(entreprise_id=entreprise_id),
    )

    alertes_critiques: List[str] = []
    actions_prioritaires: List[str] = []
    resumes: List[str] = []
    notifications: List[str] = []

    for c in chantiers:
        if entreprise_id and c.get("entreprise_id") and c.get("entreprise_id") != entreprise_id:
            alertes_critiques.append("Incohérence tenant détectée sur un chantier")
            continue

        insights = generate_chantier_insights(
            chantier=c,
            cashflow=cashflow,
            factures=[f for f in factures if f.get("chantier_id") == c.get("id")],
            clients=clients,
            entreprise_id=entreprise_id,
        )
        resumes.append(insights.get("resume", ""))
        for p in insights.get("priorites", []):
            if p.get("niveau") == "critique":
                alertes_critiques.append(p.get("message", "Priorité critique"))
        if any(p.get("niveau") == "critique" for p in insights.get("priorites", [])):
            actions_prioritaires.extend(insights.get("actions_recommandees", []))
        else:
            notifications.extend(insights.get("alertes", []))

    resume_global = "; ".join([r for r in resumes if r]) or "Aucun risque détecté."

    return {
        "date": date.today().isoformat(),
        "alertes_critiques": _dedupe(alertes_critiques),
        "actions_prioritaires": _dedupe(actions_prioritaires),
        "resume_global": resume_global,
        "notifications": _dedupe(notifications),
    }
