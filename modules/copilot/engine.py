from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from modules.chantier.kpi import classify_budget_derive, classify_heures_derive


def _add_priority(priorites: List[Dict[str, Any]], niveau: str, message: str, meta: Dict[str, Any] | None = None) -> None:
    priorites.append({"niveau": niveau, "message": message, **(meta or {})})


def _sort_priorities(priorites: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    order = {"critique": 0, "eleve": 1, "normal": 2}
    return sorted(priorites, key=lambda p: order.get(p.get("niveau", "normal"), 2))


def generate_chantier_insights(
    chantier: Dict[str, Any],
    cashflow: Dict[str, Any],
    factures: List[Dict[str, Any]],
    clients: List[Dict[str, Any]],
    entreprise_id: str | None = None,
) -> Dict[str, Any]:
    priorites: List[Dict[str, Any]] = []
    alertes: List[str] = []
    actions: List[str] = []

    chantier_id = chantier.get("id")
    chantier_ent = chantier.get("entreprise_id")
    if entreprise_id and chantier_ent and chantier_ent != entreprise_id:
        return {
            "priorites": [{"niveau": "critique", "message": "Incohérence de données chantier (tenant)"}],
            "alertes": ["Analyse copilote bloquée: chantier hors entreprise"],
            "actions_recommandees": ["Vérifier l'isolation multi-tenant des données"],
            "resume": "Analyse interrompue pour incohérence de tenant.",
            "impact_financier_estime": 0.0,
        }

    scoped_factures = []
    for f in factures:
        if chantier_id is not None and f.get("chantier_id") != chantier_id:
            continue
        facture_ent = f.get("entreprise_id")
        if entreprise_id and facture_ent and facture_ent != entreprise_id:
            continue
        scoped_factures.append(f)

    scoped_clients = []
    for c in clients:
        client_ent = c.get("entreprise_id")
        if entreprise_id and client_ent and client_ent != entreprise_id:
            continue
        scoped_clients.append(c)

    risk_score = chantier.get("risk_score", 0) or 0
    derive_pct = chantier.get("derive_pourcentage", 0) or 0
    derive_budget_pct = chantier.get("derive_budget_pourcentage", 0) or 0
    montant_ht = chantier.get("montant_ht", 0) or 0

    # 1. Risque chantier
    if risk_score > 80:
        alertes.append("Risque chantier critique")
        _add_priority(priorites, "critique", "Risque chantier élevé (>80)")
    elif risk_score > 60:
        alertes.append("Risque chantier à surveiller")
        _add_priority(priorites, "eleve", "Risque chantier significatif (>60)")

    # 2. Dérive heures
    derive_heures_niveau = classify_heures_derive(derive_pct)
    if derive_heures_niveau == "critique":
        alertes.append("Dérive heures critique (>20%)")
        actions.append("Réévaluer le reste à faire")
        _add_priority(priorites, "critique", "Dérive heures majeure")
    elif derive_heures_niveau == "eleve":
        alertes.append("Dérive heures à surveiller (>10%)")
        _add_priority(priorites, "eleve", "Dérive heures modérée")

    # 3. Budget matériel
    derive_budget_niveau = classify_budget_derive(derive_budget_pct)
    if derive_budget_niveau == "critique":
        alertes.append("Dérive budget matériel (>20%)")
        actions.append("Bloquer achats non essentiels")
        _add_priority(priorites, "critique", "Budget matériel en dérive critique")
    elif derive_budget_niveau == "eleve":
        alertes.append("Dérive budget matériel à surveiller (>10%)")
        _add_priority(priorites, "eleve", "Budget matériel en dérive")

    # 4. Trésorerie
    cashflow_balance = cashflow.get("balance", cashflow.get("solde", 0)) or 0
    if cashflow_balance < 0:
        alertes.append("Tension de trésorerie (cashflow négatif)")
        actions.append("Demander acompte")
        _add_priority(priorites, "critique", "Cashflow négatif")

    # 5. Factures impayées
    today_str = str(date.today())
    impayees = [
        f for f in scoped_factures
        if str(f.get("statut") or "").lower() not in {"payée", "paye"}
        and f.get("due_date")
        and str(f["due_date"]) < today_str
    ]
    impayes_total = sum(float(f.get("montant_ht") or 0) for f in impayees)
    if impayees:
        actions.append("Relancer client")
        _add_priority(priorites, "eleve" if impayes_total > 0 else "normal", "Factures impayées à relancer", {"montant": impayes_total})

    # 6. Client à risque
    client = None
    client_id = chantier.get("client_id")
    if client_id is not None:
        client = next((c for c in scoped_clients if c.get("id") == client_id), None)
        if client is None:
            alertes.append("Client lié introuvable pour ce chantier")
            _add_priority(priorites, "normal", "Vérifier la cohérence client du chantier")
    score_client = client.get("score_client") if client else None
    if score_client is not None and score_client < 50:
        alertes.append("Client à risque (score < 50)")
        _add_priority(priorites, "eleve", "Client à risque")

    # Impact financier estimé (dérive heures + impayés)
    impact_financier_estime = impayes_total + max(0.0, derive_pct) * montant_ht / 100

    # Résumé
    resume_parts = []
    if risk_score > 80:
        resume_parts.append("chantier à risque critique")
    elif risk_score > 60:
        resume_parts.append("chantier à risque élevé")
    if derive_heures_niveau != "normal":
        resume_parts.append("dérive des heures")
    if derive_budget_niveau != "normal":
        resume_parts.append("dérive budget matériel")
    if cashflow_balance < 0:
        resume_parts.append("tension de trésorerie")
    if impayees:
        resume_parts.append("factures impayées")
    if score_client is not None and score_client < 50:
        resume_parts.append("client à risque")
    resume = "Chantier stable." if not resume_parts else "Chantier " + " avec ".join([resume_parts[0]] + resume_parts[1:]) + "."

    priorites_sorted = _sort_priorities(priorites)

    return {
        "priorites": priorites_sorted,
        "alertes": alertes,
        "actions_recommandees": actions,
        "resume": resume,
        "impact_financier_estime": impact_financier_estime,
    }
