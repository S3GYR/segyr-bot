from __future__ import annotations

import pytest

from modules.finance.cashflow import compute_cashflow
from tools.finance_tool import FinanceTool
from tests.conftest import FakeMemoryStore


def test_compute_cashflow_positive():
    data = compute_cashflow(
        [{"montant_ht": 100}, {"montant_ht": 50}],
        [{"montant_ht": 30}],
    )
    assert data["encaissements"] == 150
    assert data["decaissements"] == 30
    assert data["solde"] == 120


def test_compute_cashflow_negative():
    data = compute_cashflow(
        [{"montant_ht": 50}],
        [{"montant_ht": 120}],
    )
    assert data["solde"] == -70
    assert data["decaissements"] == 120


@pytest.mark.asyncio
async def test_finance_tool_cashflow():
    store = FakeMemoryStore()
    store.add_facture(None, 100, None, None, None)
    store.add_facture(None, 200, None, None, None)
    store.update_facture(2, {"statut": "fournisseur_impayee"})

    tool = FinanceTool(store)
    result = await tool.run(action="cashflow", payload={})

    assert result["cashflow"]["encaissements"] == 100
    assert result["cashflow"]["decaissements"] == 200
    assert result["cashflow"]["solde"] == -100
