from __future__ import annotations

import asyncio
from asyncio import QueueFull
import json
import logging
import hmac
import hashlib
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os
import random

import uvicorn

_bootstrap_logger = logging.getLogger("gateway_bootstrap")

try:
    from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
except Exception as e:
    import time

    _bootstrap_logger.error("FastAPI import failed: %s", e)
    while True:
        time.sleep(2)

from core.agent.loop import AgentLoop
from core.bus.events import InboundMessage, OutboundMessage
from core.bus.queue import MessageBus
from core.logging import logger, log_requests
from core.providers.base import GenerationSettings
from core.providers.registry import get_provider
from core.redis.client import redis_ping, redis_publish, redis_client
from redis import Redis
from core.utils.rate_limit import RateLimiter

try:
    from config.settings import settings
except Exception as e:
    logger.error("settings import failed: {}", e)

    class Dummy:
        workspace = "/tmp"

        ws_allowed_origins = "*"
        ws_token: str | None = None

        class llm:
            model = "none"
            provider = "none"
            api_key = None
            api_base = None
            temperature = 0.7
            max_tokens = 512
            context_window_tokens = 4096

        class agent:
            max_iterations = 1
            exec_timeout = 5
            restrict_to_workspace = False

    settings = Dummy()


def _get_settings():
    return settings


def _parse_ws_allowed_origins(raw: str | None) -> frozenset[str]:
    if raw is None:
        return frozenset({"*"})
    items = [o.strip() for o in str(raw).split(",")]
    cleaned = [o for o in items if o]
    if not cleaned:
        return frozenset({"*"})
    if "*" in cleaned:
        return frozenset({"*"})
    return frozenset(cleaned)


@dataclass(frozen=True)
class GatewayConfig:
    allowed_origins: frozenset[str]
    ws_token: str
    max_ws_connections: int
    ws_max_size: int
    ws_ping_interval: float
    pubsub_max_bytes: int
    pubsub_queue_max: int
    max_ws_per_ip: int
    max_ws_per_min_ip: int


def _load_gateway_config() -> GatewayConfig:
    cfg = _get_settings()
    origins = _parse_ws_allowed_origins(getattr(cfg, "ws_allowed_origins", "*"))
    token = (getattr(cfg, "ws_token", None) or "").strip()
    return GatewayConfig(
        allowed_origins=origins,
        ws_token=token,
        max_ws_connections=int(os.getenv("MAX_WS_CONNECTIONS", "0")),
        ws_max_size=int(os.getenv("WS_MAX_SIZE", "16777216")),
        ws_ping_interval=float(os.getenv("WS_PING_INTERVAL", "15")),
        pubsub_max_bytes=int(os.getenv("PUBSUB_MAX_BYTES", "65536")),
        pubsub_queue_max=int(os.getenv("PUBSUB_QUEUE_MAX", "1000")),
        max_ws_per_ip=int(os.getenv("MAX_WS_PER_IP", "0")),
        max_ws_per_min_ip=int(os.getenv("MAX_WS_PER_MIN_IP", "0")),
    )


def _validate_gateway_config(config: GatewayConfig) -> None:
    if not isinstance(config.allowed_origins, frozenset) or not config.allowed_origins:
        raise ValueError("WS_ALLOWED_ORIGINS invalide ou vide")
    if any(not isinstance(o, str) for o in config.allowed_origins):
        raise ValueError("WS_ALLOWED_ORIGINS doit être une collection de chaînes")
    if config.ws_max_size <= 0:
        raise ValueError("WS_MAX_SIZE doit être > 0")
    if config.ws_ping_interval <= 0:
        raise ValueError("WS_PING_INTERVAL doit être > 0")
    if config.pubsub_max_bytes <= 0:
        raise ValueError("PUBSUB_MAX_BYTES doit être > 0")
    if config.pubsub_queue_max <= 0:
        raise ValueError("PUBSUB_QUEUE_MAX doit être > 0")
    if config.max_ws_connections < 0:
        raise ValueError("MAX_WS_CONNECTIONS doit être >= 0")
    if config.max_ws_per_ip < 0 or config.max_ws_per_min_ip < 0:
        raise ValueError("MAX_WS_PER_IP et MAX_WS_PER_MIN_IP doivent être >= 0")


# ---------------------------------------------------------------------------
# Configuration globale (définie une seule fois avant usage)
# ---------------------------------------------------------------------------
_GATEWAY_CONFIG = _load_gateway_config()
_validate_gateway_config(_GATEWAY_CONFIG)

