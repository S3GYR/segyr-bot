from __future__ import annotations

import os
import sys
import types
from datetime import date
from typing import TYPE_CHECKING, Any, Dict, List
from unittest.mock import AsyncMock

import pytest


def _install_test_stubs() -> None:
    # --- fastapi stub ---
    try:
        import fastapi  # noqa: F401
    except Exception:
        fastapi_stub = types.ModuleType("fastapi")

        class HTTPException(Exception):
            def __init__(self, status_code: int | None = None, detail: str | None = None, headers: dict | None = None):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail
                self.headers = headers or {}

        class _DummyState:
            pass

        class FastAPI:
            def __init__(self, *args, **kwargs):
                self.state = _DummyState()
                self.dependency_overrides = {}

            def _route(self, *args, **kwargs):
                def _decorator(func):
                    return func

                return _decorator

            get = post = put = patch = delete = _route

            def add_middleware(self, *args, **kwargs):
                return None

            def include_router(self, *args, **kwargs):
                return None

            def middleware(self, *args, **kwargs):
                def _decorator(func):
                    return func

                return _decorator

        class APIRouter:
            def __init__(self, *args, **kwargs):
                pass

            def _decorator(self, *args, **kwargs):
                def _wrap(func):
                    return func

                return _wrap

            get = post = put = patch = delete = _decorator

        class Request:
            pass

        def Depends(dep=None):
            return dep

        def Header(default=None, **kwargs):
            return default

        status = types.SimpleNamespace(
            HTTP_400_BAD_REQUEST=400,
            HTTP_401_UNAUTHORIZED=401,
            HTTP_403_FORBIDDEN=403,
            HTTP_404_NOT_FOUND=404,
            HTTP_429_TOO_MANY_REQUESTS=429,
        )

        fastapi_stub.HTTPException = HTTPException
        fastapi_stub.status = status
        fastapi_stub.FastAPI = FastAPI
        fastapi_stub.APIRouter = APIRouter
        fastapi_stub.Request = Request
        fastapi_stub.Depends = Depends
        fastapi_stub.Header = Header

        testclient_stub = types.ModuleType("fastapi.testclient")

        class _FastAPITestClientStub:
            __test__ = False

            def __init__(self, *args, **kwargs):
                self._reason = "fastapi non installé: tests API ignorés"

            def __enter__(self):
                pytest.skip(self._reason)

            def __exit__(self, exc_type, exc, tb):
                return False

        testclient_stub.TestClient = _FastAPITestClientStub

        middleware_stub = types.ModuleType("fastapi.middleware")
        gzip_stub = types.ModuleType("fastapi.middleware.gzip")

        class GZipMiddleware:
            def __init__(self, *args, **kwargs):
                pass

        gzip_stub.GZipMiddleware = GZipMiddleware

        responses_stub = types.ModuleType("fastapi.responses")

        class FileResponse:
            def __init__(self, *args, **kwargs):
                pass

        class PlainTextResponse:
            def __init__(self, content: str = "", status_code: int = 200, headers: dict | None = None):
                self.content = content
                self.status_code = status_code
                self.headers = headers or {}

        responses_stub.FileResponse = FileResponse
        responses_stub.PlainTextResponse = PlainTextResponse

        sys.modules.setdefault("fastapi", fastapi_stub)
        sys.modules.setdefault("fastapi.testclient", testclient_stub)
        sys.modules.setdefault("fastapi.middleware", middleware_stub)
        sys.modules.setdefault("fastapi.middleware.gzip", gzip_stub)
        sys.modules.setdefault("fastapi.responses", responses_stub)

    # --- starlette stubs for fastapi-adjacent imports ---
    try:
        import starlette  # noqa: F401
    except Exception:
        starlette_stub = types.ModuleType("starlette")
        middleware_stub = types.ModuleType("starlette.middleware")
        trustedhost_stub = types.ModuleType("starlette.middleware.trustedhost")
        base_stub = types.ModuleType("starlette.middleware.base")
        requests_stub = types.ModuleType("starlette.requests")
        responses_stub = types.ModuleType("starlette.responses")

        class TrustedHostMiddleware:
            def __init__(self, *args, **kwargs):
                pass

        class BaseHTTPMiddleware:
            def __init__(self, *args, **kwargs):
                pass

        class Request:
            pass

        class Response:
            def __init__(self, *args, **kwargs):
                self.headers = {}
                self.status_code = kwargs.get("status_code", 200)

        class JSONResponse(Response):
            def __init__(self, content=None, status_code=200, headers=None):
                super().__init__(status_code=status_code)
                self.content = content
                self.headers = headers or {}

        trustedhost_stub.TrustedHostMiddleware = TrustedHostMiddleware
        base_stub.BaseHTTPMiddleware = BaseHTTPMiddleware
        requests_stub.Request = Request
        responses_stub.Response = Response
        responses_stub.JSONResponse = JSONResponse

        sys.modules.setdefault("starlette", starlette_stub)
        sys.modules.setdefault("starlette.middleware", middleware_stub)
        sys.modules.setdefault("starlette.middleware.trustedhost", trustedhost_stub)
        sys.modules.setdefault("starlette.middleware.base", base_stub)
        sys.modules.setdefault("starlette.requests", requests_stub)
        sys.modules.setdefault("starlette.responses", responses_stub)

    # --- loguru stub ---
    try:
        import loguru  # noqa: F401
    except Exception:
        loguru_stub = types.ModuleType("loguru")

        class _Logger:
            def bind(self, *args, **kwargs):
                return self

            def __getattr__(self, _name):
                return lambda *a, **k: None

        loguru_stub.logger = _Logger()
        sys.modules.setdefault("loguru", loguru_stub)

    # --- psycopg stub ---
    try:
        import psycopg  # noqa: F401
    except Exception:
        psycopg_stub = types.ModuleType("psycopg")
        rows_stub = types.ModuleType("psycopg.rows")

        def _connect(*args, **kwargs):
            raise RuntimeError("psycopg indisponible en mode test")

        rows_stub.dict_row = object()
        psycopg_stub.connect = _connect
        psycopg_stub.rows = rows_stub
        sys.modules.setdefault("psycopg", psycopg_stub)
        sys.modules.setdefault("psycopg.rows", rows_stub)

    # --- redis stub ---
    try:
        import redis  # noqa: F401
    except Exception:
        redis_stub = types.ModuleType("redis")
        redis_exceptions_stub = types.ModuleType("redis.exceptions")

        class RedisError(Exception):
            pass

        class Redis:
            @classmethod
            def from_url(cls, *args, **kwargs):
                return cls()

            def ping(self):
                return True

            def incr(self, *args, **kwargs):
                return 1

            def expire(self, *args, **kwargs):
                return True

            def ttl(self, *args, **kwargs):
                return 1

        redis_stub.Redis = Redis
        redis_stub.RedisError = RedisError
        redis_exceptions_stub.RedisError = RedisError
        sys.modules.setdefault("redis", redis_stub)
        sys.modules.setdefault("redis.exceptions", redis_exceptions_stub)

    # --- email-validator stub (used by pydantic EmailStr) ---
    try:
        import email_validator  # noqa: F401
    except Exception:
        email_validator_stub = types.ModuleType("email_validator")

        class EmailNotValidError(ValueError):
            pass

        class _ValidatedEmail:
            def __init__(self, email: str):
                normalized = (email or "").strip()
                self.normalized = normalized
                self.local_part = normalized.split("@", 1)[0] if "@" in normalized else normalized

        def validate_email(email: str, check_deliverability: bool = False):  # noqa: ARG001
            candidate = (email or "").strip()
            if "@" not in candidate or candidate.startswith("@") or candidate.endswith("@"):
                raise EmailNotValidError("invalid email")
            return _ValidatedEmail(candidate)

        email_validator_stub.EmailNotValidError = EmailNotValidError
        email_validator_stub.validate_email = validate_email
        email_validator_stub.__version__ = "2.0.0"
        sys.modules.setdefault("email_validator", email_validator_stub)

        try:
            import importlib.metadata as importlib_metadata

            _orig_version = importlib_metadata.version

            def _version(name: str):
                if name == "email-validator":
                    return "2.0.0"
                return _orig_version(name)

            importlib_metadata.version = _version
        except Exception:
            pass


_install_test_stubs()

# Ensure mandatory settings are available before app imports during test collection.
os.environ.setdefault("SEGYR_TEST_MODE", "true")
os.environ.setdefault("SEGYR_DB_PASSWORD", "test-db-password")
os.environ.setdefault("SEGYR_JWT_SECRET", "test-jwt-secret-32-characters-min")
os.environ.setdefault("SEGYR_API_AUTH_TOKEN", "test-api-auth-token")
if not str(os.environ.get("SEGYR_SMTP_PORT", "")).strip():
    os.environ["SEGYR_SMTP_PORT"] = "25"

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
