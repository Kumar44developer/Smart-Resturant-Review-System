from __future__ import annotations

import json
import sqlite3
from typing import Any

from .. import db


def add_analysis(conn: sqlite3.Connection, review_id: int, *, provider: str, model_id: str,
                 prompt_version: str, sentiment: str | None = None, confidence: float | None = None,
                 aspects: list[dict] | None = None, topics: list[str] | None = None,
                 summary: str | None = None, status: str = "done", duration_ms: int | None = None,
                 error_category: str | None = None, model_version: str | None = None) -> int:
    return db.insert(
        conn,
        """INSERT INTO review_analyses
           (review_id, model_provider, model_id, model_version, prompt_version, sentiment,
            confidence, aspect_results, topics, summary, status, duration_ms, error_category)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (review_id, provider, model_id, model_version, prompt_version, sentiment,
         confidence, json.dumps(aspects or []), json.dumps(topics or []), summary,
         status, duration_ms, error_category),
    )


def list_analyses(conn: sqlite3.Connection, review_id: int) -> list[dict]:
    rows = db.query_all(
        conn,
        "SELECT * FROM review_analyses WHERE review_id = ? ORDER BY analyzed_at DESC, id DESC",
        (review_id,),
    )
    for r in rows:
        r["aspect_results"] = json.loads(r["aspect_results"] or "[]")
        r["topics"] = json.loads(r["topics"] or "[]")
    return rows


def latest_analysis(conn: sqlite3.Connection, review_id: int) -> dict | None:
    rows = list_analyses(conn, review_id)
    return rows[0] if rows else None


# ---- embeddings ----

def upsert_embedding(conn: sqlite3.Connection, review_id: int, restaurant_id: int, *,
                     embedding_model: str, index_version: str, vector: list[float]) -> None:
    conn.execute(
        """INSERT INTO review_embeddings
           (review_id, restaurant_id, embedding_model, index_version, dim, vector, updated_at)
           VALUES (?,?,?,?,?,?,datetime('now'))
           ON CONFLICT(review_id) DO UPDATE SET
             vector=excluded.vector, embedding_model=excluded.embedding_model,
             index_version=excluded.index_version, dim=excluded.dim, updated_at=datetime('now')""",
        (review_id, restaurant_id, embedding_model, index_version, len(vector), json.dumps(vector)),
    )


def get_embeddings(conn: sqlite3.Connection, restaurant_id: int, *,
                   embedding_model: str | None = None) -> list[dict[str, Any]]:
    """Return [{review_id, vector}] for a restaurant, for in-process cosine retrieval."""
    sql = "SELECT review_id, vector, embedding_model FROM review_embeddings WHERE restaurant_id = ?"
    params: list[Any] = [restaurant_id]
    if embedding_model:
        sql += " AND embedding_model = ?"; params.append(embedding_model)
    out = []
    for row in conn.execute(sql, tuple(params)).fetchall():
        out.append({"review_id": row["review_id"], "vector": json.loads(row["vector"])})
    return out


def delete_embedding(conn: sqlite3.Connection, review_id: int) -> None:
    conn.execute("DELETE FROM review_embeddings WHERE review_id = ?", (review_id,))