_WS_ALLOWED_ORIGINS = _GATEWAY_CONFIG.allowed_origins
_WS_TOKEN = _GATEWAY_CONFIG.ws_token
_MAX_WS_CONNECTIONS = _GATEWAY_CONFIG.max_ws_connections  # 0 = illimité
_WS_MAX_SIZE = _GATEWAY_CONFIG.ws_max_size
_WS_PING_INTERVAL = _GATEWAY_CONFIG.ws_ping_interval
_PUBSUB_MAX_BYTES = _GATEWAY_CONFIG.pubsub_max_bytes
_PUBSUB_QUEUE_MAX = _GATEWAY_CONFIG.pubsub_queue_max
_PUBSUB_STATS: dict[str, float | int] = {
    "delivered": 0,
    "last_lag_ms": 0.0,
    "dropped": 0,
    "dropped_oversize": 0,
    "published": 0,
}
_MAX_WS_PER_IP = _GATEWAY_CONFIG.max_ws_per_ip  # 0 illimité
_MAX_WS_PER_MIN_IP = _GATEWAY_CONFIG.max_ws_per_min_ip  # 0 illimité
_ip_conn: dict[str, int] = {}
_ip_recent: dict[str, list[float]] = {}
_ip_rejected: dict[str, int] = {}
_conn_counters: dict[str, int] = {"active": 0, "accepted": 0, "rejected": 0, "messages_sent": 0, "rejected_ip": 0}


def _default_channels_config_path() -> Path:
    settings = _get_settings()
    workspace_cfg = Path(settings.workspace) / "channels.json"
    if workspace_cfg.exists():
        return workspace_cfg

    # Fallback to bundled example config.
    return Path(__file__).parent / "channels" / "config.example.json"


def load_channels_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        logger.warning("Fichier de config channels introuvable: {}", config_path)
        return {}

    with open(config_path, encoding="utf-8") as fh:
        raw = json.load(fh)

    channels = raw.get("channels", raw)
    if not isinstance(channels, dict):
        raise ValueError("Configuration channels invalide: objet attendu")

    return channels


def _ensure_webhook_defaults(channels_config: dict[str, Any]) -> dict[str, Any]:
    webhook = channels_config.get("webhook")
    if not isinstance(webhook, dict):
        webhook = {}

    webhook.setdefault("enabled", True)
    webhook["host"] = "0.0.0.0"
    webhook["port"] = 8090
    webhook["route"] = "/message"
    webhook.setdefault("allowFrom", ["*"])

    channels_config["webhook"] = webhook
    return channels_config


def _extract_message(payload: dict[str, Any]) -> tuple[str, str, str, list[str]] | None:
    sender = str(payload.get("sender") or payload.get("sender_id") or "").strip()
    chat_id = str(payload.get("chat_id") or payload.get("conversation_id") or sender).strip()
    text = str(payload.get("text") or payload.get("message") or "").strip()
    media = payload.get("media") or []

    if text and chat_id:
        return sender or chat_id, chat_id, text, media if isinstance(media, list) else []

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    message_block = data.get("message") if isinstance(data, dict) and isinstance(data.get("message"), dict) else {}
    key_block = message_block.get("key") if isinstance(message_block.get("key"), dict) else {}
    message_data = message_block.get("message") if isinstance(message_block.get("message"), dict) else {}
    extended = message_data.get("extendedTextMessage") if isinstance(message_data.get("extendedTextMessage"), dict) else {}

    evo_text = str(
        message_data.get("conversation")
        or extended.get("text")
        or (data.get("text") if isinstance(data, dict) else None)
        or payload.get("message")
        or ""
    ).strip()
    evo_chat_id = str(
        key_block.get("remoteJid")
        or (data.get("chat_id") if isinstance(data, dict) else None)
        or payload.get("chat_id")
        or ""
    ).strip()
    evo_sender = str(
        key_block.get("participant")
        or key_block.get("remoteJid")
        or payload.get("sender")
        or evo_chat_id
    ).strip()

    if evo_text and evo_chat_id:
        return evo_sender or evo_chat_id, evo_chat_id, evo_text, []
    return None


