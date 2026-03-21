from __future__ import annotations

HEURES_DERIVE_ELEVE_PCT = 10.0
HEURES_DERIVE_CRITIQUE_PCT = 20.0
BUDGET_DERIVE_ELEVE_PCT = 10.0
BUDGET_DERIVE_CRITIQUE_PCT = 20.0


def _to_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def classify_heures_derive(derive_pourcentage: object) -> str:
    derive_pct = _to_float(derive_pourcentage)
    if derive_pct > HEURES_DERIVE_CRITIQUE_PCT:
        return "critique"
    if derive_pct > HEURES_DERIVE_ELEVE_PCT:
        return "eleve"
    return "normal"


def classify_budget_derive(derive_budget_pourcentage: object) -> str:
    derive_pct = _to_float(derive_budget_pourcentage)
    if derive_pct > BUDGET_DERIVE_CRITIQUE_PCT:
        return "critique"
    if derive_pct > BUDGET_DERIVE_ELEVE_PCT:
        return "eleve"
    return "normal"
