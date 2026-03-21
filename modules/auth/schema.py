from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    entreprise_id: str
    role: str = Field(default="admin")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    entreprise_id: str


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    role: str
    entreprise_id: str
