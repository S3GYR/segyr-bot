from __future__ import annotations

import time
from typing import Any, Dict, Optional

import jwt
from fastapi import HTTPException, status

try:
    import bcrypt
except ImportError:  # pragma: no cover - depends on runtime environment
    bcrypt = None  # type: ignore[assignment]

if bcrypt is None:  # pragma: no cover - fail fast in broken runtime
    raise RuntimeError("bcrypt est obligatoire et indisponible dans cet environnement")

from config.settings import settings
from core.memory import MemoryStore

def _require_bcrypt() -> Any:
    if bcrypt is None:
        raise RuntimeError("bcrypt est obligatoire et indisponible dans cet environnement")
    return bcrypt


def hash_password(password: str) -> str:
    bcrypt_lib = _require_bcrypt()
    return bcrypt_lib.hashpw(password.encode("utf-8"), bcrypt_lib.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    bcrypt_lib = _require_bcrypt()
    raw_hash = (password_hash or "").strip()
    if not raw_hash:
        return False

    if not raw_hash.startswith("$2"):
        return False

    try:
        return bcrypt_lib.checkpw(password.encode("utf-8"), raw_hash.encode("utf-8"))
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
