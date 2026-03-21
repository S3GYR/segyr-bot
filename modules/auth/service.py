from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException, status

from core.memory import MemoryStore
from modules.auth.utils import create_access_token, hash_password, verify_password


class AuthService:
    def __init__(self, store: MemoryStore | None = None) -> None:
        self.store = store or MemoryStore()

    def register(self, email: str, password: str, entreprise_id: str, role: str = "admin") -> Dict[str, Any]:
        existing = self.store.get_user_by_email(email)
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email déjà utilisé")
        pwd_hash = hash_password(password)
        user = self.store.add_user(email, pwd_hash, role, entreprise_id)
        token = create_access_token({"user_id": user["id"], "entreprise_id": entreprise_id})
        return {"user": user, "access_token": token}

    def login(self, email: str, password: str) -> Dict[str, Any]:
        user = self.store.get_user_by_email(email)
        if not user or not verify_password(password, user.get("password_hash", "")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants invalides")
        token = create_access_token({"user_id": user["id"], "entreprise_id": user["entreprise_id"]})
        return {"user": user, "access_token": token}