class GatewayRuntime:
    def __init__(self) -> None:
        self.channels_config_path: Path | None = None
        self.started = False
        self.bus: MessageBus | None = None
        self.agent: AgentLoop | None = None
        self.agent_task: asyncio.Task | None = None
        self.outbound_task: asyncio.Task | None = None
        self.watchdog_task: asyncio.Task | None = None
        self.response_timeout_s = 20.0
        self.allow_from: set[str] = {"*"}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_lock = asyncio.Lock()
        self.runtime_ready = False
        self._runtime_state = "stopped"

    async def start(self) -> None:
        if self.started:
            return

        self.runtime_ready = False
        self._runtime_state = "starting"

        try:
            settings = _get_settings()
            workspace_path = Path(settings.workspace)
            config_path = self.channels_config_path or _default_channels_config_path()
            channels_config = _ensure_webhook_defaults(load_channels_config(config_path))
            webhook_cfg = channels_config.get("webhook") if isinstance(channels_config.get("webhook"), dict) else {}
            allow_from = webhook_cfg.get("allowFrom") or webhook_cfg.get("allow_from") or ["*"]
            self.allow_from = {str(v) for v in allow_from} if isinstance(allow_from, list) else {"*"}

            response_timeout = webhook_cfg.get("responseTimeoutS") or webhook_cfg.get("response_timeout_s") or 20.0
            try:
                self.response_timeout_s = max(float(response_timeout), 1.0)
            except Exception:
                self.response_timeout_s = 20.0

            self.bus = MessageBus(max_inbound=1000, max_outbound=1000)
            provider = get_provider(
                model=settings.llm.model,
                provider=settings.llm.provider,
                api_key=settings.llm.api_key or None,
                api_base=settings.llm.api_base or None,
            )
            self.provider = provider
            provider.generation = GenerationSettings(
                temperature=settings.llm.temperature,
                max_tokens=settings.llm.max_tokens,
            )

            self.agent = AgentLoop(
                bus=self.bus,
                provider=provider,
                workspace=workspace_path,
                model=provider.get_default_model(),
                max_iterations=settings.agent.max_iterations,
                context_window_tokens=settings.llm.context_window_tokens,
                exec_timeout=settings.agent.exec_timeout,
                restrict_to_workspace=settings.agent.restrict_to_workspace,
            )

            if hasattr(self.agent, "run"):
                self.agent_task = asyncio.create_task(self.agent.run(), name="gateway-agent-loop")
            if hasattr(self, "_dispatch_outbound"):
                self.outbound_task = asyncio.create_task(self._dispatch_outbound(), name="gateway-outbound-dispatcher")
            if hasattr(self, "_watchdog_tasks"):
                self.watchdog_task = asyncio.create_task(self._watchdog_tasks(), name="gateway-watchdog")

            self.started = True
            self.runtime_ready = True
            self._runtime_state = "ready"
            logger.info("Gateway started (FastAPI) host=0.0.0.0 port=8090")
            print("✅ Runtime started")
        except Exception as e:
            print(f"❌ Runtime failed: {e}")
            self.started = False
            self.runtime_ready = False
            self._runtime_state = "degraded"
            logger.error("Runtime start failed: {}", e)
            for task in (self.agent_task, self.outbound_task, self.watchdog_task):
                try:
                    if task and not task.done():
                        task.cancel()
                except Exception:
                    pass
            if any(t for t in (self.agent_task, self.outbound_task, self.watchdog_task) if t):
                await asyncio.gather(
                    *[t for t in (self.agent_task, self.outbound_task, self.watchdog_task) if t],
                    return_exceptions=True,
                )

    async def stop(self) -> None:
        if not self.started:
            return

        self.started = False
        self.runtime_ready = False
        self._runtime_state = "stopped"

        if self.agent is not None:
            self.agent.stop()

        tasks = [t for t in (self.agent_task, self.outbound_task, self.watchdog_task) if t is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        async with self._pending_lock:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(asyncio.CancelledError())
            self._pending.clear()

        logger.info("Gateway stopped")

    def _is_allowed(self, sender_id: str) -> bool:
        if not self.allow_from:
            return False
        if "*" in self.allow_from:
            return True

    async def _dispatch_outbound(self) -> None:
        """Boucle de consommation des messages sortants.

        - ne doit pas bloquer l'event loop
        - tolérante aux erreurs (ne crashe jamais le runtime)
        - s'arrête proprement si runtime stoppé ou tâche annulée
        - limite le spin CPU via timeout + yield explicite
        """

        if self.bus is None:
            logger.warning("Outbound dispatcher démarre sans bus: stop immédiat")
            return

        logger.info("Outbound dispatcher démarré")
        try:
            while self.started:
                # Stop rapide si runtime arrêté pendant un timeout
                if not self.started:
                    break

                try:
                    msg: OutboundMessage = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)
                except asyncio.TimeoutError:
                    await asyncio.sleep(0.05)
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("Erreur consommation outbound: {}", exc)
                    await asyncio.sleep(0.1)
                    continue

                if not self.started:
                    break

                try:
                    logger.debug(
                        "Outbound prêt channel={} chat_id={} preview= {}",
                        getattr(msg, "channel", "?"),
                        getattr(msg, "chat_id", "?"),
                        (msg.content[:160] + "…") if isinstance(getattr(msg, "content", None), str) else str(getattr(msg, "content", "")),
                    )
                    # TODO: router vers un ChannelManager si/when branché
                except Exception as exc:
                    logger.warning("Outbound dispatch log failed: {}", exc)

                # Yield pour éviter de monopoliser l'event loop
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            logger.info("Outbound dispatcher annulé")
            raise
        except Exception as exc:
            logger.error("Outbound dispatcher crash: {}", exc)
        finally:
            logger.info("Outbound dispatcher arrêté")

    async def _watchdog_tasks(self) -> None:
        """Surveille les tâches de fond et loggue les crashs sans jamais casser."""
        try:
            while self.started:
                for name, task in (
                    ("agent", self.agent_task),
                    ("outbound", self.outbound_task),
                ):
                    if task is None:
                        continue
                    if task.cancelled():
                        logger.info("Watchdog: task={} cancelled", name)
                        continue
                    if task.done():
                        try:
                            exc = task.exception()
                        except asyncio.CancelledError:
                            continue
                        except Exception as err:
                            logger.warning("Watchdog: task={} exception read failed err={}", name, err)
                            continue
                        if exc:
                            logger.error("Watchdog: task={} crashed: {}", name, exc)
                        else:
                            logger.info("Watchdog: task={} completed", name)
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.info("Watchdog annulé")
            raise
        except Exception as exc:
            logger.error("Watchdog crash: {}", exc)
        finally:
            logger.info("Watchdog arrêté")

    async def _lifespan_start(self) -> None:
        await self.start()

    async def _lifespan_shutdown(self) -> None:
        await self.stop()

