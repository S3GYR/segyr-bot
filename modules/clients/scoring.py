from __future__ import annotations

from typing import Dict


def compute_client_score(client_data: Dict[str, object]) -> Dict[str, object]:
    score = 100.0

    factures_retard = client_data.get("factures_retard", 0) or 0
    delai_moyen = client_data.get("delai_moyen") or 0
    montant_impaye = client_data.get("montant_impaye") or 0
    nb_relances = client_data.get("nb_relances", 0) or 0

    if factures_retard:
        score -= 20
    if delai_moyen and delai_moyen > 45:
        score -= 15
    if montant_impaye and montant_impaye > 10000:
        score -= 25
    if nb_relances and nb_relances > 3:
        score -= 10

    score = max(0.0, min(100.0, score))

    niveau = "fiable"
    if score < 40:
        niveau = "dangereux"
    elif score < 60:
        niveau = "risqué"
    elif score < 75:
        niveau = "correct"

    return {"score": score, "niveau": niveau}
