from __future__ import annotations

from typing import Any, Dict, List

from loguru import logger

from modules.notifications.service import send_notification


class ActionEngine:
    """Déclenche des actions automatiques en fonction de l'analyse."""

    async def execute_actions(self, context: Dict[str, Any], analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        registry = context.get("registry")
        store = context.get("store")
        message: str = context.get("message", "") or ""
        intents: List[Dict[str, Any]] = analysis.get("intents", []) or []
        decision: Dict[str, Any] = analysis.get("decision", {}) or {}
        cashflow: Dict[str, Any] = analysis.get("cashflow", {}) or {}
        actions: List[Dict[str, Any]] = []

        has_finance = any(r.get("intent") == "finance" for r in intents)
        chantier_risk = decision.get("chantier_risk", {}) or {}
        risk_score = chantier_risk.get("score", 0)
        derive_pourcentage = chantier_risk.get("derive_pourcentage") or analysis.get("derive_pourcentage") or 0
        derive_budget_pourcentage = chantier_risk.get("derive_budget_pourcentage") or analysis.get("derive_budget_pourcentage") or 0

        # Relance factures impayées
        if has_finance and registry:
            try:
                relances = await registry.execute("invoice_tool", action="relance", payload={})
                actions.append({"type": "finance_relance", "output": relances})
            except Exception as exc:  # pragma: no cover - runtime safety
                logger.warning("Relance automatique échouée: %s", exc)

        # Alertes chantier critiques
        if risk_score and risk_score > 80:
            actions.append({"type": "chantier_alerte", "message": "Risque chantier critique détecté"})
            try:
                send_notification("chantier", "Risque chantier critique détecté")
            except Exception:
                logger.debug("Notification chantier critique échouée")
        elif risk_score and risk_score > 60:
            actions.append({"type": "chantier_surveillance", "message": "Risque chantier élevé"})

        # Retard planning => plan d'action
        if "retard" in message.lower() or "planning" in message.lower():
            actions.append(
                {
                    "type": "planning_plan_action",
                    "steps": [
                        "Rebaseliner les jalons critiques",
                        "Notifier les équipes terrain",
                        "Confirmer les ressources et approvisionnements",
                    ],
                }
            )

        # Dérive heures production
        if derive_pourcentage > 20:
            actions.append({"type": "alerte_derivation_heures", "message": "Dérive critique des heures"})
            try:
                send_notification("chantier", "Dérive critique des heures détectée")
            except Exception:
                logger.debug("Notification dérive heures échouée")
        elif derive_pourcentage > 10:
            actions.append({"type": "alerte_derivation_heures", "message": "Dérive heures à surveiller"})

        # Dérive budget matériel
        if derive_budget_pourcentage > 20:
            actions.append({"type": "alerte_budget_materiel", "message": "Dérive critique budget matériel"})
            try:
                send_notification("chantier", "Budget matériel dépassement critique")
            except Exception:
                logger.debug("Notification budget matériel échouée")
        elif derive_budget_pourcentage > 10:
            actions.append({"type": "alerte_budget_materiel", "message": "Dérive budget matériel à surveiller"})

        # Trésorerie négative imminente
        if cashflow and cashflow.get("solde") is not None and float(cashflow.get("solde")) < 0:
            actions.append(
                {
                    "type": "alerte_tresorerie",
                    "niveau": "critique",
                    "message": "Trésorerie négative imminente",
                    "actions_suggerees": [
                        "Relancer clients en retard",
                        "Demander acompte",
                        "Négocier délais fournisseurs",
                    ],
                }
            )
            try:
                send_notification("finance", "Trésorerie négative imminente")
            except Exception:
                logger.debug("Notification trésorerie échouée")

        if store and (risk_score or actions):
            try:
                # Historiser dernier score global pour monitoring
                store.add_decision(context.get("user_id", "default"), intents, decision, actions)
            except Exception as exc:  # pragma: no cover - runtime safety
                logger.debug("Decision history save failed: %s", exc)

        return actions