async def _safe_send(ws: WebSocket, text: str) -> bool:
    if len(text.encode("utf-8")) > _WS_MAX_SIZE:
        _PUBSUB_STATS["dropped"] += 1
        return False
    await ws.send_text(text)
    return True


def _client_ip(ws: WebSocket) -> str:
    try:
        return ws.client.host or "unknown"
    except Exception:
        return "unknown"


def _prune_recent(ip: str, now: float) -> None:
    bucket = _ip_recent.setdefault(ip, [])
    cutoff = now - 60
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)


def _allow_ip(ws: WebSocket) -> bool:
    ip = _client_ip(ws)
    now = time.time()
    _prune_recent(ip, now)
    if _MAX_WS_PER_MIN_IP and len(_ip_recent[ip]) >= _MAX_WS_PER_MIN_IP:
        _ip_rejected[ip] = _ip_rejected.get(ip, 0) + 1
        _conn_counters["rejected_ip"] += 1
        logger.info("ws_reject ip={} reason=rate_per_min count={} limit={}", ip, len(_ip_recent[ip]), _MAX_WS_PER_MIN_IP)
        return False
    if _MAX_WS_PER_IP and _ip_conn.get(ip, 0) >= _MAX_WS_PER_IP:
        _ip_rejected[ip] = _ip_rejected.get(ip, 0) + 1
        _conn_counters["rejected_ip"] += 1
        logger.info("ws_reject ip={} reason=concurrent count={} limit={}", ip, _ip_conn.get(ip, 0), _MAX_WS_PER_IP)
        return False
    _ip_recent[ip].append(now)
    _ip_conn[ip] = _ip_conn.get(ip, 0) + 1
    return True

runtime = GatewayRuntime()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        await runtime.start()
    except Exception as exc:
        logger.error("runtime start failed (lifespan): {}", exc)
    try:
        yield
    finally:
        try:
            await runtime.stop()
        except Exception as exc:
            logger.error("runtime stop failed (lifespan): {}", exc)


app = FastAPI(title="SEGYR Gateway", version="1.0.0", lifespan=_lifespan)

allow_all = "*" in _WS_ALLOWED_ORIGINS
origins_list = ["*"] if allow_all else sorted(_WS_ALLOWED_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins_list,
    allow_credentials=False if allow_all else True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info(
    "CORS configured",
    extra={
        "origins": "*" if allow_all else origins_list,
        "allow_credentials": False if allow_all else True,
    },
)
logger.info(
    "Gateway config",
    extra={
        "ws_allowed_origins": "*" if allow_all else origins_list,
        "ws_token_set": bool(_WS_TOKEN),
        "ws_max_size": _WS_MAX_SIZE,
        "pubsub_queue_max": _PUBSUB_QUEUE_MAX,
        "ws_ping_interval": _WS_PING_INTERVAL,
        "max_ws_conn": _MAX_WS_CONNECTIONS,
        "max_ws_per_ip": _MAX_WS_PER_IP,
        "max_ws_per_min_ip": _MAX_WS_PER_MIN_IP,
    },
)

# Metriques HTTP (initialisées avant le middleware pour éviter KeyError/NameError)
_metrics: dict[str, Any] = {
    "requests_total": 0,
    "latencies_ms": [],
    "rejected_busy": 0,
}

def _build_pubsub_client() -> Redis:
    try:
        url = getattr(settings, "REDIS_URL", None) or "redis://localhost:6379"
        return Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
            health_check_interval=10,
        )
    except Exception as e:
        logger.warning("Redis pubsub client init failed: {}", e)
        return None

_redis_pubsub_client = _build_pubsub_client()
try:
    _rate_limiter = RateLimiter(
        max_requests=getattr(settings, "rate_limit_max_requests", 100),
        window_seconds=getattr(settings, "rate_limit_window_seconds", 60),
        prefix="segyr_rl",
    )
except Exception as e:
    logger.warning("RateLimiter init failed: {}", e)
    _rate_limiter = None

@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    _metrics["requests_total"] += 1
    _metrics["latencies_ms"].append(duration_ms)
    # keep bounded size for latencies
    if len(_metrics["latencies_ms"]) > 500:
        _metrics["latencies_ms"] = _metrics["latencies_ms"][-500:]
    return response

@app.get("/health")
async def health() -> dict[str, str]:
    # Toujours 200: ne dépend pas d'objets fragiles, encapsule toute exception.
    try:
        return {"status": "ok"}  # Chemin nominal: aucune info interne requise.
    except Exception as exc:  # Catch-all de sécurité pour éviter toute propagation.
        return {"status": "degraded", "detail": str(exc)}


@app.get("/health/advanced")
async def health_advanced() -> dict[str, str]:
    # Variante avancée (toujours 200) exposant un état runtime best-effort.
    state = "unknown"
    try:
        state = getattr(runtime, "_runtime_state", "unknown") or "unknown"  # Lecture best-effort.
        return {"status": "ok", "runtime": state}
    except Exception as exc:
        # En cas d'erreur d'accès, on reste 200 mais en mode dégradé.
        return {"status": "degraded", "detail": str(exc)}

