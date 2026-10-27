from __future__ import annotations

import sqlite3
from typing import Any

from .. import db


def create_review(conn: sqlite3.Connection, restaurant_id: int, review_text: str,
                  rating: float | None = None, source: str = "manual",
                  external_source_id: str | None = None, author_name: str | None = None,
                  review_ts: str | None = None, language: str = "en",
                  is_synthetic: int = 0) -> dict:
    rid = db.insert(
        conn,
        """INSERT INTO reviews
           (restaurant_id, review_text, rating, source, external_source_id,
            author_name, review_ts, language, is_synthetic)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (restaurant_id, review_text, rating, source, external_source_id,
         author_name, review_ts, language, is_synthetic),
    )
    return get_review(conn, rid)  # type: ignore[return-value]


def get_review(conn: sqlite3.Connection, review_id: int) -> dict | None:
    return db.query_one(conn, "SELECT * FROM reviews WHERE id = ?", (review_id,))


def update_review(conn: sqlite3.Connection, review_id: int, **fields: Any) -> dict | None:
    allowed = {"review_text", "rating", "author_name", "review_ts", "language", "analysis_status"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if sets:
        assignments = ", ".join(f"{k} = ?" for k in sets)
        conn.execute(
            f"UPDATE reviews SET {assignments}, updated_at = datetime('now') WHERE id = ?",
            (*sets.values(), review_id),
        )
    return get_review(conn, review_id)


def delete_review(conn: sqlite3.Connection, review_id: int) -> None:
    conn.execute("DELETE FROM reviews WHERE id = ?", (review_id,))


def set_analysis_status(conn: sqlite3.Connection, review_id: int, status: str) -> None:
    conn.execute("UPDATE reviews SET analysis_status = ? WHERE id = ?", (status, review_id))


def duplicate_exists(conn: sqlite3.Connection, restaurant_id: int, source: str,
                     external_source_id: str | None) -> bool:
    if external_source_id is None:
        return False
    return db.scalar(
        conn,
        "SELECT 1 FROM reviews WHERE restaurant_id=? AND source=? AND external_source_id=? LIMIT 1",
        (restaurant_id, source, external_source_id),
    ) is not None


_FILTER_ALLOWED = {
    "source": "source = ?",
    "analysis_status": "analysis_status = ?",
    "language": "language = ?",
}


def search(conn: sqlite3.Connection, restaurant_id: int, *, q: str | None = None,
           rating_min: float | None = None, rating_max: float | None = None,
           sentiment: str | None = None, source: str | None = None,
           date_from: str | None = None, date_to: str | None = None,
           sort: str = "review_ts", order: str = "desc",
           limit: int = 20, offset: int = 0) -> dict:
    """Search/filter with pagination. Sentiment filter joins the latest analysis."""
    where = ["r.restaurant_id = ?"]
    params: list[Any] = [restaurant_id]
    if source:
        where.append("r.source = ?"); params.append(source)
    if rating_min is not None:
        where.append("r.rating >= ?"); params.append(rating_min)
    if rating_max is not None:
        where.append("r.rating <= ?"); params.append(rating_max)
    if date_from:
        where.append("r.review_ts >= ?"); params.append(date_from)
    if date_to:
        where.append("r.review_ts <= ?"); params.append(date_to)

    # Always attach the latest analysis sentiment (single `la` alias) so both
    # the sentiment filter and the display column share one join.
    la_join = """LEFT JOIN (
        SELECT review_id, sentiment,
               ROW_NUMBER() OVER (PARTITION BY review_id ORDER BY analyzed_at DESC) rn
        FROM review_analyses
    ) la ON la.review_id = r.id AND la.rn = 1"""
    if sentiment:
        where.append("la.sentiment = ?")
        params.append(sentiment)

    if q:
        # keyword search uses FTS5 rowids intersected with the scope.
        fts_ids = [row["rowid"] for row in conn.execute(
            "SELECT rowid FROM reviews_fts WHERE reviews_fts MATCH ?", (q,)
        ).fetchall()]
        if not fts_ids:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        placeholders = ",".join("?" * len(fts_ids))
        where.append(f"r.id IN ({placeholders})")
        params.extend(fts_ids)

    sort_map = {
        "review_ts": "r.review_ts", "created_at": "r.created_at",
        "rating": "r.rating", "id": "r.id",
    }
    sort_col = sort_map.get(sort, "r.review_ts")
    dirn = "ASC" if str(order).lower() == "asc" else "DESC"

    where_sql = " AND ".join(where)
    total = db.scalar(conn, f"SELECT COUNT(*) FROM reviews r {la_join} WHERE {where_sql}", params)
    items = db.query_all(
        conn,
        f"""SELECT r.*, la.sentiment AS sentiment
            FROM reviews r
            {la_join}
            WHERE {where_sql}
            ORDER BY {sort_col} {dirn} NULLS LAST
            LIMIT ? OFFSET ?""",
        (*params, limit, offset),
    )
    return {"items": items, "total": int(total or 0), "limit": limit, "offset": offset}
