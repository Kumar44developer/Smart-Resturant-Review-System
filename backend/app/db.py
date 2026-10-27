"""Thin, dependency-free data-access layer over the Python stdlib sqlite3 driver.

Deliberately hand-rolled (no SQLAlchemy) so the whole backend runs under the
local Windows security policy. The repositories/services talk to these helpers,
which keeps raw SQL isolated in one place and makes a later swap to SQLAlchemy
+ Postgres a contained change. See docs/ARCHITECTURE.md.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from .config import settings

_local = threading.local()


def _db_path() -> Path:
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open a connection with sane production defaults."""
    file = path or str(_db_path())
    conn = sqlite3.connect(file, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def get_conn() -> sqlite3.Connection:
    """Request/scoped connection (one per OS thread)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = connect()
        _local.conn = conn
    return conn


def close_conn() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def query_all(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    cur = conn.execute(sql, tuple(params))
    return [dict(row) for row in cur.fetchall()]


def query_one(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    rows = query_all(conn, sql, params)
    return rows[0] if rows else None


def scalar(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> Any:
    cur = conn.execute(sql, tuple(params))
    row = cur.fetchone()
    return row[0] if row else None


def execute(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    return conn.execute(sql, tuple(params))


def insert(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> int:
    cur = conn.execute(sql, tuple(params))
    return int(cur.lastrowid)