async def publish_log(entry: dict[str, Any]) -> None:
    """Publish JSON log to Redis channel, fail-safe to logger."""
    try:
        payload = json.dumps(entry, ensure_ascii=False)
    except Exception as exc:
        logger.warning("failed to serialize log for pubsub: {}", exc)
        return
    if len(payload.encode("utf-8")) > _PUBSUB_MAX_BYTES:
        _PUBSUB_STATS["dropped_oversize"] += 1
        return
    loop = asyncio.get_running_loop()
    ok = False
    try:
        await loop.run_in_executor(None, _redis_pubsub_client.publish, _LOG_CHANNEL, payload)
        _PUBSUB_STATS["published"] += 1
        ok = True
    except Exception:
        ok = await redis_publish(_LOG_CHANNEL, payload)
        if ok:
            _PUBSUB_STATS["published"] += 1
        else:
            logger.info("log (fallback local): {}", payload)

async def _redis_check(timeout: float = 0.5) -> bool:
    try:
        return await asyncio.wait_for(redis_ping(timeout_s=timeout), timeout=timeout + 0.1)
    except Exception as e:
        logger.warning("readiness redis check failed: {}", e)
        return False

async def _llm_check(timeout: float = 0.5) -> bool:
    # lightweight probe: resolve provider and perform a cheap noop if supported
    try:
        provider = get_provider(
            model=settings.llm.model,
            provider=settings.llm.provider,
            api_key=settings.llm.api_key or None,
            api_base=settings.llm.api_base or None,
        )
        if hasattr(provider, "ping"):
            await asyncio.wait_for(provider.ping(), timeout=timeout)
        return True
    except Exception as e:
        logger.warning("readiness llm check failed: {}", e)
        return False

@app.get("/readiness")
async def readiness() -> dict[str, Any]:
    redis_ok, llm_ok = await asyncio.gather(_redis_check(), _llm_check())
    status = "ok" if redis_ok and llm_ok else "degraded"
    return {"status": status, "redis": redis_ok, "llm": llm_ok}

async def _live_metrics() -> dict[str, Any]:
    redis_ok, llm_ok = await asyncio.gather(_redis_check(), _llm_check())
    fallback_active = False
    llm_stats: dict[str, Any] = {}
    try:
        if hasattr(runtime, "provider") and hasattr(runtime.provider, "get_metrics"):
            raw = runtime.provider.get_metrics()
            if isinstance(raw, dict):
                llm_stats = raw
                fallback_active = bool(raw.get("fallbacks", 0))
    except Exception:
        fallback_active = False

    latencies = _metrics.get("latencies_ms", [])
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    llm_counts = llm_stats.get("counts", {}) if isinstance(llm_stats, dict) else {}
    llm_latencies = llm_stats.get("latencies_ms", {}) if isinstance(llm_stats, dict) else {}

    def _avg(tag: str) -> float:
        cnt = llm_counts.get(tag, 0)
        if cnt <= 0:
            return 0.0
        return llm_latencies.get(tag, 0.0) / cnt

    status = "ok" if redis_ok and llm_ok else "degraded"
    bus_in_depth = runtime.bus.inbound_size if runtime.bus else 0
    bus_in_max = runtime.bus.inbound_max if runtime.bus else 0
    rejected_ip = _conn_counters.get("rejected_ip", 0)

    return {
        "status": status,
        "global_status": status,
        "redis": redis_ok,
        "redis_status": redis_ok,
        "llm": llm_ok,
        "llm_status": llm_ok,
        "fallback": fallback_active,
        "fallback_active": fallback_active,
        "timestamp": time.time(),
        "requests_total": _metrics.get("requests_total", 0),
        "request_count": _metrics.get("requests_total", 0),
        "request_latency_ms": avg_latency,
        "latency_ms": avg_latency,
        "queue_inbound_depth": bus_in_depth,
        "queue_inbound_max": bus_in_max,
        "queue_size": bus_in_depth,
        "rejected_busy": _metrics.get("rejected_busy", 0),
        "llm_fallbacks": llm_stats.get("fallbacks", 0) if isinstance(llm_stats, dict) else 0,
        "llm_requests_total": sum(llm_counts.values()) if llm_counts else 0,
        "llm_avg_latency_ms": llm_stats.get("latency_avg_ms") or _avg("primary"),
        "llm_avg_latency_primary_ms": _avg("primary"),
        "llm_avg_latency_secondary_ms": _avg("secondary"),
        "llm_avg_latency_fast_ms": _avg("primary_fast"),
        "ip_rejected": rejected_ip,
        "pubsub_delivered": _PUBSUB_STATS.get("delivered", 0),
        "pubsub_lag_ms": _PUBSUB_STATS.get("last_lag_ms", 0.0),
        "pubsub_dropped": _PUBSUB_STATS.get("dropped", 0),
    }

