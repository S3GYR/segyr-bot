from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from api.main import app, engine
from tests.conftest import FakeMemoryStore


@pytest.fixture()
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/health", headers={"X-API-Token": "segyr-token"})
    assert resp.status_code == 200


def test_chat_requires_token(client):
    resp = client.post("/chat", json={"message": "salut"})
    assert resp.status_code == 401


def test_chat_with_token(client, monkeypatch):
    monkeypatch.setattr("config.settings.settings.api_auth_token", "tkn")
    engine.store = FakeMemoryStore()
    # ensure token is read from header
    resp = client.post("/chat", headers={"X-API-Token": "tkn"}, json={"message": "facture"})
    assert resp.status_code == 200
    data = resp.json()
    assert "intents" in data and "decision" in data and "result" in data
    assert data.get("actions") is not None


def test_dashboard_counts(client, monkeypatch):
    monkeypatch.setattr("config.settings.settings.api_auth_token", "tkn")
    engine.store = FakeMemoryStore()
    # seed
    engine.store.add_client("C1", score_client=55)
    engine.store.add_facture(None, 100, None, None, None)
    engine.store.add_project("P1", None, None, None, "brouillon", 0, None)
    resp = client.get("/dashboard", headers={"X-API-Token": "tkn"})
    assert resp.status_code == 200
    data = resp.json()
    assert "chantiers" in data and "factures" in data and "alertes" in data
    assert "cashflow" in data and "impayes" in data and "clients_risque" in data
    assert data["chantiers"]["total"] >= 1
    assert data["factures"]["impayees"] >= 0


def test_cashflow_endpoint(client, monkeypatch):
    monkeypatch.setattr("config.settings.settings.api_auth_token", "tkn")
    engine.store = FakeMemoryStore()
    engine.store.add_facture(None, 100, None, None, None)
    engine.store.add_facture(None, 200, None, None, None)
    engine.store.update_facture(2, {"statut": "fournisseur_impayee"})

    resp = client.get("/finance/cashflow", headers={"X-API-Token": "tkn"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["encaissements"] == 100
    assert data["decaissements"] == 200
    assert data["solde"] == -100
