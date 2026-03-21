from __future__ import annotations

from modules.chantier.engine import ChantierRiskEngine


def test_compute_risk_score_levels():
    engine = ChantierRiskEngine()
    res = engine.compute_risk_score(["ordre service absent", "permis absent", "retard planning", "problème sécurité"], ["danger sécurité"])
    assert res["score"] >= 40 + 30 + 20 + 50
    assert res["niveau"] in {"ÉLEVÉ", "CRITIQUE"}
