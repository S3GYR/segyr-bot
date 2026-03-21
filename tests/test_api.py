from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app, engine, get_current_user_dep


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_user_override():
    app.dependency_overrides[get_current_user_dep] = lambda: {
        "id": "user-test",
        "role": "admin",
        "entreprise_id": "ent-test",
    }
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user_dep, None)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_chat_requires_token(client, fake_store):
    engine.store = fake_store
    resp = client.post("/chat", json={"message": "salut"})
    assert resp.status_code == 401


def test_chat_with_auth_override(client, fake_store, auth_user_override):
    engine.store = fake_store
    resp = client.post("/chat", json={"message": "facture"})
    assert resp.status_code == 200
    data = resp.json()
    assert "intents" in data and "decision" in data and "result" in data
    assert data.get("actions") is not None


def test_clients_endpoints(client, fake_store, auth_user_override):
    engine.store = fake_store

    created_resp = client.post(
        "/clients",
        json={"name": "ACME", "email": "acme@example.com", "phone": "+33123456789"},
    )
    assert created_resp.status_code == 200

    resp = client.get("/clients")
    assert resp.status_code == 200
    data = resp.json()
    assert "clients" in data
    assert len(data["clients"]) >= 1
    assert data["clients"][0]["name"] == "ACME"


def test_cashflow_endpoint(client, fake_store, auth_user_override):
    engine.store = fake_store
    engine.store.add_facture(None, 100, None, None, None, entreprise_id="ent-test")
    engine.store.add_facture(None, 200, None, None, None, entreprise_id="ent-test")
    engine.store.update_facture(2, {"statut": "fournisseur_impayee"})

    resp = client.get("/finance/cashflow")
    assert resp.status_code == 200
    data = resp.json()
    assert data["encaissements"] == 100
    assert data["decaissements"] == 200
    assert data["solde"] == -100
