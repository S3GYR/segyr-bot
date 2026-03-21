from __future__ import annotations

from typing import Dict, List

from modules.chantier.kpi import (
    BUDGET_DERIVE_CRITIQUE_PCT,
    BUDGET_DERIVE_ELEVE_PCT,
    HEURES_DERIVE_CRITIQUE_PCT,
    HEURES_DERIVE_ELEVE_PCT,
)


def compute_heures_metrics(chantier: Dict[str, object]) -> Dict[str, float]:
    """Calcule les métriques d'heures à partir d'un chantier.

    Les champs non présents sont considérés à 0 pour conserver la compatibilité.
    """

    hv = float(chantier.get("heures_vendues", 0) or 0)
    hc = float(chantier.get("heures_consommees", 0) or 0)

    heures_restantes = hv - hc
    derive_heures = hc - hv
    derive_pourcentage = (derive_heures / hv * 100) if hv else 0.0
    reste_a_faire = heures_restantes

    return {
        "heures_vendues": hv,
        "heures_consommees": hc,
        "heures_restantes": heures_restantes,
        "reste_a_faire": reste_a_faire,
        "derive_heures": derive_heures,
        "derive_pourcentage": derive_pourcentage,
    }


def projection_fin_chantier(chantier: Dict[str, object]) -> Dict[str, float]:
    """Projection simple de dérive finale selon la consommation actuelle et l'avancement."""

    metrics = compute_heures_metrics(chantier)
    avancement = float(chantier.get("avancement", 0) or 0)
    ratio = avancement / 100 if avancement else 0
    projected_total = metrics["heures_consommees"] / ratio if ratio else metrics["heures_consommees"]
    derive_final = projected_total - metrics["heures_vendues"]
    derive_pct_final = (derive_final / metrics["heures_vendues"] * 100) if metrics["heures_vendues"] else 0.0

    metrics.update(
        {
            "projection_heures_totales": projected_total,
            "projection_derive_heures": derive_final,
            "projection_derive_pourcentage": derive_pct_final,
        }
    )
    return metrics


def compute_budget_materiel(chantier: Dict[str, object]) -> Dict[str, float]:
    """Calcule les dérives de budget matériel (prévu vs engagé)."""

    prevu = float(chantier.get("budget_materiel_prevu", 0) or 0)
    engage = float(chantier.get("budget_materiel_engage", 0) or 0)
    restant = prevu - engage
    derive = engage - prevu
    derive_pct = (derive / prevu * 100) if prevu else 0.0

    return {
        "budget_materiel_prevu": prevu,
        "budget_materiel_engage": engage,
        "budget_materiel_restant": restant,
        "derive_budget_materiel": derive,
        "derive_budget_pourcentage": derive_pct,
    }


class ChantierRiskEngine:
    """Calcul de score de risque chantier."""

    def compute_risk_score(
        self,
        diagnostic: List[str] | List[dict] | str,
        risques: List[str],
        derive_pourcentage: float | None = None,
        derive_budget_pourcentage: float | None = None,
    ) -> Dict[str, object]:
        score = 0
        diag_items: List[str] = []
        if isinstance(diagnostic, str):
            diag_items = [diagnostic.lower()]
        elif isinstance(diagnostic, list):
            diag_items = [str(x).lower() for x in diagnostic]

        risk_text = " ".join(diag_items + [" ".join(risques).lower()])

        if "ordre service absent" in risk_text or "ordre de service" in risk_text:
            score += 40
        if "permis" in risk_text and "absent" in risk_text:
            score += 30
        if "retard" in risk_text or "planning" in risk_text:
            score += 20
        if "sécurité" in risk_text or "danger" in risk_text:
            score += 50

        if derive_pourcentage is not None:
            if derive_pourcentage > HEURES_DERIVE_CRITIQUE_PCT:
                score += 30
            elif derive_pourcentage > HEURES_DERIVE_ELEVE_PCT:
                score += 15

        if derive_budget_pourcentage is not None:
            if derive_budget_pourcentage > BUDGET_DERIVE_CRITIQUE_PCT:
                score += 25
            elif derive_budget_pourcentage > BUDGET_DERIVE_ELEVE_PCT:
                score += 10

        niveau = "FAIBLE"
        if score > 80:
            niveau = "CRITIQUE"
        elif score > 60:
            niveau = "ÉLEVÉ"
        elif score > 30:
            niveau = "MOYEN"

        return {"score": score, "niveau": niveau}

    def analyze(self, contexte: Dict[str, object]) -> Dict[str, object]:
        diagnostic = contexte.get("diagnostic") or contexte.get("description") or ""
        risques = contexte.get("risques") or []

        derive_pourcentage = None
        derive_budget_pourcentage = None
        if isinstance(contexte, dict):
            derive_pourcentage = contexte.get("derive_pourcentage")
            derive_budget_pourcentage = contexte.get("derive_budget_pourcentage")
            chantier_ctx = contexte.get("chantier") or contexte
            hours_present = any(k in chantier_ctx for k in ["heures_vendues", "heures_consommees"])
            if derive_pourcentage is None and hours_present:
                derive_pourcentage = compute_heures_metrics(chantier_ctx).get("derive_pourcentage")
            budget_present = any(k in chantier_ctx for k in ["budget_materiel_prevu", "budget_materiel_engage"])
            if derive_budget_pourcentage is None and budget_present:
                derive_budget_pourcentage = compute_budget_materiel(chantier_ctx).get("derive_budget_pourcentage")

        score_data = self.compute_risk_score(
            diagnostic if isinstance(diagnostic, list) else [diagnostic],
            risques,
            derive_pourcentage=derive_pourcentage,
            derive_budget_pourcentage=derive_budget_pourcentage,
        )
        return {
            "diagnostic": diagnostic,
            "risques": risques,
            "score": score_data,
            "derive_pourcentage": derive_pourcentage,
            "derive_budget_pourcentage": derive_budget_pourcentage,
        }
