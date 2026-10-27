"""FastAPI dependencies: request-scoped DB, authentication, restaurant RBAC."""
from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import Depends, HTTPException, Request, status

from . import db
from .repo import restaurants as rrepo
from .repo import users as urepo
from .security import decode_token

SESSION_COOKIE = "srr_session"


def get_db() -> Iterator[sqlite3.Connection]:
    conn = db.get_conn()
    try:
        yield conn
    finally:
        pass  # thread-local connection is reused; closed at shutdown


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def optional_user(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict | None:
    token = _extract_token(request)
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    user = urepo.get_user(conn, int(payload["sub"]))
    if not user or user["status"] != "active":
        return None
    return user


def current_user(user: dict | None = Depends(optional_user)) -> dict:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    return user


def enforce_role(conn: sqlite3.Connection, user: dict, restaurant_id: int, min_role: str) -> dict:
    """Verify active membership and sufficient role. Never trust a client-supplied id."""
    membership = rrepo.get_membership(conn, user["id"], restaurant_id)
    if not membership:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this restaurant")
    if not rrepo.role_at_least(membership["role"], min_role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {min_role} role")
    return membership


def is_admin(conn: sqlite3.Connection, user: dict) -> bool:
    """Admin = owns at least one restaurant (used for the developer/eval view)."""
    return urepo.user_owns_any(conn, user["id"])
