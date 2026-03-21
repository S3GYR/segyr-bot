from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional

import jwt
from fastapi import HTTPException, status
from loguru import logger

try:
    import bcrypt
except ImportError:  # pragma: no cover - depends on runtime environment
    bcrypt = None  # type: ignore[assignment]

from config.settings import settings
from core.memory import MemoryStore

_FALLBACK_WARNED = False


def _warn_sha256_fallback() -> None:
    global _FALLBACK_WARNED
    if _FALLBACK_WARNED:
        return
    logger.warning(
        "bcrypt indisponible: fallback SHA256 activé (DEV uniquement, moins sûr que bcrypt)."
    )
    _FALLBACK_WARNED = True


def _sha256_hash(password: str) -> str:
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return f"sha256${digest}"


def hash_password(password: str) -> str:
    if bcrypt is not None:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    _warn_sha256_fallback()
    return _sha256_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    raw_hash = (password_hash or "").strip()
    if not raw_hash:
        return False

    if raw_hash.startswith("sha256$"):
        return _sha256_hash(password) == raw_hash

    # Backward-compat for early/plain sha256 storage without prefix.
    if len(raw_hash) == 64 and all(c in "0123456789abcdef" for c in raw_hash.lower()):
        return hashlib.sha256(password.encode("utf-8")).hexdigest() == raw_hash.lower()

    try:
        if bcrypt is None:
            _warn_sha256_fallback()
            return False
        return bcrypt.checkpw(password.encode("utf-8"), raw_hash.encode("utf-8"))
    except Exception:
        return False


def create_access_token(payload: Dict[str, Any], exp_minutes: Optional[int] = None) -> str:
    exp = int(time.time()) + 60 * (exp_minutes or settings.jwt_exp_minutes)
    to_encode = {**payload, "exp": exp}
    token = jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token


def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expiré")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide")


def get_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization manquant")
    return authorization.split(" ", 1)[1].strip()


def get_current_user(token: str, store: MemoryStore) -> Dict[str, Any]:
    payload = decode_token(token)
    user_id = payload.get("user_id")
    ent_id = payload.get("entreprise_id")
    if not user_id or not ent_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token incomplet")
    user = store.get_user(user_id)
    if not user or user.get("entreprise_id") != ent_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable")
    return user
