from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from agents.action_engine import ActionEngine


@pytest.mark.asyncio
async def test_actions_relance_and_decision_history(fake_store):
    engine = ActionEngine()
    store = fake_store
    registry = AsyncMock()
    registry.execute = AsyncMock(return_value={"relances": ["F1"]})

    actions = await engine.execute_actions(
        {"registry": registry, "store": store, "message": "facture impayée", "user_id": "u1"},
        {"intents": [{"intent": "finance"}], "decision": {"diag": "finance"}, "risk_score": 70},
    )

    assert any(a["type"] == "finance_relance" for a in actions)
    assert len(store.decisions) >= 1
