"""Ordered SQL migration runner.

Applies every ``NNN_*.sql`` file under this directory that is not already
recorded in ``schema_migrations``, each inside its own transaction. Keeps a
recorded history so re-running is safe (idempotent)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _ensure_history(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )


def applied(conn: sqlite3.Connection) -> set[str]:
    _ensure_history(conn)
    return {r["name"] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}


def pending_files(applied_names: set[str]) -> list[Path]:
    return [p for p in sorted(HERE.glob("*.sql")) if p.name not in applied_names]


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply all pending migrations; return the list of applied filenames."""
    _ensure_history(conn)
    done = applied(conn)
    applied_now: list[str] = []
    for path in pending_files(done):
        sql = path.read_text(encoding="utf-8")
        # executescript() implicitly commits any open transaction before running,
        # so the app connection is kept in autocommit (isolation_level=None) and we
        # do not wrap it in a manual BEGIN/COMMIT here.
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (path.name,))
        applied_now.append(path.name)
    return applied_now
