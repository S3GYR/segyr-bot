import pytest
from fastapi.testclient import TestClient

from segyr_bot.gateway import app


def test_health_returns_200():
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200


def test_health_advanced_returns_200():
    with TestClient(app) as client:
        resp = client.get("/health/advanced")
        assert resp.status_code == 200
        assert resp.json().get("status") in {"ok", "degraded"}
