"""Configuration centralisée de SEGYR-BOT."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    """Configuration du fournisseur LLM."""
    model_config = SettingsConfigDict(env_prefix="SEGYR_LLM_", extra="ignore")

    provider: str = "litellm"
    model: str = "ollama/qwen3.5:9b"
    fallback_model: str = "ollama/qwen3.5:4b"
    secondary_provider: str | None = None
    secondary_model: str | None = None
    secondary_api_key: str | None = None
    secondary_api_base: str | None = None
    fast_model: str | None = None
    mode: Literal["fast", "quality"] = "quality"
    api_key: str = ""
    api_base: str = "http://ollama:11434"
    timeout: float = 120.0
    max_tokens: int = 700
    temperature: float = 0.15
    retry_attempts: int = 2
    context_window_tokens: int = 65_536


class DatabaseSettings(BaseSettings):
    """Configuration PostgreSQL."""
    model_config = SettingsConfigDict(env_prefix="SEGYR_DB_", extra="ignore")

    host: str = "localhost"
    port: int = 5432
    name: str = "segyrbot"
    user: str = "segyr"
    password: str = "CHANGE_ME_DB_PASSWORD"

    @property
    def url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def async_url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RedisSettings(BaseSettings):
    """Configuration Redis."""
    model_config = SettingsConfigDict(env_prefix="SEGYR_REDIS_", extra="ignore")

    host: str = "localhost"
    port: int = 6379
    db: int = 0

    @property
    def url(self) -> str:
        env_url = os.getenv("REDIS_URL") or os.getenv("SEGYR_REDIS_URL")
        if env_url:
            return env_url
        return f"redis://{self.host}:{self.port}/{self.db}"


class AgentSettings(BaseSettings):
    """Configuration de l'agent."""
    model_config = SettingsConfigDict(env_prefix="SEGYR_AGENT_", extra="ignore")

    max_iterations: int = 40
    exec_timeout: int = 60
    restrict_to_workspace: bool = False


class APISettings(BaseSettings):
    """Configuration de l'API REST."""
    model_config = SettingsConfigDict(env_prefix="SEGYR_API_", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]


