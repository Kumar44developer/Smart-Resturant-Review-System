from __future__ import annotations

import sqlite3

from .. import db
from ..security import hash_password


def create_user(conn: sqlite3.Connection, name: str, email: str, password: str, status: str = "active") -> dict:
    email = email.strip().lower()
    uid = db.insert(
        conn,
        "INSERT INTO users (name, email, password_hash, status) VALUES (?,?,?,?)",
        (name.strip(), email, hash_password(password), status),
    )
    return get_user(conn, uid)  # type: ignore[return-value]


def get_user(conn: sqlite3.Connection, user_id: int) -> dict | None:
    return db.query_one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))


def get_user_by_email(conn: sqlite3.Connection, email: str) -> dict | None:
    return db.query_one(conn, "SELECT * FROM users WHERE email = ?", (email.strip().lower(),))


def user_owns_any(conn: sqlite3.Connection, user_id: int) -> bool:
    return db.scalar(
        conn,
        "SELECT 1 FROM memberships WHERE user_id = ? AND role = 'owner' AND status = 'active' LIMIT 1",
        (user_id,),
    ) is not None
