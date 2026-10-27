"""Authentication primitives: password hashing + JWT session tokens.

Password hashing uses hashlib.scrypt (stdlib) so there is no compiled
dependency to be blocked by the local security policy, while still being a
strong, memory-hard KDF. Tokens are signed HS256 JWTs via PyJWT."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from .config import settings

_N = 2**14  # CPU/memory cost
_R = 8
_P = 1
_DKLEN = 32


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("password too short")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=0)
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(derived).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected), maxmem=0
        )
        return hmac.compare_digest(derived, expected)
    except Exception:
        return False


def create_token(user_id: int, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expiry_minutes)).timestamp()),
        "iss": "smart-review-platform",
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"], issuer="smart-review-platform")
    except jwt.PyJWTError:
        return None
