from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from loguru import logger

from agents.action_engine import ActionEngine
from agents.decision_engine import DecisionEngine
from agents.orchestrator import Orchestrator
from config.settings import settings
from core.llm import LLMClient, LLMClientError
from core.memory import MemoryStore
from core.tools import ToolRegistry
from core.system_prompt import SYSTEM_PROMPT
from modules.chantier.engine import ChantierRiskEngine
from modules.clients.service import ClientService
from modules.factures.service import InvoiceService
from modules.finance.cashflow import compute_cashflow
from tools.client_tool import ClientTool
from tools.finance_tool import FinanceTool
from tools.invoice_tool import InvoiceTool
from tools.postgres_tool import PostgresTool


class AgentEngine:
    """Orchestration minimale : route l’intention et exécute un tool adapté."""

    def __init__(self, workspace: Path | None = None, store: MemoryStore | None = None) -> None:
        self.workspace = workspace or settings.workspace_path
        self.workspace.mkdir(parents=True, exist_ok=True)
        settings.logs_path.mkdir(parents=True, exist_ok=True)

        self.store = store or MemoryStore()
        self.llm = LLMClient()
        self.registry = ToolRegistry()
        self.orchestrator = Orchestrator()
        self.decision_engine = DecisionEngine()
        self.risk_engine = ChantierRiskEngine()
        self.action_engine = ActionEngine()
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        client_service = ClientService(self.store)
        invoice_service = InvoiceService(self.store)
        self.registry.register(PostgresTool(self.store))
        self.registry.register(ClientTool(client_service))
        self.registry.register(InvoiceTool(invoice_service))
        self.registry.register(FinanceTool(self.store))

    async def process(self, message: str, user_id: str | None = "default", entreprise_id: str | None = None) -> Dict[str, Any]:
        # Routage + intent
        route_ctx = await self.orchestrator.route(message, context={"entreprise_id": entreprise_id})
        intent_obj = route_ctx.get("intent")
        intents = [
            {
                "intent": route_ctx.get("domain"),
                "domain": route_ctx.get("domain"),
                "action": route_ctx.get("action"),
                "entities": route_ctx.get("entities"),
                "confidence": getattr(intent_obj, "confidence", None),
            }
        ]

        # Analyse initiale
        decision = self.decision_engine.analyze(message, intents)
        chantier_risk = None
        if "chantier" in (decision.diagnostic or "").lower() or any("chantier" in r for r in decision.risques):
            chantier_risk = self.risk_engine.analyze({"diagnostic": [decision.diagnostic], "risques": decision.risques})
        risk_score = chantier_risk.get("score", 0) if chantier_risk else None

        if chantier_risk:
            decision_data = decision.as_dict()
            decision_data["chantier_risk"] = chantier_risk
            decision = type(decision)(**decision_data)  # rebuild dataclass-like

        # Historiser la requête utilisateur
        try:
            self.store.add_history(user_id or "default", "user", message)
        except Exception as exc:  # pragma: no cover - log only
            logger.debug("History store failed: %s", exc)

        tool_name = route_ctx.get("tool")
        action = route_ctx.get("action") or "analyze"
        payload = {"message": message, "intents": intents, "decision": decision.as_dict(), "risk_score": risk_score}

        result: Any = None
        if tool_name:
            try:
                result = await self.registry.execute(tool_name, action=action, payload=payload)
            except Exception as exc:  # pragma: no cover - runtime safety
                logger.warning("Tool %s a échoué: %s", tool_name, exc)

        if result is None:
            history_msgs = []
            try:
                history = self.store.get_history(user_id or "default", limit=10)
                history_msgs = [{"role": h["role"], "content": h["content"]} for h in history]
            except Exception as exc:  # pragma: no cover - log only
                logger.debug("History load failed: %s", exc)

            messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history_msgs, {"role": "user", "content": message}]
            try:
                content = await self.llm.chat(messages)
                result = {"reply": content, "decision": decision.as_dict()}
            except LLMClientError as exc:
                llm_error = dict(exc.payload)
                logger.warning("LLM degraded response: %s", llm_error.get("error"))
                result = {
                    "error": llm_error.get("error", "Erreur LLM"),
                    "fallback_used": bool(llm_error.get("fallback_used", False)),
                    "provider": llm_error.get("provider", settings.llm_provider),
                    "model": llm_error.get("model", settings.llm_model),
                    "fallback_model": llm_error.get("fallback_model", settings.llm.fallback_model),
                }

        # Calcul cashflow pour enrichir la réponse et les actions
        cashflow_data = compute_cashflow(
            self.store.get_unpaid_client_invoices(entreprise_id=entreprise_id),
            self.store.get_unpaid_supplier_invoices(entreprise_id=entreprise_id),
        )

        enriched_result: Dict[str, Any]
        if isinstance(result, dict):
            enriched_result = {**result}
            finance_block = enriched_result.get("finance") or {}
            finance_block["cashflow"] = cashflow_data
            enriched_result["finance"] = finance_block
        else:
            enriched_result = {"result": result, "finance": {"cashflow": cashflow_data}}

        # Actions automatiques
        actions = []
        try:
            actions = await self.action_engine.execute_actions(
                {"registry": self.registry, "store": self.store, "message": message, "user_id": user_id},
                {"intents": intents, "decision": decision.as_dict(), "risk_score": risk_score, "cashflow": cashflow_data},
            )
        except Exception as exc:  # pragma: no cover - runtime safety
            logger.warning("Actions automatiques échouées: %s", exc)

        try:
            self.store.add_decision(user_id or "default", intents, decision.as_dict(), actions)
        except Exception as exc:  # pragma: no cover - log only
            logger.debug("Decision history store failed: %s", exc)

        try:
            self.store.add_history(user_id or "default", "assistant", str(enriched_result))
        except Exception as exc:  # pragma: no cover - log only
            logger.debug("History store failed: %s", exc)

        return {
            "intents": intents,
            "decision": decision.as_dict(),
            "result": enriched_result,
            "risk_score": risk_score,
            "actions": actions,
        }
