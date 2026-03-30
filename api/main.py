"""Entrée FastAPI pour SEGYR-BOT.

Expose endpoints de chat, clients, factures et dashboard.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.middleware.security import GlobalRateLimitMiddleware, SecurityHeadersMiddleware
from api.routes.dashboard import router as dashboard_router
from api.routes.health import router as health_router
from api.routes.metrics import router as metrics_router
from api.routes.repair import router as repair_router
from config.settings import settings
from core.agent.loop import AgentLoop
from core.bus.queue import MessageBus
from core.logging import log_requests, logger, setup_sentry
from core.memory import MemoryStore
from core.providers.base import GenerationSettings
from core.providers.registry import get_provider
from modules.chantier.service import ChantierService
from modules.fdv.service import FDVService
from modules.clients.service import ClientService
from modules.factures.service import InvoiceService
from modules.finance.cashflow import compute_cashflow
from modules.auth.service import AuthService
from modules.auth.schema import LoginRequest, RegisterRequest, TokenResponse
from modules.auth.utils import get_bearer_token, get_current_user
from modules.copilot.engine import generate_chantier_insights
from modules.scoring.company_score import compute_company_score

BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
API_FALLBACK_PREFIXES = {
    "health",
    "repair",
    "metrics",
    "auth",
    "chat",
    "clients",
    "factures",
    "chantier",
    "finance",
    "fdv",
}


class AppRuntime:
    """Unified runtime for API mode (AgentLoop + LiteLLM provider + shared store)."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.bus = MessageBus()
        self.provider = get_provider(
            model=settings.llm.model,
            provider=settings.llm.provider,
            api_key=settings.llm.api_key or None,
            api_base=settings.llm.api_base or None,
        )
        self.provider.generation = GenerationSettings(
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
        )
        self.agent_loop = AgentLoop(
            bus=self.bus,
            provider=self.provider,
            workspace=settings.workspace,
            model=self.provider.get_default_model(),
            max_iterations=settings.agent.max_iterations,
            context_window_tokens=settings.llm.context_window_tokens,
            exec_timeout=settings.agent.exec_timeout,
            restrict_to_workspace=settings.agent.restrict_to_workspace,
        )

    async def run_chat(self, message: str, *, session_key: str, chat_id: str, channel: str = "api") -> str:
        return await self.agent_loop.process_direct(
            content=message,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
        )


class ChatRequest(BaseModel):
    message: str
    entreprise_id: Optional[str] = None  # legacy override; prefer JWT


class ChatResponse(BaseModel):
    intents: list[dict]
    decision: dict
    result: dict
    actions: Optional[list] = None
    risk_score: Optional[int] = None


class ClientCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


class FactureCreate(BaseModel):
    client_id: Optional[int] = None
    montant_ht: float = Field(default=0, ge=0)
    due_date: Optional[date] = None
    reference: Optional[str] = None
    notes: Optional[str] = None


class ChantierCreate(BaseModel):
    titre: str
    client_id: Optional[int] = None
    echeance: Optional[date] = None
    statut: Optional[str] = None
    avancement: float = Field(default=0, ge=0)
    notes: Optional[str] = None


app = FastAPI(title="SEGYR-BOT", version="0.2.0", debug=settings.debug)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.api_trusted_hosts)
app.add_middleware(GlobalRateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=500)
setup_sentry()
log_requests(app)
app.include_router(dashboard_router)
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(repair_router)
logger.bind(event="api_startup", log_level="INFO").info("SEGYR-BOT API initialized")
runtime = AppRuntime()
engine = runtime  # backward compatibility for tests/legacy imports


def get_runtime() -> AppRuntime:
    return runtime


async def get_current_user_dep(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None, alias=settings.api_token_header),
    app_runtime: AppRuntime = Depends(get_runtime),
):
    if authorization:
        token = get_bearer_token(authorization)
        return get_current_user(token, app_runtime.store)
    if settings.api_auth_token and x_api_token == settings.api_auth_token:
        return {"id": "system", "role": "system", "entreprise_id": None}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise")


def resolve_entreprise_id(current_user: dict, fallback: str | None = None) -> str | None:
    ent_id = current_user.get("entreprise_id")
    if ent_id:
        return ent_id
    if current_user.get("id") == "system":
        if fallback:
            return fallback
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="entreprise_id requis pour cet appel")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur sans entreprise_id")


