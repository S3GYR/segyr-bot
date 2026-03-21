from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class Decision:
    diagnostic: str
    risques: List[str]
    actions: List[str]
    chantier_risk: Dict[str, object] | None = None

    def as_dict(self) -> Dict[str, List[str] | str]:
        data = {
            "diagnostic": self.diagnostic,
            "risques": self.risques,
            "actions": self.actions,
        }
        if self.chantier_risk is not None:
            data["chantier_risk"] = self.chantier_risk
        return data


class DecisionEngine:
    """Moteur décisionnel léger, avant tout appel LLM."""

    def analyze(self, message: str, intents: List[dict] | None = None) -> Decision:
        text = (message or "").lower()
        intents = intents or []
        topics = {r.get("intent") for r in intents if r.get("intent")}

        risques: List[str] = []
        actions: List[str] = []

        if "finance" in topics or any(k in text for k in ["facture", "impay", "paiement", "relance"]):
            risques.append("Retard d'encaissement ou litige client")
            actions.append("Lister les factures en retard et planifier une relance prioritaire")

        if "chantier" in topics or any(k in text for k in ["chantier", "travaux", "planning", "avance"]):
            risques.append("Dérive planning ou aléas terrain non couverts")
            actions.append("Vérifier avancement vs jalons et sécuriser ressources critiques")

        if "client" in topics or "relation" in topics or any(k in text for k in ["client", "prospect", "contact"]):
            risques.append("Insatisfaction client ou informations incomplètes")
            actions.append("Mettre à jour la fiche client et noter les engagements pris")

        if not risques:
            risques.append("Contexte partiel, informations manquantes pour arbitrer")
            actions.append("Collecter objectifs, délais, budgets et contraintes réglementaires")

        diagnostic = self._build_diagnostic(text, intents)
        return Decision(diagnostic=diagnostic, risques=risques, actions=actions)

    def _build_diagnostic(self, text: str, intents: List[dict]) -> str:
        if intents:
            top = intents[0]
            return f"Focus {top.get('intent', 'general')} / domaine {top.get('domain', 'general')} détecté"
        if "facture" in text or "paiement" in text:
            return "Orientation finance / encaissement"
        if "chantier" in text or "travaux" in text:
            return "Orientation chantier / production"
        return "Analyse exploratoire en attente de précisions"
