from __future__ import annotations

import sqlite3

from .. import db

ROLE_ORDER = {"viewer": 0, "member": 1, "manager": 2, "owner": 3}


def create_restaurant(conn: sqlite3.Connection, name: str, owner_user_id: int,
                      description: str | None = None, location: str | None = None,
                      timezone: str = "UTC") -> dict:
    rid = db.insert(
        conn,
        "INSERT INTO restaurants (name, description, location, timezone) VALUES (?,?,?,?)",
        (name.strip(), description, location, timezone),
    )
    add_membership(conn, owner_user_id, rid, "owner")
    return get_restaurant(conn, rid)  # type: ignore[return-value]


def get_restaurant(conn: sqlite3.Connection, restaurant_id: int) -> dict | None:
    return db.query_one(conn, "SELECT * FROM restaurants WHERE id = ?", (restaurant_id,))


def update_restaurant(conn: sqlite3.Connection, restaurant_id: int, **fields) -> dict | None:
    allowed = {"name", "description", "location", "timezone"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if sets:
        assignments = ", ".join(f"{k} = ?" for k in sets)
        conn.execute(f"UPDATE restaurants SET {assignments} WHERE id = ?", (*sets.values(), restaurant_id))
    return get_restaurant(conn, restaurant_id)


def list_restaurants_for_user(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    return db.query_all(
        conn,
        """SELECT r.*, m.role FROM restaurants r
           JOIN memberships m ON m.restaurant_id = r.id
           WHERE m.user_id = ? AND m.status = 'active'
           ORDER BY r.name""",
        (user_id,),
    )


def add_membership(conn: sqlite3.Connection, user_id: int, restaurant_id: int, role: str,
                   status: str = "active") -> None:
    if role not in ROLE_ORDER:
        raise ValueError(f"unknown role {role}")
    conn.execute(
        """INSERT INTO memberships (user_id, restaurant_id, role, status) VALUES (?,?,?,?)
           ON CONFLICT(user_id, restaurant_id) DO UPDATE SET role=excluded.role, status=excluded.status""",
        (user_id, restaurant_id, role, status),
    )


def get_membership(conn: sqlite3.Connection, user_id: int, restaurant_id: int) -> dict | None:
    return db.query_one(
        conn,
        "SELECT * FROM memberships WHERE user_id = ? AND restaurant_id = ? AND status = 'active'",
        (user_id, restaurant_id),
    )


def list_members(conn: sqlite3.Connection, restaurant_id: int) -> list[dict]:
    return db.query_all(
        conn,
        """SELECT u.id AS user_id, u.name, u.email, m.role, m.status
           FROM memberships m JOIN users u ON u.id = m.user_id
           WHERE m.restaurant_id = ? ORDER BY m.role, u.name""",
        (restaurant_id,),
    )


def role_at_least(role: str, minimum: str) -> bool:
    return ROLE_ORDER.get(role, -1) >= ROLE_ORDER.get(minimum, 99)