async def _handle_client_msg(ws: WebSocket, timeout: float = 2.0) -> bool:
    try:
        msg = await asyncio.wait_for(ws.receive_text(), timeout=timeout)
    except asyncio.TimeoutError:
        return False
    except WebSocketDisconnect:
        raise
    except Exception:
        return False
    if isinstance(msg, str) and len(msg.encode("utf-8")) > _WS_MAX_SIZE:
        await ws.close(code=4400)
        return False
    try:
        data = json.loads(msg)
    except Exception:
        data = {}
    if isinstance(data, dict):
        if data.get("type") == "ping":
            ts = data.get("ts", time.time())
            await ws.send_text(json.dumps({"type": "pong", "ts": ts}, ensure_ascii=False))
        elif data.get("type") == "pong":
            pass
    return True

def _check_origin(ws: WebSocket) -> bool:
    if "*" in _WS_ALLOWED_ORIGINS:
        return True
    try:
        origin = ws.headers.get("origin") or ws.headers.get("Origin") or ""
    except Exception:
        origin = ""
    return origin in _WS_ALLOWED_ORIGINS

def _check_token(ws: WebSocket) -> bool:
    if not _WS_TOKEN:
        return True
    try:
        token = ws.headers.get("x-ws-token") or ws.headers.get("X-WS-Token") or ""
    except Exception:
        token = ""
    return hmac.compare_digest(token, _WS_TOKEN)

@app.websocket("/ws/metrics")
async def ws_metrics(ws: WebSocket) -> None:
    ip = _client_ip(ws)
    if not _check_origin(ws) or not _check_token(ws):
        logger.info("ws_connect_reject ip={} reason=auth_or_origin", ip)
        await ws.close(code=4403)
        return
    if not _allow_ip(ws):
        _conn_counters["rejected"] += 1
        logger.info("ws_connect_reject ip={} reason=rate_limit", ip)
        await ws.close(code=4408)
        return
    if _MAX_WS_CONNECTIONS and _conn_counters["active"] >= _MAX_WS_CONNECTIONS:
        await ws.close(code=4408)
        _conn_counters["rejected"] += 1
        _release_ip(ws)
        return
    _conn_counters["active"] += 1
    _conn_counters["accepted"] += 1
    logger.info("ws_connect_metrics ip={} active={}", ip, _conn_counters["active"])
    await ws.accept()
    last_activity = time.time()
    last_server_ping = 0.0
    try:
        while True:
            now = time.time()
            # send metrics
            payload = await _live_metrics()
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
            _conn_counters["messages_sent"] += 1

            # send server ping every 15s
            if now - last_server_ping >= _WS_PING_INTERVAL:
                last_server_ping = now
                await ws.send_text(json.dumps({"type": "server_ping", "ts": now}, ensure_ascii=False))
                _conn_counters["messages_sent"] += 1

            # read optional client message (ping/pong) with short timeout
            handled = await _handle_client_msg(ws, timeout=2)
            if handled:
                last_activity = time.time()

            # idle timeout 30s
            if time.time() - last_activity > 30:
                logger.info("ws_disconnect ip={} reason=idle", ip)
                await ws.close()
                break
    except WebSocketDisconnect:
        logger.info("ws_disconnect ip={} reason=client", ip)
        return
    except Exception as exc:
        logger.error("ws_metrics error: {}", exc)
    finally:
        try:
            await ws.close()
        except Exception:
            pass
        _conn_counters["active"] = max(0, _conn_counters["active"] - 1)
        _release_ip(ws)

@app.websocket("/ws/logs")
async def ws_logs(ws: WebSocket) -> None:
    ip = _client_ip(ws)
    if not _allow_ip(ws):
        _conn_counters["rejected"] += 1
        await ws.close(code=4408)
        return
    if _MAX_WS_CONNECTIONS and _conn_counters["active"] >= _MAX_WS_CONNECTIONS:
        await ws.close(code=4408)
        _conn_counters["rejected"] += 1
        _release_ip(ws)
        return
    _conn_counters["active"] += 1
    _conn_counters["accepted"] += 1
    await ws.accept()
    loop = asyncio.get_running_loop()
    pubsub = None
    last_activity = time.time()
    last_server_ping = 0.0
    try:
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        await loop.run_in_executor(None, pubsub.subscribe, _LOG_CHANNEL)
        while True:
            now = time.time()
            # server ping
            if now - last_server_ping >= _WS_PING_INTERVAL:
                last_server_ping = now
                await ws.send_text(json.dumps({"type": "server_ping", "ts": now}, ensure_ascii=False))

            # pubsub message
            msg = await loop.run_in_executor(None, pubsub.get_message, True, 0.01)
            if msg and msg.get("type") == "message":
                data = msg.get("data")
                if data is not None:
                    try:
                        text = data if isinstance(data, str) else data.decode("utf-8")
                        await ws.send_text(text)
                        last_activity = time.time()
                        _PUBSUB_STATS["delivered"] += 1
                        _conn_counters["messages_sent"] += 1
                        try:
                            parsed = json.loads(text)
                            ts_val = parsed.get("timestamp") or parsed.get("ts")
                            if ts_val:
                                lag_ms = (time.time() - float(ts_val)) * (1000 if ts_val < 1e12 else 1)
                                if lag_ms >= 0:
                                    _PUBSUB_STATS["last_lag_ms"] = lag_ms
                        except Exception:
                            pass
                    except Exception as exc:
                        logger.warning("ws_logs send failed: {}", exc)

            # idle timeout 30s
            if time.time() - last_activity > 30:
                logger.info("ws_disconnect ip={} reason=idle", ip)
                await ws.close()
                break
    except WebSocketDisconnect:
        logger.info("ws_disconnect ip={} reason=client", ip)
        return
    except Exception as exc:
        logger.error("ws_logs error: {}", exc)
    finally:
        try:
            if pubsub is not None:
                await loop.run_in_executor(None, pubsub.close)
            await ws.close()
        except Exception:
            pass
        _conn_counters["active"] = max(0, _conn_counters["active"] - 1)
        _release_ip(ws)

