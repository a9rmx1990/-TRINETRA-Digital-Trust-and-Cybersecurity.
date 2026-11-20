"""Customer session tokens and analyst credentials.

A customer session token is an access credential bound to one owner identity; it is
never an account number. Analyst tokens are HMAC-signed, scoped and expiring, and are
validated on every SOC route, WebSocket replay, aggregate and MCP read.
"""
from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass

from fastapi import Header

from . import clock
from .config import settings
from .db import get_db
from .util import ApiError, const_eq, hmac_hex, new_id, sha256, token


@dataclass(frozen=True)
class Owner:
    id: str


@dataclass(frozen=True)
class Analyst:
    name: str
    scope: str


def create_owner() -> tuple[str, str]:
    tok = token()
    oid = new_id("own")
    get_db().write(lambda t: t.execute(
        "INSERT INTO owners(id, token_hash, created_ms) VALUES (?, ?, ?)", (oid, sha256(tok), clock.now_ms())))
    return oid, tok


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def require_owner(authorization: str | None = Header(default=None)) -> Owner:
    tok = _bearer(authorization)
    if not tok:
        raise ApiError(401, "unauthenticated", "Sign in to the sandbox to continue.")
    row = get_db().read(lambda t: t.one("SELECT id FROM owners WHERE token_hash = ?", (sha256(tok),)))
    if not row:
        raise ApiError(401, "unauthenticated", "This sandbox session is no longer valid.")
    return Owner(row["id"])


# ---- analysts -----------------------------------------------------------

_generated_passcode: str | None = None


def analyst_passcode() -> str:
    """Passcode from env, else generated once and written to the data dir (never logged)."""
    global _generated_passcode
    if settings.analyst_passcode:
        return settings.analyst_passcode
    if _generated_passcode is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        p = settings.data_dir / "analyst-passcode.txt"
        if p.exists():
            _generated_passcode = p.read_text().strip()
        else:
            _generated_passcode = secrets.token_hex(6)
            p.write_text(_generated_passcode + "\n")
            p.chmod(0o600)
    return _generated_passcode


def issue_analyst_token(name: str, ttl_ms: int = 12 * clock.HOUR) -> str:
    body = {"sub": name, "scope": settings.analyst_scope, "exp": clock.now_ms() + ttl_ms, "jti": new_id("at")}
    raw = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{raw}.{hmac_hex(settings.server_secret, raw)}"


def verify_analyst_token(tok: str | None) -> Analyst:
    if not tok or "." not in tok:
        raise ApiError(401, "unauthenticated", "Analyst sign-in required.")
    raw, sig = tok.rsplit(".", 1)
    if not const_eq(sig, hmac_hex(settings.server_secret, raw)):
        raise ApiError(401, "unauthenticated", "Analyst credential is invalid.")
    body = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    if body["exp"] < clock.now_ms():
        raise ApiError(401, "expired", "Analyst session expired. Sign in again.")
    if body["scope"] != settings.analyst_scope:
        raise ApiError(403, "forbidden_scope", "Credential is not valid for this scope.")
    return Analyst(body["sub"], body["scope"])


def require_analyst(authorization: str | None = Header(default=None)) -> Analyst:
    return verify_analyst_token(_bearer(authorization))
