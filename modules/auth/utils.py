from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Any, Dict, Optional

import jwt
from fastapi import HTTPException, status

try:
    import bcrypt
except ImportError:  # pragma: no cover - depends on runtime environment
    bcrypt = None  # type: ignore[assignment]


def _is_test_mode() -> bool:
    return str(os.getenv("SEGYR_TEST_MODE", "")).strip().lower() in {"1", "true", "yes", "on"}


class _TestModeBcryptFallback:
    """Minimal password backend used only for CI/tests when bcrypt is unavailable."""

    _prefix = "$2t$"

    @staticmethod
    def gensalt() -> bytes:
        return os.urandom(16)

    @classmethod
    def hashpw(cls, password: bytes, salt: bytes) -> bytes:
        digest = hashlib.pbkdf2_hmac("sha256", password, salt, 120_000)
        salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
        digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return f"{cls._prefix}{salt_b64}${digest_b64}".encode("utf-8")

    @classmethod
    def checkpw(cls, password: bytes, hashed: bytes) -> bool:
        raw = hashed.decode("utf-8")
        if not raw.startswith(cls._prefix):
            return False
        try:
            encoded = raw[len(cls._prefix) :]
            salt_raw, digest_raw = encoded.split("$", 1)
            salt = base64.urlsafe_b64decode(f"{salt_raw}==")
            expected = base64.urlsafe_b64decode(f"{digest_raw}==")
        except Exception:
            return False

        probe = hashlib.pbkdf2_hmac("sha256", password, salt, 120_000)
        return hmac.compare_digest(probe, expected)


if bcrypt is None and _is_test_mode():  # pragma: no cover - depends on runtime env
    bcrypt = _TestModeBcryptFallback()  # type: ignore[assignment]

if bcrypt is None:  # pragma: no cover - fail fast in non-test runtime
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
