from __future__ import annotations

import pytest

from agents.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_intent_detection():
    orchestrator = Orchestrator()
    route = await orchestrator.route("facture en retard sur chantier")
    assert route["domain"] == "finance"
    assert route["action"] == "read"
    assert "system_hint" in route
