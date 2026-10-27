from __future__ import annotations

import sqlite3

from .. import db


def create_session(conn: sqlite3.Connection, user_id: int, restaurant_id: int) -> dict:
    sid = db.insert(
        conn,
        "INSERT INTO conversation_sessions (user_id, restaurant_id) VALUES (?,?)",
        (user_id, restaurant_id),
    )
    return get_session(conn, sid)  # type: ignore[return-value]


def get_session(conn: sqlite3.Connection, session_id: int) -> dict | None:
    return db.query_one(conn, "SELECT * FROM conversation_sessions WHERE id = ?", (session_id,))


def list_sessions_for_user(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    return db.query_all(
        conn,
        "SELECT * FROM conversation_sessions WHERE user_id = ? ORDER BY created_at DESC, id DESC",
        (user_id,),
    )


def add_message(conn: sqlite3.Connection, session_id: int, role: str, content: str) -> int:
    return db.insert(
        conn,
        "INSERT INTO conversation_messages (session_id, role, content) VALUES (?,?,?)",
        (session_id, role, content),
    )


def list_messages(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    return db.query_all(
        conn,
        "SELECT * FROM conversation_messages WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    )


def add_citation(conn: sqlite3.Connection, message_id: int, review_id: int, rank: int,
                 retrieval_score: float | None, excerpt: str | None) -> None:
    db.insert(
        conn,
        """INSERT INTO retrieval_citations (message_id, review_id, rank, retrieval_score, excerpt)
           VALUES (?,?,?,?,?)""",
        (message_id, review_id, rank, retrieval_score, excerpt),
    )


def citations_for_message(conn: sqlite3.Connection, message_id: int) -> list[dict]:
    return db.query_all(
        conn,
        """SELECT c.*, r.restaurant_id, r.review_ts, r.rating, r.source
           FROM retrieval_citations c JOIN reviews r ON r.id = c.review_id
           WHERE c.message_id = ? ORDER BY c.rank ASC""",
        (message_id,),
    )


def delete_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute("DELETE FROM conversation_sessions WHERE id = ?", (session_id,))
