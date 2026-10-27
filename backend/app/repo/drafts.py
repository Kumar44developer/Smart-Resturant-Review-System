from __future__ import annotations

import sqlite3

from .. import db


def create_draft(conn: sqlite3.Connection, review_id: int, restaurant_id: int, body: str,
                 tone: str, provider: str, model_id: str, length: str = "medium",
                 created_by: int | None = None, is_ai_generated: int = 1) -> dict:
    did = db.insert(
        conn,
        """INSERT INTO response_drafts
           (review_id, restaurant_id, body, tone, length, model_provider, model_id,
            is_ai_generated, status, created_by)
           VALUES (?,?,?,?,?,?,?,?, 'draft', ?)""",
        (review_id, restaurant_id, body, tone, length, provider, model_id,
         is_ai_generated, created_by),
    )
    return get_draft(conn, did)  # type: ignore[return-value]


def get_draft(conn: sqlite3.Connection, draft_id: int) -> dict | None:
    return db.query_one(conn, "SELECT * FROM response_drafts WHERE id = ?", (draft_id,))


def list_drafts_for_review(conn: sqlite3.Connection, review_id: int) -> list[dict]:
    return db.query_all(
        conn, "SELECT * FROM response_drafts WHERE review_id = ? ORDER BY id DESC", (review_id,)
    )


def update_body(conn: sqlite3.Connection, draft_id: int, body: str, editor_id: int) -> dict | None:
    db.execute(
        conn,
        "UPDATE response_drafts SET body=?, status='edited', updated_at=datetime('now') WHERE id=?",
        (body, draft_id),
    )
    _ = editor_id
    return get_draft(conn, draft_id)


def set_status(conn: sqlite3.Connection, draft_id: int, status: str,
               approver_id: int | None = None) -> dict | None:
    if status == "approved":
        db.execute(
            conn,
            "UPDATE response_drafts SET status='approved', approved_by=?, approved_at=datetime('now'), updated_at=datetime('now') WHERE id=?",
            (approver_id, draft_id),
        )
    else:
        db.execute(
            conn,
            "UPDATE response_drafts SET status=?, updated_at=datetime('now') WHERE id=?",
            (status, draft_id),
        )
    return get_draft(conn, draft_id)
