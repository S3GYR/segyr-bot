"""Entrée FastAPI pour SEGYR-BOT.

Expose endpoints de chat, clients, factures et dashboard.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.routes.dashboard import router as dashboard_router
from api.routes.health import router as health_router
from api.routes.metrics import router as metrics_router
from api.routes.repair import router as repair_router
from config.settings import settings
from core.agent import AgentEngine
from core.logging import log_requests, logger, setup_sentry
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
app.add_middleware(GZipMiddleware, minimum_size=500)
setup_sentry()
log_requests(app)
app.include_router(dashboard_router)
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(repair_router)
logger.bind(event="api_startup", log_level="INFO").info("SEGYR-BOT API initialized")
engine = AgentEngine()


def get_engine() -> AgentEngine:
    return engine


async def require_token(x_api_token: str | None = Header(default=None, alias=settings.api_token_header)) -> None:
    if settings.api_auth_token and x_api_token != settings.api_auth_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide")


async def get_current_user_dep(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None, alias=settings.api_token_header),
    agent: AgentEngine = Depends(get_engine),
):
    if authorization:
        token = get_bearer_token(authorization)
        return get_current_user(token, agent.store)
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


@app.get("/", tags=["info"])
async def root() -> dict[str, str]:
    return {"message": "SEGYR-BOT API", "llm_provider": settings.llm_provider}


@app.post("/auth/register", response_model=TokenResponse, tags=["auth"])
async def auth_register(payload: RegisterRequest, agent: AgentEngine = Depends(get_engine)):
    service = AuthService(agent.store)
    data = service.register(payload.email, payload.password, payload.entreprise_id, payload.role)
    user = data["user"]
    return TokenResponse(access_token=data["access_token"], user_id=user["id"], entreprise_id=user["entreprise_id"])


@app.post("/auth/login", response_model=TokenResponse, tags=["auth"])
async def auth_login(payload: LoginRequest, agent: AgentEngine = Depends(get_engine)):
    service = AuthService(agent.store)
    data = service.login(payload.email, payload.password)
    user = data["user"]
    return TokenResponse(access_token=data["access_token"], user_id=user["id"], entreprise_id=user["entreprise_id"])


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(req: ChatRequest, agent: AgentEngine = Depends(get_engine), current_user=Depends(get_current_user_dep)) -> ChatResponse:
    ent_id = resolve_entreprise_id(current_user, fallback=req.entreprise_id)
    result = await agent.process(req.message, entreprise_id=ent_id)
    return ChatResponse(
        intents=result["intents"],
        decision=result["decision"],
        result=result["result"],
        actions=result.get("actions"),
        risk_score=result.get("risk_score"),
    )


@app.get("/clients", tags=["clients"])
async def list_clients(agent: AgentEngine = Depends(get_engine), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    service = ClientService(agent.store)
    clients = service.list(entreprise_id=ent_id)
    return {"clients": [c.__dict__ for c in clients]}


@app.post("/clients", tags=["clients"])
async def create_client(payload: ClientCreate, agent: AgentEngine = Depends(get_engine), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    data = payload.model_dump()
    data["entreprise_id"] = ent_id
    service = ClientService(agent.store)
    created = service.create(data)
    return {"client": created.__dict__}


@app.get("/factures", tags=["factures"])
async def list_factures(agent: AgentEngine = Depends(get_engine), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    service = InvoiceService(agent.store)
    factures = service.list(entreprise_id=ent_id)
    return {"factures": [f.__dict__ for f in factures]}


@app.post("/factures", tags=["factures"])
async def create_facture(payload: FactureCreate, agent: AgentEngine = Depends(get_engine), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    data = payload.model_dump()
    data["entreprise_id"] = ent_id
    service = InvoiceService(agent.store)
    created = service.create(data)
    return {"facture": created.__dict__}


@app.get("/chantier", tags=["chantier"])
async def list_chantiers(agent: AgentEngine = Depends(get_engine), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    service = ChantierService(agent.store)
    chantiers = service.list(entreprise_id=ent_id)
    return {"chantiers": [c.__dict__ for c in chantiers]}


@app.post("/chantier", tags=["chantier"])
async def create_chantier(payload: ChantierCreate, agent: AgentEngine = Depends(get_engine), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    data = payload.model_dump()
    data["entreprise_id"] = ent_id
    service = ChantierService(agent.store)
    created = service.create(data)
    return {"chantier": created.__dict__}


@app.get("/dashboard/data", tags=["dashboard"])
async def dashboard(agent: AgentEngine = Depends(get_engine), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    store = agent.store
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
async def cashflow(agent: AgentEngine = Depends(get_engine), current_user=Depends(get_current_user_dep)) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    store = agent.store
    factures_clients = store.get_unpaid_client_invoices(entreprise_id=ent_id)
    factures_fournisseurs = store.get_unpaid_supplier_invoices(entreprise_id=ent_id)
    return compute_cashflow(factures_clients, factures_fournisseurs)


@app.get("/fdv/history/{chantier_id}", tags=["fdv"])
async def fdv_history(
    chantier_id: str,
    agent: AgentEngine = Depends(get_engine),
    limit: int = 50,
    current_user=Depends(get_current_user_dep),
) -> dict:
    ent_id = resolve_entreprise_id(current_user)
    try:
        chantier_int_id = int(chantier_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="chantier_id invalide") from exc

    chantier = agent.store.get_project(chantier_int_id)
    if not chantier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="chantier introuvable")
    if chantier.get("entreprise_id") != ent_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé")

    history = agent.store.get_fdv_history(str(chantier_int_id), limit=limit)
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
