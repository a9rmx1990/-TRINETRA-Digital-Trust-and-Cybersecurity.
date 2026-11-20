from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid

from fastapi import HTTPException


def new_id(prefix: str) -> str:
    """Opaque server-generated identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def sha256(s: str | bytes) -> str:
    if isinstance(s, str):
        s = s.encode()
    return hashlib.sha256(s).hexdigest()


def hmac_hex(secret: str, msg: str) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def const_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def mask_ref(ref: str | None) -> str:
    if not ref:
        return ""
    tail = ref[-4:]
    return "•••• " + tail


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(status_code=status, detail={"code": code, "message": message, **extra})


def format_inr(minor: int) -> str:
    """Indian digit grouping, e.g. 123456789 -> ₹12,34,567.89"""
    neg = minor < 0
    minor = abs(minor)
    rupees, paise = divmod(minor, 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return f"{'-' if neg else ''}₹{s}.{paise:02d}"
