from __future__ import annotations

import os
from datetime import date
from typing import TYPE_CHECKING, Any, Dict, List
from unittest.mock import AsyncMock

import pytest

# Ensure mandatory settings are available before app imports during test collection.
os.environ.setdefault("SEGYR_TEST_MODE", "true")
os.environ.setdefault("SEGYR_DB_PASSWORD", "test-db-password")
os.environ.setdefault("SEGYR_JWT_SECRET", "test-jwt-secret-32-characters-min")
os.environ.setdefault("SEGYR_API_AUTH_TOKEN", "test-api-auth-token")

if TYPE_CHECKING:
    from core.agent import AgentEngine


class FakeMemoryStore:
    def __init__(self) -> None:
        self.clients: Dict[int, Dict[str, Any]] = {}
        self.factures: Dict[int, Dict[str, Any]] = {}
        self.projects: Dict[int, Dict[str, Any]] = {}
        self.enterprises: Dict[str, Dict[str, Any]] = {}
        self.users: Dict[str, Dict[str, Any]] = {}
        self.history: List[Dict[str, Any]] = []
        self.decisions: List[Dict[str, Any]] = []
        self._cid = 1
        self._fid = 1
        self._pid = 1

    # Generic
    def raw_query(self, sql_query: str, params: list[Any] | None = None) -> list[dict]:  # pragma: no cover - minimal
        if not sql_query.lower().strip().startswith("select"):
            raise ValueError("Seules les requêtes SELECT sont autorisées via raw_query")
        return []

    # Clients
    def add_client(self, name: str, email: str | None = None, phone: str | None = None, notes: str | None = None, score_client: int | None = None, entreprise_id: str | None = None) -> Dict[str, Any]:
        cid = self._cid
        self._cid += 1
        row = {
            "id": cid,
            "name": name,
            "email": email,
            "phone": phone,
            "notes": notes,
            "score_client": score_client if score_client is not None else 50,
            "entreprise_id": entreprise_id,
            "created_at": None,
        }
        self.clients[cid] = row
        return row

    def list_clients(self, entreprise_id: str | None = None) -> list[dict]:
        if entreprise_id:
            return [c for c in self.clients.values() if c.get("entreprise_id") == entreprise_id]
        return list(self.clients.values())

    def get_client(self, client_id: int) -> dict | None:
        return self.clients.get(client_id)

    def update_client(self, client_id: int, data: Dict[str, Any]) -> dict | None:
        row = self.clients.get(client_id)
        if not row:
            return None
        row.update(data)
        return row

    def update_client_score(self, client_id: int, score: float) -> dict | None:
        row = self.clients.get(client_id)
        if not row:
            return None
        row["score_client"] = score
        return row

    # Factures
    def add_facture(self, client_id: int | None, montant_ht: float, due_date: str | None, reference: str | None, notes: str | None, entreprise_id: str | None = None) -> Dict[str, Any]:
        fid = self._fid
        self._fid += 1
        row = {
            "id": fid,
            "client_id": client_id,
            "montant_ht": montant_ht,
            "due_date": due_date,
            "reference": reference,
            "notes": notes,
            "statut": "brouillon",
            "entreprise_id": entreprise_id,
            "created_at": None,
        }
        self.factures[fid] = row
        return row

    def list_factures(self, entreprise_id: str | None = None) -> list[dict]:
        if entreprise_id:
            return [f for f in self.factures.values() if f.get("entreprise_id") == entreprise_id]
        return list(self.factures.values())

    def list_factures_by_client(self, client_id: int, entreprise_id: str | None = None) -> list[dict]:
        return [
            f
            for f in self.factures.values()
            if f.get("client_id") == client_id
            and (entreprise_id is None or f.get("entreprise_id") == entreprise_id)
        ]

    def get_facture(self, facture_id: int) -> dict | None:
        return self.factures.get(facture_id)

    def update_facture(self, facture_id: int, data: Dict[str, Any]) -> dict | None:
        row = self.factures.get(facture_id)
        if not row:
            return None
        row.update(data)
        return row

    # Unpaid helpers
    def get_unpaid_client_invoices(self, entreprise_id: str | None = None) -> list[dict]:
        factures = self.list_factures(entreprise_id=entreprise_id)
        return [
            f
            for f in factures
            if f.get("statut") not in {"payée", "paye", "fournisseur_impayee"}
        ]

    def get_unpaid_supplier_invoices(self, entreprise_id: str | None = None) -> list[dict]:
        factures = self.list_factures(entreprise_id=entreprise_id)
        return [f for f in factures if f.get("statut") == "fournisseur_impayee"]

    # Projects
    def add_project(
        self,
        titre: str,
        client_id: int | None,
        montant_ht: float | None = None,
        echeance: str | None = None,
        statut: str = "brouillon",
        avancement: float = 0.0,
        notes: str | None = None,
        risk_score: int = 0,
        heures_vendues: float = 0.0,
        heures_consommees: float = 0.0,
        heures_restantes: float = 0.0,
        reste_a_faire: float = 0.0,
        derive_heures: float = 0.0,
        derive_pourcentage: float = 0.0,
        budget_materiel_prevu: float = 0.0,
        budget_materiel_engage: float = 0.0,
        budget_materiel_restant: float = 0.0,
        derive_budget_materiel: float = 0.0,
        derive_budget_pourcentage: float = 0.0,
    ) -> Dict[str, Any]:
        pid = self._pid
        self._pid += 1
        row = {
            "id": pid,
            "titre": titre,
            "client_id": client_id,
            "montant_ht": montant_ht,
            "echeance": echeance,
            "statut": statut,
            "avancement": avancement,
            "notes": notes,
            "risk_score": risk_score,
            "heures_vendues": heures_vendues,
            "heures_consommees": heures_consommees,
            "heures_restantes": heures_restantes,
            "reste_a_faire": reste_a_faire,
            "derive_heures": derive_heures,
            "derive_pourcentage": derive_pourcentage,
            "budget_materiel_prevu": budget_materiel_prevu,
            "budget_materiel_engage": budget_materiel_engage,
            "budget_materiel_restant": budget_materiel_restant,
            "derive_budget_materiel": derive_budget_materiel,
            "derive_budget_pourcentage": derive_budget_pourcentage,
        }
        self.projects[pid] = row
        return row

    def list_projects(self, entreprise_id: str | None = None) -> list[dict]:
        if entreprise_id:
            return [p for p in self.projects.values() if p.get("entreprise_id") == entreprise_id]
        return list(self.projects.values())

    def get_project(self, project_id: int) -> dict | None:
        return self.projects.get(project_id)

    def update_project(self, project_id: int, data: Dict[str, Any]) -> dict | None:
        row = self.projects.get(project_id)
        if not row:
            return None
        row.update(data)
        return row

    # Enterprises
    def add_enterprise(self, name: str) -> Dict[str, Any]:
        ent_id = f"ent-{len(self.enterprises)+1}"
        row = {"id": ent_id, "name": name}
        self.enterprises[ent_id] = row
        return row

    def list_enterprises(self) -> list[dict]:
        return list(self.enterprises.values())

    def get_enterprise(self, ent_id: str) -> dict | None:
        return self.enterprises.get(ent_id)

    # Users
    def add_user(self, email: str, password_hash: str, role: str, entreprise_id: str) -> Dict[str, Any]:
        user_id = f"usr-{len(self.users)+1}"
        row = {
            "id": user_id,
            "email": email,
            "password_hash": password_hash,
            "role": role,
            "entreprise_id": entreprise_id,
        }
        self.users[user_id] = row
        return row

    def get_user_by_email(self, email: str) -> dict | None:
        for u in self.users.values():
            if u.get("email") == email:
                return u
        return None

    def get_user(self, user_id: str) -> dict | None:
        return self.users.get(user_id)

    def list_users(self, entreprise_id: str | None = None) -> list[dict]:
        if entreprise_id:
            return [u for u in self.users.values() if u.get("entreprise_id") == entreprise_id]
        return list(self.users.values())

    # History
    def add_history(self, user_id: str, role: str, content: str) -> None:
        self.history.append({"user_id": user_id, "role": role, "content": content, "created_at": date.today().isoformat()})

    def get_history(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        items = [h for h in self.history if h["user_id"] == user_id]
        return items[-limit:]

    def add_decision(self, user_id: str, intents: List[Dict[str, Any]], decision: Dict[str, Any], actions: List[Dict[str, Any]] | List[str] | None = None) -> None:
        self.decisions.append({"user_id": user_id, "intents": intents, "decision": decision, "actions": actions or []})

    def get_decisions(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        items = [d for d in self.decisions if d["user_id"] == user_id]
        return items[-limit:]


@pytest.fixture()
def fake_store() -> FakeMemoryStore:
    return FakeMemoryStore()


@pytest.fixture()
def test_engine(fake_store: FakeMemoryStore) -> "AgentEngine":
    from core.agent import AgentEngine

    engine = AgentEngine(store=fake_store)
    engine.llm.chat = AsyncMock(return_value="Hello")
    return engine