class Settings(BaseSettings):
    """Configuration globale SEGYR-BOT."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "SEGYR-BOT"
    version: str = "0.1.0"
    test_mode: bool = Field(default=False, alias="SEGYR_TEST_MODE")
    debug: bool = Field(default=False, alias="SEGYR_DEBUG")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", alias="SEGYR_LOG_LEVEL"
    )
    workspace_path: Path = Field(default=Path("workspace"), alias="SEGYR_WORKSPACE")
    logs_path: Path = Field(default=Path("logs"), alias="SEGYR_LOGS_PATH")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="SEGYR_REDIS_URL")
    redis_enabled: bool = Field(default=True, alias="SEGYR_REDIS_ENABLED")
    cache_ttl: int = Field(default=300, alias="SEGYR_CACHE_TTL")
    global_rate_limit_enabled: bool = Field(default=True, alias="SEGYR_GLOBAL_RATE_LIMIT_ENABLED")
    global_rate_limit_window_seconds: int = Field(default=60, alias="SEGYR_GLOBAL_RATE_LIMIT_WINDOW_SECONDS")
    global_rate_limit_max_requests: int = Field(default=120, alias="SEGYR_GLOBAL_RATE_LIMIT_MAX_REQUESTS")
    global_rate_limit_fail_closed: bool = Field(default=False, alias="SEGYR_GLOBAL_RATE_LIMIT_FAIL_CLOSED")
    webhook_secret: str | None = Field(default=None, alias="SEGYR_WEBHOOK_SECRET")
    rate_limit_window_seconds: int = Field(default=10, alias="SEGYR_RATE_LIMIT_WINDOW")
    rate_limit_max_requests: int = Field(default=10, alias="SEGYR_RATE_LIMIT_MAX")
    api_auth_token: str | None = Field(default=None, alias="SEGYR_API_AUTH_TOKEN")
    api_token_header: str = Field(default="X-API-Token", alias="SEGYR_API_TOKEN_HEADER")
    api_trusted_hosts_raw: str = Field(
        default="localhost,127.0.0.1,api,segyr-api",
        alias="SEGYR_API_TRUSTED_HOSTS",
    )
    http_hsts_max_age: int = Field(default=63_072_000, alias="SEGYR_HTTP_HSTS_MAX_AGE")
    http_content_security_policy: str = Field(
        default=(
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        ),
        alias="SEGYR_HTTP_CSP",
    )
    http_referrer_policy: str = Field(default="strict-origin-when-cross-origin", alias="SEGYR_HTTP_REFERRER_POLICY")
    ws_allowed_origins: str = Field(default="*", alias="WS_ALLOWED_ORIGINS")
    ws_token: str | None = Field(default=None, alias="WS_TOKEN")
    jwt_secret: str = Field(default="CHANGE_ME_JWT_SECRET", alias="SEGYR_JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="SEGYR_JWT_ALGO")
    jwt_exp_minutes: int = Field(default=60, alias="SEGYR_JWT_EXP_MIN")
    auto_repair_enabled: bool = Field(default=True, alias="SEGYR_AUTO_REPAIR_ENABLED")
    auto_repair_mode: Literal["run", "dry-run", "approval_required"] = Field(
        default="run",
        alias="SEGYR_AUTO_REPAIR_MODE",
    )
    smtp_host: str | None = Field(default=None, alias="SEGYR_SMTP_HOST")
    smtp_port: int | None = Field(default=None, alias="SEGYR_SMTP_PORT")
    smtp_user: str | None = Field(default=None, alias="SEGYR_SMTP_USER")
    smtp_password: str | None = Field(default=None, alias="SEGYR_SMTP_PASSWORD")
    smtp_from: str | None = Field(default=None, alias="SEGYR_SMTP_FROM")
    telegram_bot_token: str | None = Field(default=None, alias="SEGYR_TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = Field(default=None, alias="SEGYR_TELEGRAM_CHAT_ID")
    evolution_api_base: str | None = Field(default=None, alias="SEGYR_EVOLUTION_API_BASE")
    evolution_api_key: str | None = Field(default=None, alias="SEGYR_EVOLUTION_API_KEY")
    evolution_instance: str | None = Field(default=None, alias="SEGYR_EVOLUTION_INSTANCE")
    evolution_webhook_secret: str | None = Field(default=None, alias="SEGYR_EVOLUTION_WEBHOOK_SECRET")

    @property
    def workspace(self) -> Path:
        p = self.workspace_path
        if not p.is_absolute():
            p = Path(__file__).parent.parent / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def postgres_dsn(self) -> str:
        return f"postgresql+psycopg://{self.db.user}:{self.db.password}@{self.db.host}:{self.db.port}/{self.db.name}"

    @property
    def REDIS_URL(self) -> str:
        """Compat alias for modules expecting uppercase setting names."""
        return self.redis_url

    @property
    def api_trusted_hosts(self) -> list[str]:
        raw = str(self.api_trusted_hosts_raw or "").strip()
        if not raw:
            hosts = ["localhost", "127.0.0.1"]
        else:
            hosts = [host.strip() for host in raw.split(",") if host.strip()]
        if self.test_mode and "testserver" not in hosts:
            hosts.append("testserver")
        return hosts

    def model_post_init(self, __context: dict | None) -> None:
        def _ensure(secret: str | None, name: str, mandatory: bool = True) -> None:
            if secret is None:
                if mandatory:
                    raise ValueError(f"Configuration manquante: {name}")
                return
            if str(secret).startswith("CHANGE_ME"):
                raise ValueError(f"Configuration invalide (placeholder) pour {name}")

        if self.test_mode:
            return

        _ensure(self.jwt_secret, "SEGYR_JWT_SECRET")
        _ensure(self.db.password, "SEGYR_DB_PASSWORD")
        if self.api_auth_token and len(self.api_auth_token.strip()) < 16:
            raise ValueError("Configuration invalide: SEGYR_API_AUTH_TOKEN trop court (min 16 caractères)")
        # SMTP et Telegram optionnels: valider uniquement si fournis
        _ensure(self.smtp_password, "SEGYR_SMTP_PASSWORD", mandatory=False)
        _ensure(self.telegram_bot_token, "SEGYR_TELEGRAM_BOT_TOKEN", mandatory=False)
        _ensure(self.evolution_api_key, "SEGYR_EVOLUTION_API_KEY", mandatory=False)
        _ensure(self.evolution_webhook_secret, "SEGYR_EVOLUTION_WEBHOOK_SECRET", mandatory=False)

    # Compatibilité legacy
    @property
    def llm_provider(self) -> str:
        return self.llm.provider

    @property
    def llm_model(self) -> str:
        return self.llm.model

    @property
    def llm_base_url(self) -> str:
        return self.llm.api_base

    @property
    def llm_api_key(self) -> str:
        return self.llm.api_key

    @property
    def llm_max_tokens(self) -> int:
        return self.llm.max_tokens

    @property
    def llm_timeout(self) -> float:
        return self.llm.timeout

    @property
    def llm_cache_ttl_seconds(self) -> int:
        return self.cache_ttl

    _llm: LLMSettings | None = None
    _db: DatabaseSettings | None = None
    _redis: RedisSettings | None = None
    _agent: AgentSettings | None = None
    _api: APISettings | None = None

    @property
    def llm(self) -> LLMSettings:
        if self._llm is None:
            self._llm = LLMSettings()
        return self._llm

    @property
    def db(self) -> DatabaseSettings:
        if self._db is None:
            self._db = DatabaseSettings()
        return self._db

    @property
    def redis(self) -> RedisSettings:
        if self._redis is None:
            self._redis = RedisSettings()
        return self._redis

    @property
    def agent(self) -> AgentSettings:
        if self._agent is None:
            self._agent = AgentSettings()
        return self._agent

    @property
    def api(self) -> APISettings:
        if self._api is None:
            self._api = APISettings()
        return self._api


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the global settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# Compat helper pour l'ancien import
settings = get_settings()