@app.get("/metrics")
async def metrics() -> Response:
    total = _metrics.get("requests_total", 0)
    latencies = _metrics.get("latencies_ms", [])
    count = len(latencies)
    avg = sum(latencies) / count if count else 0.0
    max_latency = max(latencies) if latencies else 0.0
    inbound_depth = runtime.bus.inbound_size if runtime.bus else 0
    outbound_depth = runtime.bus.outbound_size if runtime.bus else 0
    inbound_max = runtime.bus.inbound_max if runtime.bus else 0
    outbound_max = runtime.bus.outbound_max if runtime.bus else 0
    rejected_busy = _metrics.get("rejected_busy", 0)
    rejected_ip = _conn_counters.get("rejected_ip", 0)
    llm_stats = runtime.provider.get_metrics() if hasattr(runtime.provider, "get_metrics") else {}
    llm_counts = llm_stats.get("counts", {}) if isinstance(llm_stats, dict) else {}
    llm_fallbacks = llm_stats.get("fallbacks", 0) if isinstance(llm_stats, dict) else 0
    llm_latencies = llm_stats.get("latencies_ms", {}) if isinstance(llm_stats, dict) else {}
    llm_requests_total = sum(llm_counts.values()) if llm_counts else 0
    llm_avg_latency = 0.0
    if llm_latencies and llm_counts:
        total_latency = sum(llm_latencies.values())
        llm_avg_latency = total_latency / llm_requests_total if llm_requests_total else 0.0
    fast_calls = llm_counts.get("primary_fast", 0)
    primary_calls = llm_counts.get("primary", 0)
    secondary_calls = llm_counts.get("secondary", 0)
    def _avg(tag: str) -> float:
        cnt = llm_counts.get(tag, 0)
        if cnt <= 0:
            return 0.0
        return llm_latencies.get(tag, 0.0) / cnt
    avg_primary = _avg("primary")
    avg_secondary = _avg("secondary")
    avg_fast = _avg("primary_fast")
    lines = [
        "# HELP segyr_requests_total Total HTTP requests",
        "# TYPE segyr_requests_total counter",
        f"segyr_requests_total {total}",
        "# HELP segyr_request_latency_ms Average request latency in ms (rolling)",
        "# TYPE segyr_request_latency_ms gauge",
        f"segyr_request_latency_ms {avg:.2f}",
        "# HELP segyr_request_latency_max_ms Max request latency in ms (rolling)",
        "# TYPE segyr_request_latency_max_ms gauge",
        f"segyr_request_latency_max_ms {max_latency:.2f}",
        "# HELP segyr_queue_inbound_depth Current inbound queue depth",
        "# TYPE segyr_queue_inbound_depth gauge",
        f"segyr_queue_inbound_depth {inbound_depth}",
        "# HELP segyr_queue_outbound_depth Current outbound queue depth",
        "# TYPE segyr_queue_outbound_depth gauge",
        f"segyr_queue_outbound_depth {outbound_depth}",
        "# HELP segyr_queue_inbound_max Inbound queue max size",
        "# TYPE segyr_queue_inbound_max gauge",
        f"segyr_queue_inbound_max {inbound_max}",
        "# HELP segyr_queue_outbound_max Outbound queue max size",
        "# TYPE segyr_queue_outbound_max gauge",
        f"segyr_queue_outbound_max {outbound_max}",
        "# HELP segyr_requests_rejected_busy Requests rejected due to backpressure",
        "# TYPE segyr_requests_rejected_busy counter",
        f"segyr_requests_rejected_busy {rejected_busy}",
        "# HELP segyr_llm_requests_total Total LLM requests (router)",
        "# TYPE segyr_llm_requests_total counter",
        f"segyr_llm_requests_total {llm_requests_total}",
        "# HELP segyr_llm_fallback_total LLM fallback count",
        "# TYPE segyr_llm_fallback_total counter",
        f"segyr_llm_fallback_total {llm_fallbacks}",
        "# HELP segyr_llm_primary_calls_total Primary LLM calls",
        "# TYPE segyr_llm_primary_calls_total counter",
        f"segyr_llm_primary_calls_total {primary_calls}",
        "# HELP segyr_llm_secondary_calls_total Secondary LLM calls",
        "# TYPE segyr_llm_secondary_calls_total counter",
        f"segyr_llm_secondary_calls_total {secondary_calls}",
        "# HELP segyr_llm_fast_calls_total Fast LLM calls",
        "# TYPE segyr_llm_fast_calls_total counter",
        f"segyr_llm_fast_calls_total {fast_calls}",
        "# HELP segyr_llm_avg_latency_ms Average LLM latency (ms)",
        "# TYPE segyr_llm_avg_latency_ms gauge",
        f"segyr_llm_avg_latency_ms {llm_avg_latency:.2f}",
        "# HELP segyr_llm_avg_latency_primary_ms Average latency primary (ms)",
        "# TYPE segyr_llm_avg_latency_primary_ms gauge",
        f"segyr_llm_avg_latency_primary_ms {avg_primary:.2f}",
        "# HELP segyr_llm_avg_latency_secondary_ms Average latency secondary (ms)",
        "# TYPE segyr_llm_avg_latency_secondary_ms gauge",
        f"segyr_llm_avg_latency_secondary_ms {avg_secondary:.2f}",
        "# HELP segyr_llm_avg_latency_fast_ms Average latency fast (ms)",
        "# TYPE segyr_llm_avg_latency_fast_ms gauge",
        f"segyr_llm_avg_latency_fast_ms {avg_fast:.2f}",
        "# HELP segyr_ws_active Active WebSocket connections",
        "# TYPE segyr_ws_active gauge",
        f"segyr_ws_active {_conn_counters['active']}",
        "# HELP segyr_ws_accepted_total Accepted WebSocket connections",
        "# TYPE segyr_ws_accepted_total counter",
        f"segyr_ws_accepted_total {_conn_counters['accepted']}",
        "# HELP segyr_ws_rejected_total Rejected WebSocket connections",
        "# TYPE segyr_ws_rejected_total counter",
        f"segyr_ws_rejected_total {_conn_counters['rejected']}",
        "# HELP segyr_ws_messages_sent_total WebSocket messages sent",
        "# TYPE segyr_ws_messages_sent_total counter",
        f"segyr_ws_messages_sent_total {_conn_counters['messages_sent']}",
        "# HELP segyr_pubsub_published_total Pubsub messages published",
        "# TYPE segyr_pubsub_published_total counter",
        f"segyr_pubsub_published_total {_PUBSUB_STATS['published']}",
        "# HELP segyr_pubsub_delivered_total Pubsub messages delivered",
        "# TYPE segyr_pubsub_delivered_total counter",
        f"segyr_pubsub_delivered_total {_PUBSUB_STATS['delivered']}",
        "# HELP segyr_pubsub_lag_ms Last pubsub lag in ms",
        "# TYPE segyr_pubsub_lag_ms gauge",
        f"segyr_pubsub_lag_ms {_PUBSUB_STATS['last_lag_ms']:.2f}",
        "# HELP segyr_pubsub_dropped_oversize_total Pubsub messages dropped for size",
        "# TYPE segyr_pubsub_dropped_oversize_total counter",
        f"segyr_pubsub_dropped_oversize_total {_PUBSUB_STATS['dropped_oversize']}",
    ]
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.post("/message")
async def message(request: Request) -> dict[str, Any]:
    body = await request.body()
    if len(body) > 10_000:
        raise HTTPException(status_code=413, detail="payload too large")

    secret = settings.webhook_secret
    if secret:
        signature = request.headers.get("X-Signature", "")
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, digest):
            logger.warning("webhook hmac invalid")
            raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json payload")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be object")

    text = str(payload.get("text") or payload.get("message") or "").strip()
    chat_id = str(payload.get("chat_id") or payload.get("conversation_id") or "").strip()
    if not text or not chat_id:
        raise HTTPException(status_code=400, detail="missing text or chat_id")

    # Rate limit per sender/chat or client IP
    sender = str(payload.get("sender") or payload.get("sender_id") or chat_id)
    identity = sender or (request.client.host if request.client else "unknown")

    # Backpressure: refuse if inbound queue is near capacity
    if runtime.bus and runtime.bus.inbound_size >= runtime.bus.inbound_max:
        _metrics["rejected_busy"] += 1
        logger.warning("backpressure: inbound queue full identity={} depth={}/{}", identity, runtime.bus.inbound_size, runtime.bus.inbound_max)
        raise HTTPException(status_code=429, detail="gateway busy")

    if _rate_limiter is not None:
        allowed = await _rate_limiter.allow(identity)
        if not allowed:
            logger.warning("rate limit hit identity={}", identity)
            raise HTTPException(status_code=429, detail="rate limit exceeded")

    mode_header = request.headers.get("X-LLM-Mode")
    mode_payload = str(payload.get("mode") or "").strip().lower()
    mode = mode_header or mode_payload or "auto"
    if mode not in {"fast", "quality", "auto"}:
        mode = "auto"

    try:
        return await runtime.handle_message({**payload, "_llm_mode": mode})
    except QueueFull:
        _metrics["rejected_busy"] += 1
        logger.warning("backpressure: queue full during publish identity={} depth={}/{}", identity, runtime.bus.inbound_size, runtime.bus.inbound_max if runtime.bus else 0)
        raise HTTPException(status_code=429, detail="gateway busy")


if __name__ == "__main__":
    logger.info("Starting FastAPI Gateway (stable mode)...")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8090,
        log_level="info",
        loop="asyncio",
        lifespan="on",
        access_log=True,
    )