def _extract_evolution_payload(payload: dict[str, Any]) -> dict[str, str] | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    message_block = data.get("message") if isinstance(data, dict) and isinstance(data.get("message"), dict) else {}
    key_block = message_block.get("key") if isinstance(message_block.get("key"), dict) else {}
    message_data = message_block.get("message") if isinstance(message_block.get("message"), dict) else {}
    extended = message_data.get("extendedTextMessage") if isinstance(message_data.get("extendedTextMessage"), dict) else {}

    text = (
        message_data.get("conversation")
        or extended.get("text")
        or (data.get("text") if isinstance(data, dict) else None)
        or payload.get("message")
        or ""
    )
    chat_id = str(
        key_block.get("remoteJid")
        or (data.get("chat_id") if isinstance(data, dict) else None)
        or payload.get("chat_id")
        or ""
    )
    sender_id = str(key_block.get("participant") or key_block.get("remoteJid") or payload.get("sender") or chat_id)

    text = str(text or "").strip()
    chat_id = chat_id.strip()
    sender_id = sender_id.strip()
    if not text or not chat_id:
        return None
    return {"text": text, "chat_id": chat_id, "sender_id": sender_id}


async def _send_evolution_reply(chat_id: str, reply: str) -> bool:
    api_base = (settings.evolution_api_base or "").rstrip("/")
    instance = (settings.evolution_instance or "").strip()
    if not api_base or not instance:
        return False

    number = chat_id.replace("@s.whatsapp.net", "")
    url = f"{api_base}/message/sendText/{instance}"
    headers = {"Content-Type": "application/json"}
    if settings.evolution_api_key:
        headers["apikey"] = settings.evolution_api_key

    payload = {
        "number": number,
        "textMessage": {"text": reply},
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        return True
    except Exception as exc:  # pragma: no cover - optional integration
        logger.warning("Evolution send failed chat_id={} err={}", chat_id, exc)
        return False


@app.get("/", tags=["info"])
async def root() -> dict[str, str]:
    return {"message": "SEGYR-BOT API", "llm_provider": settings.llm_provider}


@app.post("/auth/register", response_model=TokenResponse, tags=["auth"])
async def auth_register(payload: RegisterRequest, app_runtime: AppRuntime = Depends(get_runtime)):
    service = AuthService(app_runtime.store)
    data = service.register(payload.email, payload.password, payload.entreprise_id, payload.role)
    user = data["user"]
    return TokenResponse(access_token=data["access_token"], user_id=user["id"], entreprise_id=user["entreprise_id"])


@app.post("/auth/login", response_model=TokenResponse, tags=["auth"])
async def auth_login(payload: LoginRequest, app_runtime: AppRuntime = Depends(get_runtime)):
    service = AuthService(app_runtime.store)
    data = service.login(payload.email, payload.password)
    user = data["user"]
    return TokenResponse(access_token=data["access_token"], user_id=user["id"], entreprise_id=user["entreprise_id"])


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(req: ChatRequest, app_runtime: AppRuntime = Depends(get_runtime), current_user=Depends(get_current_user_dep)) -> ChatResponse:
    ent_id = resolve_entreprise_id(current_user, fallback=req.entreprise_id)
    user_id = str(current_user.get("id") or "api-user")
    chat_id = ent_id or user_id
    session_key = f"api:{chat_id}:{user_id}"
    reply = await app_runtime.run_chat(req.message, session_key=session_key, chat_id=chat_id, channel="api")
    return ChatResponse(
        intents=[{"intent": "chat", "domain": "general", "action": "reply", "confidence": 1.0}],
        decision={"engine": "agent_loop", "provider": "litellm", "model": app_runtime.provider.get_default_model()},
        result={"reply": reply},
        actions=[],
        risk_score=None,
    )


@app.post("/webhooks/whatsapp/evolution", tags=["webhooks"])
async def evolution_webhook(
    payload: dict[str, Any],
    app_runtime: AppRuntime = Depends(get_runtime),
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
) -> dict[str, Any]:
    if settings.evolution_webhook_secret and x_webhook_secret != settings.evolution_webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook secret invalide")

    parsed = _extract_evolution_payload(payload)
    if not parsed:
        return {"ok": True, "ignored": True}

    chat_id = parsed["chat_id"]
    text = parsed["text"]
    session_key = f"webhook:{chat_id}"
    reply = await app_runtime.run_chat(text, session_key=session_key, chat_id=chat_id, channel="webhook")
    sent = await _send_evolution_reply(chat_id, reply)
    return {"ok": True, "chat_id": chat_id, "reply": reply, "sent": sent}


@app.get("/clients", tags=["clients"])
async def list_clients(app_runtime: AppRuntime = Depends(get_runtime), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    service = ClientService(app_runtime.store)
    clients = service.list(entreprise_id=ent_id)
    return {"clients": [c.__dict__ for c in clients]}


@app.post("/clients", tags=["clients"])
async def create_client(payload: ClientCreate, app_runtime: AppRuntime = Depends(get_runtime), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    data = payload.model_dump()
    data["entreprise_id"] = ent_id
    service = ClientService(app_runtime.store)
    created = service.create(data)
    return {"client": created.__dict__}


@app.get("/factures", tags=["factures"])
async def list_factures(app_runtime: AppRuntime = Depends(get_runtime), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    service = InvoiceService(app_runtime.store)
    factures = service.list(entreprise_id=ent_id)
    return {"factures": [f.__dict__ for f in factures]}


@app.post("/factures", tags=["factures"])
async def create_facture(payload: FactureCreate, app_runtime: AppRuntime = Depends(get_runtime), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    data = payload.model_dump()
    data["entreprise_id"] = ent_id
    service = InvoiceService(app_runtime.store)
    created = service.create(data)
    return {"facture": created.__dict__}


@app.get("/chantier", tags=["chantier"])
async def list_chantiers(app_runtime: AppRuntime = Depends(get_runtime), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    service = ChantierService(app_runtime.store)
    chantiers = service.list(entreprise_id=ent_id)
    return {"chantiers": [c.__dict__ for c in chantiers]}


@app.post("/chantier", tags=["chantier"])
async def create_chantier(payload: ChantierCreate, app_runtime: AppRuntime = Depends(get_runtime), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    data = payload.model_dump()
    data["entreprise_id"] = ent_id
    service = ChantierService(app_runtime.store)
    created = service.create(data)
    return {"chantier": created.__dict__}


@app.get("/dashboard/data", tags=["dashboard"])
async def dashboard(app_runtime: AppRuntime = Depends(get_runtime), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    store = app_runtime.store
    chantier_service = ChantierService(store)
    chantiers_objs = chantier_service.list(entreprise_id=ent_id)
    chantiers = [c.__dict__ for c in chantiers_objs]
    factures = store.list_factures(entreprise_id=ent_id)
    clients = store.list_clients(entreprise_id=ent_id)
    en_risque = [c for c in chantiers if c.get("risk_score", 0) and c["risk_score"] > 60]
    impayees = [f for f in factures if f.get("statut", "") not in {"payée", "paye"} and f.get("due_date") and str(f["due_date"]) < str(date.today())]
    cashflow_data = compute_cashflow(
        store.get_unpaid_client_invoices(entreprise_id=ent_id),
        store.get_unpaid_supplier_invoices(entreprise_id=ent_id),
    )
    impayes_total = float(cashflow_data.get("impayes_total") or 0)
    clients_risque = [c for c in clients if (c.get("score_client") is not None and c.get("score_client") < 60)]
    clients_risque_sorted = sorted(clients_risque, key=lambda c: c.get("score_client") or 0)
    top_clients_risque = clients_risque_sorted[:5]
    alertes = []
    for c in en_risque:
        alertes.append({"type": "chantier_risque", "projet_id": c.get("id"), "message": "Risque chantier élevé"})
    for f in impayees:
        alertes.append({"type": "facture_impayee", "facture_id": f.get("id"), "message": "Facture impayée / en retard"})

    chantiers_detail = []
    copilot_global_actions: list[str] = []
    priorite_critique = 0
    for c in chantiers:
        insights = generate_chantier_insights(
            chantier=c,
            cashflow=cashflow_data,
            factures=[f for f in factures if f.get("chantier_id") == c.get("id")],
            clients=clients,
            entreprise_id=ent_id,
        )
        if any(p.get("niveau") == "critique" for p in insights.get("priorites", [])):
            priorite_critique += 1
        copilot_global_actions.extend(insights.get("actions_recommandees", []))
        chantiers_detail.append({
            **c,
            "copilot": {
                "priorites": insights.get("priorites", []),
                "alertes": insights.get("alertes", []),
                "actions_recommandees": insights.get("actions_recommandees", []),
                "resume": insights.get("resume", ""),
                "impact_financier_estime": insights.get("impact_financier_estime", 0.0),
            },
        })

    company_score = compute_company_score(clients=clients, chantiers=chantiers_detail, cashflow=cashflow_data)

    return {
        "chantiers": chantiers_detail,
        "clients": clients,
        "factures": factures,
        "impayes_total": impayes_total,
        "cashflow": cashflow_data,
        "clients_risque": top_clients_risque,
        "alertes": alertes,
        "synthese_chantiers": [
            {
                "id": c.get("id"),
                "titre": c.get("titre"),
                "risk_score": c.get("risk_score", 0),
                "avancement": c.get("avancement", 0),
                "statut": c.get("statut"),
                "derive_heures": c.get("derive_heures", 0),
                "derive_pourcentage": c.get("derive_pourcentage", 0),
                "derive_budget_materiel": c.get("derive_budget_materiel", 0),
                "derive_budget_pourcentage": c.get("derive_budget_pourcentage", 0),
                "marge": (c.get("fdv") or {}).get("marge"),
                "rentabilite_pct": (c.get("fdv") or {}).get("rentabilite_pct"),
                "cout_reel": (c.get("fdv") or {}).get("prix_revient"),
                "projections": c.get("projections", {}),
            } for c in chantiers_detail
        ],
        "copilot_global": {
            "priorite_critique": priorite_critique,
            "actions_urgentes": list(dict.fromkeys(copilot_global_actions)),
        },
        "company_score": company_score,
    }


@app.get("/finance/cashflow", tags=["finance"])
async def cashflow(app_runtime: AppRuntime = Depends(get_runtime), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    store = app_runtime.store
    factures_clients = store.get_unpaid_client_invoices(entreprise_id=ent_id)
    factures_fournisseurs = store.get_unpaid_supplier_invoices(entreprise_id=ent_id)
    return compute_cashflow(factures_clients, factures_fournisseurs)


@app.get("/fdv/history/{chantier_id}", tags=["fdv"])
async def fdv_history(
    chantier_id: str,
    app_runtime: AppRuntime = Depends(get_runtime),
    limit: int = 50,
    current_user=Depends(get_current_user_dep),
) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    try:
        chantier_int_id = int(chantier_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="chantier_id invalide") from exc

    chantier = app_runtime.store.get_project(chantier_int_id)
    if not chantier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="chantier introuvable")
    if chantier.get("entreprise_id") != ent_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé")

    history = app_runtime.store.get_fdv_history(str(chantier_int_id), limit=limit)
    return {"chantier_id": str(chantier_int_id), "history": history}


def _resolve_frontend_file(relative_path: str) -> Path | None:
    if not FRONTEND_DIST_DIR.exists():
        return None

    candidate = (FRONTEND_DIST_DIR / relative_path).resolve()
    try:
        candidate.relative_to(FRONTEND_DIST_DIR.resolve())
    except Exception:
        return None

    if candidate.is_file():
        return candidate
    return None


def _cache_control_for(path: Path) -> str:
    rel = path.relative_to(FRONTEND_DIST_DIR).as_posix()
    if rel == "index.html":
        return "no-cache"
    if rel.startswith("assets/"):
        return "public, max-age=31536000, immutable"
    return "public, max-age=3600"


def _serve_frontend_file(path: Path) -> FileResponse:
    headers = {"Cache-Control": _cache_control_for(path)}
    return FileResponse(path, headers=headers)


def _serve_spa_index() -> FileResponse:
    index_path = FRONTEND_DIST_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Frontend build manquant: exécuter npm run build dans frontend/",
        )
    return _serve_frontend_file(index_path)


@app.get("/dashboard", include_in_schema=False)
@app.get("/dashboard/", include_in_schema=False)
async def dashboard_spa_root() -> FileResponse:
    return _serve_spa_index()


@app.get("/dashboard/{path:path}", include_in_schema=False)
async def dashboard_spa_path(path: str) -> FileResponse:
    file_path = _resolve_frontend_file(path)
    if file_path is not None:
        return _serve_frontend_file(file_path)
    return _serve_spa_index()


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str, request: Request) -> FileResponse:
    if not full_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    first_segment = full_path.split("/", 1)[0]
    if first_segment in API_FALLBACK_PREFIXES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    file_path = _resolve_frontend_file(full_path)
    if file_path is not None:
        return _serve_frontend_file(file_path)

    accept = request.headers.get("accept", "")
    if "text/html" not in accept and "*/*" not in accept:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    return _serve_spa_index()
