from __future__ import annotations

import importlib
import sys
import types
import builtins

import pytest


def _ensure_jwt_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        import jwt  # noqa: F401
    except ImportError:
        class ExpiredSignatureError(Exception):
            pass

        class InvalidTokenError(Exception):
            pass

        jwt_stub = types.SimpleNamespace(
            encode=lambda payload, secret, algorithm=None: "stub-token",
            decode=lambda token, secret, algorithms=None: {},
            ExpiredSignatureError=ExpiredSignatureError,
            InvalidTokenError=InvalidTokenError,
        )
        monkeypatch.setitem(sys.modules, "jwt", jwt_stub)


@pytest.fixture()
def auth_utils(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SEGYR_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("SEGYR_DB_PASSWORD", "test-db-password")
    _ensure_jwt_stub(monkeypatch)

    from modules.auth import utils as auth_utils_module

    return importlib.reload(auth_utils_module)


def test_hash_password_uses_bcrypt_and_verify_roundtrip(auth_utils) -> None:
    if auth_utils.bcrypt is None:
        pytest.skip("bcrypt non disponible dans l'environnement")

    password = "SuperSecret!123"

    hashed = auth_utils.hash_password(password)

    assert hashed.startswith("$2")
    assert auth_utils.verify_password(password, hashed) is True


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [("SuperSecret!123", True), ("wrong-password", False)],
)
def test_verify_password_bcrypt_mode(auth_utils, candidate: str, expected: bool) -> None:
    if auth_utils.bcrypt is None:
        pytest.skip("bcrypt non disponible dans l'environnement")

    hashed = auth_utils.hash_password("SuperSecret!123")

    assert auth_utils.verify_password(candidate, hashed) is expected


def test_hash_password_raises_when_bcrypt_missing(auth_utils, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_utils, "bcrypt", None)

    with pytest.raises(RuntimeError, match="bcrypt est obligatoire"):
        auth_utils.hash_password("fallback-password")


def test_hash_password_uses_test_mode_backend_when_bcrypt_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEGYR_TEST_MODE", "true")
    monkeypatch.setenv("SEGYR_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("SEGYR_DB_PASSWORD", "test-db-password")
    _ensure_jwt_stub(monkeypatch)

    real_import = builtins.__import__

    def _import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "bcrypt":
            raise ImportError("bcrypt unavailable in test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import)
    sys.modules.pop("modules.auth.utils", None)

    from modules.auth import utils as auth_utils_module

    loaded = importlib.reload(auth_utils_module)
    hashed = loaded.hash_password("Test123!")

    assert hashed.startswith("$2")
    assert loaded.verify_password("Test123!", hashed) is True


def test_verify_password_rejects_legacy_sha256_hashes(auth_utils) -> None:
    assert auth_utils.verify_password("legacy-password", "sha256$abc") is False
    assert auth_utils.verify_password("legacy-password", "a" * 64) is False


@pytest.mark.parametrize(
    "invalid_hash",
    ["", "   ", "not-a-hash", "sha256$", "sha256$xyz", "$2b$invalid", "a" * 64],
)
def test_verify_password_returns_false_on_invalid_hashes(auth_utils, invalid_hash: str) -> None:
    assert auth_utils.verify_password("any-password", invalid_hash) is False
