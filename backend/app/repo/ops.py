"""Repositories for jobs, usage, audit, recommendations, alerts, actions, evaluation."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from .. import db


# ---- import jobs ----

def create_job(conn: sqlite3.Connection, restaurant_id: int, filename: str, created_by: int | None) -> dict:
    jid = db.insert(
        conn,
        "INSERT INTO import_jobs (restaurant_id, filename, status, created_by, started_at) VALUES (?,?,'queued',?,datetime('now'))",
        (restaurant_id, filename, created_by),
    )
    return get_job(conn, jid)  # type: ignore[return-value]


def get_job(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = db.query_one(conn, "SELECT * FROM import_jobs WHERE id = ?", (job_id,))
    if row and row.get("error_details"):
        row["error_details"] = json.loads(row["error_details"])
    return row


def update_job(conn: sqlite3.Connection, job_id: int, **fields: Any) -> None:
    allowed = {"status", "total_rows", "imported", "skipped", "invalid_count",
               "duplicate_count", "error_details", "completed_at"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if "error_details" in sets and not isinstance(sets["error_details"], str):
        sets["error_details"] = json.dumps(sets["error_details"])
    if sets:
        assignments = ", ".join(f"{k} = ?" for k in sets)
        conn.execute(f"UPDATE import_jobs SET {assignments} WHERE id = ?", (*sets.values(), job_id))


# ---- ai usage ----

def record_usage(conn: sqlite3.Connection, *, user_id: int | None, restaurant_id: int | None,
                 operation: str, provider: str, model: str, input_tokens: int | None = None,
                 output_tokens: int | None = None, estimated_cost_micros: int | None = None,
                 pricing_version: str | None = None, latency_ms: int | None = None,
                 status: str = "ok") -> None:
    db.insert(
        conn,
        """INSERT INTO ai_usage_records
           (user_id, restaurant_id, operation, provider, model, input_tokens, output_tokens,
            estimated_cost_micros, pricing_version, latency_ms, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, restaurant_id, operation, provider, model, input_tokens, output_tokens,
         estimated_cost_micros, pricing_version, latency_ms, status),
    )


def usage_summary(conn: sqlite3.Connection, restaurant_id: int | None = None) -> dict:
    where = "WHERE restaurant_id IS NOT NULL"
    params: list[Any] = []
    if restaurant_id is not None:
        where = "WHERE restaurant_id = ?"
        params = [restaurant_id]
    return db.query_one(
        conn,
        f"""SELECT COUNT(*) AS operations,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors,
                   SUM(CASE WHEN status='fallback' THEN 1 ELSE 0 END) AS fallbacks,
                   SUM(COALESCE(input_tokens,0)) AS input_tokens,
                   SUM(COALESCE(output_tokens,0)) AS output_tokens,
                   SUM(COALESCE(estimated_cost_micros,0)) AS cost_micros,
                   AVG(latency_ms) AS avg_latency_ms
            FROM ai_usage_records {where}""",
        params,
    ) or {}


# ---- audit ----

def audit(conn: sqlite3.Connection, *, actor_user_id: int | None, restaurant_id: int | None,
          action: str, resource_type: str, resource_id: Any = None, metadata: dict | None = None) -> None:
    db.insert(
        conn,
        """INSERT INTO audit_events (actor_user_id, restaurant_id, action, resource_type, resource_id, metadata)
           VALUES (?,?,?,?,?,?)""",
        (actor_user_id, restaurant_id, action, resource_type,
         str(resource_id) if resource_id is not None else None,
         json.dumps(metadata or {})),
    )


def recent_audit(conn: sqlite3.Connection, restaurant_id: int | None = None, limit: int = 50) -> list[dict]:
    if restaurant_id is not None:
        return db.query_all(
            conn,
            "SELECT * FROM audit_events WHERE restaurant_id = ? ORDER BY id DESC LIMIT ?",
            (restaurant_id, limit),
        )
    return db.query_all(conn, "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,))


# ---- recommendations ----

def add_recommendation(conn: sqlite3.Connection, *, restaurant_id: int, proposed_action: str,
                       supporting_theme: str | None, supporting_review_ids: list[int],
                       support_count: int, priority_rationale: str | None,
                       uncertainty: str | None) -> int:
    return db.insert(
        conn,
        """INSERT INTO recommendations
           (restaurant_id, proposed_action, supporting_theme, supporting_review_ids,
            support_count, priority_rationale, uncertainty)
           VALUES (?,?,?,?,?,?,?)""",
        (restaurant_id, proposed_action, supporting_theme, json.dumps(supporting_review_ids),
         support_count, priority_rationale, uncertainty),
    )


def list_recommendations(conn: sqlite3.Connection, restaurant_id: int) -> list[dict]:
    rows = db.query_all(
        conn,
        "SELECT * FROM recommendations WHERE restaurant_id = ? ORDER BY support_count DESC, id DESC",
        (restaurant_id,),
    )
    for r in rows:
        r["supporting_review_ids"] = json.loads(r["supporting_review_ids"] or "[]")
    return rows


# ---- alerts ----

def add_alert(conn: sqlite3.Connection, *, restaurant_id: int, rule: str, aspect: str | None,
              window: str | None, severity: str, metric: dict, message: str) -> int:
    return db.insert(
        conn,
        """INSERT INTO alerts (restaurant_id, rule, aspect, window, severity, metric, message)
           VALUES (?,?,?,?,?,?,?)""",
        (restaurant_id, rule, aspect, window, severity, json.dumps(metric), message),
    )


def list_alerts(conn: sqlite3.Connection, restaurant_id: int, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM alerts WHERE restaurant_id = ?"
    params: list[Any] = [restaurant_id]
    if status:
        sql += " AND status = ?"; params.append(status)
    sql += " ORDER BY CASE severity WHEN 'urgent' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, id DESC"
    rows = db.query_all(conn, sql, params)
    for r in rows:
        r["metric"] = json.loads(r["metric"] or "{}")
    return rows


def set_alert_status(conn: sqlite3.Connection, alert_id: int, status: str) -> None:
    if status == "reviewed":
        conn.execute("UPDATE alerts SET status='reviewed', reviewed_at=datetime('now') WHERE id=?", (alert_id,))
    else:
        conn.execute("UPDATE alerts SET status=? WHERE id=?", (status, alert_id))


def alert_exists_recent(conn: sqlite3.Connection, restaurant_id: int, rule: str, aspect: str | None) -> dict | None:
    sql = "SELECT * FROM alerts WHERE restaurant_id=? AND rule=? AND status='open'"
    params: list[Any] = [restaurant_id, rule]
    if aspect:
        sql += " AND aspect=?"; params.append(aspect)
    return db.query_one(conn, sql + " LIMIT 1", params)


# ---- actions ----

def create_action(conn: sqlite3.Connection, *, restaurant_id: int, title: str, description: str | None,
                  owner_user_id: int | None, due_date: str | None, review_ids: list[int]) -> dict:
    aid = db.insert(
        conn,
        """INSERT INTO actions (restaurant_id, title, description, owner_user_id, due_date, status)
           VALUES (?,?,?,?,?, 'open')""",
        (restaurant_id, title, description, owner_user_id, due_date),
    )
    for rid in review_ids:
        conn.execute("INSERT OR IGNORE INTO action_review_links (action_id, review_id) VALUES (?,?)", (aid, rid))
    return get_action(conn, aid)  # type: ignore[return-value]


def get_action(conn: sqlite3.Connection, action_id: int) -> dict | None:
    row = db.query_one(conn, "SELECT * FROM actions WHERE id = ?", (action_id,))
    if row:
        row["review_ids"] = [r["review_id"] for r in conn.execute(
            "SELECT review_id FROM action_review_links WHERE action_id=?", (action_id,)).fetchall()]
    return row


def list_actions(conn: sqlite3.Connection, restaurant_id: int) -> list[dict]:
    rows = db.query_all(
        conn, "SELECT * FROM actions WHERE restaurant_id = ? ORDER BY id DESC", (restaurant_id,)
    )
    for r in rows:
        r["review_ids"] = [x["review_id"] for x in conn.execute(
            "SELECT review_id FROM action_review_links WHERE action_id=?", (r["id"],)).fetchall()]
    return rows


def update_action(conn: sqlite3.Connection, action_id: int, **fields: Any) -> dict | None:
    allowed = {"title", "description", "status", "owner_user_id", "due_date", "resolution_note"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if sets:
        assignments = ", ".join(f"{k} = ?" for k in sets)
        conn.execute(
            f"UPDATE actions SET {assignments}, updated_at=datetime('now') WHERE id = ?",
            (*sets.values(), action_id),
        )
    return get_action(conn, action_id)


# ---- evaluation ----

def record_evaluation(conn: sqlite3.Connection, *, task: str, dataset_version: str,
                      model_version: str, prompt_version: str, config: dict,
                      metrics: dict, failures: list[dict]) -> int:
    return db.insert(
        conn,
        """INSERT INTO evaluation_runs
           (task, dataset_version, model_version, prompt_version, config, metrics, failures)
           VALUES (?,?,?,?,?,?,?)""",
        (task, dataset_version, model_version, prompt_version,
         json.dumps(config), json.dumps(metrics), json.dumps(failures)),
    )


def list_evaluations(conn: sqlite3.Connection, task: str | None = None) -> list[dict]:
    sql = "SELECT * FROM evaluation_runs"
    params: list[Any] = []
    if task:
        sql += " WHERE task = ?"; params.append(task)
    sql += " ORDER BY id DESC"
    rows = db.query_all(conn, sql, params)
    for r in rows:
        r["metrics"] = json.loads(r["metrics"])
        r["config"] = json.loads(r["config"] or "{}")
        r["failures"] = json.loads(r["failures"] or "[]")
    return rows
