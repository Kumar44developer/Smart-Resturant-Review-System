"""Operational endpoints: alerts, actions, recommendations, reports/exports,
weekly digest, usage & audit records, evaluation runs, and a dev-only seed.

All reads/writes enforce restaurant-role scoping first, so one tenant can never
touch another's operational data. Usage/cost is reported exactly as stored (in
integer micro-units) with its pricing version, never rounded up into a claim."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from ... import migrations as mig
from ... import db as dbmod
from ...config import settings
from ...deps import current_user, enforce_role, get_db, is_admin
from ...repo import ops as orepo
from ...schemas import ActionIn, ActionPatch
from ...services import alerts, evaluation, export, recommendations, weekly
from ...services.seed import seed_demo

router = APIRouter(tags=["ops"])


# ---- Alerts ----

@router.get("/restaurants/{restaurant_id}/alerts")
def list_alerts(restaurant_id: int, state: str | None = Query(default=None, pattern="^(open|reviewed|dismissed)$"),
                user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "viewer")
    return orepo.list_alerts(conn, restaurant_id, status=state)


@router.post("/restaurants/{restaurant_id}/alerts/detect")
def detect_alerts(restaurant_id: int, window_days: int = Query(default=14, ge=1, le=120),
                  user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "manager")
    created = alerts.detect(conn, restaurant_id, window_days=window_days)
    orepo.audit(conn, actor_user_id=user["id"], restaurant_id=restaurant_id,
                action="alerts.detect", resource_type="restaurant", resource_id=restaurant_id,
                metadata={"created": len(created)})
    return {"detected": len(created), "alerts": created}


def _get_alert(conn, alert_id):
    row = conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    return dict(row) if row else None


@router.post("/alerts/{alert_id}/review")
def review_alert(alert_id: int, user: dict = Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    alert = _get_alert(conn, alert_id)
    if not alert:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    enforce_role(conn, user, alert["restaurant_id"], "manager")
    orepo.set_alert_status(conn, alert_id, "reviewed")
    return _get_alert(conn, alert_id)


@router.post("/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: int, user: dict = Depends(current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    alert = _get_alert(conn, alert_id)
    if not alert:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    enforce_role(conn, user, alert["restaurant_id"], "manager")
    orepo.set_alert_status(conn, alert_id, "dismissed")
    return _get_alert(conn, alert_id)


# ---- Actions (commitment / follow-through tracking) ----

@router.get("/restaurants/{restaurant_id}/actions")
def list_actions(restaurant_id: int, user: dict = Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "viewer")
    return orepo.list_actions(conn, restaurant_id)


@router.post("/restaurants/{restaurant_id}/actions", status_code=status.HTTP_201_CREATED)
def create_action(restaurant_id: int, body: ActionIn, user: dict = Depends(current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "member")
    # Validate any linked reviews belong to this restaurant (no cross-tenant links).
    from ...repo import reviews as rrepo
    for rid in body.review_ids:
        rv = rrepo.get_review(conn, rid)
        if not rv or rv["restaurant_id"] != restaurant_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"review {rid} not in this restaurant")
    action = orepo.create_action(conn, restaurant_id=restaurant_id, title=body.title,
                                 description=body.description, owner_user_id=body.owner_user_id,
                                 due_date=body.due_date, review_ids=body.review_ids)
    orepo.audit(conn, actor_user_id=user["id"], restaurant_id=restaurant_id,
                action="action.create", resource_type="action", resource_id=action["id"])
    return action


@router.patch("/actions/{action_id}")
def patch_action(action_id: int, body: ActionPatch, user: dict = Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    action = orepo.get_action(conn, action_id)
    if not action:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Action not found")
    enforce_role(conn, user, action["restaurant_id"], "member")
    updated = orepo.update_action(conn, action_id, **body.model_dump(exclude_none=True))
    orepo.audit(conn, actor_user_id=user["id"], restaurant_id=action["restaurant_id"],
                action="action.update", resource_type="action", resource_id=action_id)
    return updated


# ---- Recommendations ----

@router.get("/restaurants/{restaurant_id}/recommendations")
def list_recommendations(restaurant_id: int, user: dict = Depends(current_user),
                        conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "viewer")
    return recommendations.list_persisted(conn, restaurant_id)


@router.post("/restaurants/{restaurant_id}/recommendations/compute")
def compute_recommendations(restaurant_id: int, persist: bool = True,
                            user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "manager")
    return recommendations.compute(conn, restaurant_id, persist=persist)


# ---- Reports / exports ----

@router.get("/restaurants/{restaurant_id}/report")
def report_json(restaurant_id: int, date_from: str | None = None, date_to: str | None = None,
                user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "viewer")
    return export.to_json(conn, restaurant_id, date_from=date_from, date_to=date_to)


@router.get("/restaurants/{restaurant_id}/report.csv")
def report_csv(restaurant_id: int, date_from: str | None = None, date_to: str | None = None,
               user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "viewer")
    csv_text = export.to_csv(conn, restaurant_id, date_from=date_from, date_to=date_to)
    return Response(content=csv_text, media_type="text/csv",
                    headers={"content-disposition": f'attachment; filename="report-{restaurant_id}.csv"'})


@router.get("/restaurants/{restaurant_id}/weekly")
def weekly_digest(restaurant_id: int, week_days: int = Query(default=7, ge=1, le=120),
                  user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "viewer")
    return weekly.build(conn, restaurant_id, week_days=week_days)


# ---- Usage & audit ----

@router.get("/restaurants/{restaurant_id}/usage")
def usage(restaurant_id: int, user: dict = Depends(current_user),
          conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "manager")
    summary = orepo.usage_summary(conn, restaurant_id)
    return {**summary, "cost_field": "estimated_cost_micros",
            "note": "Costs are integer micro-units with the pricing version recorded per call."}


@router.get("/restaurants/{restaurant_id}/audit")
def audit_log(restaurant_id: int, limit: int = Query(default=50, ge=1, le=200),
              user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "manager")
    return orepo.recent_audit(conn, restaurant_id, limit=limit)


# ---- Evaluation (owner/admin developer view) ----

@router.get("/evaluation/runs")
def list_evaluations(task: str | None = None, user: dict = Depends(current_user),
                     conn: sqlite3.Connection = Depends(get_db)):
    if not is_admin(conn, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requires owning a restaurant")
    return orepo.list_evaluations(conn, task=task)


@router.post("/evaluation/run")
def run_evaluation(restaurant_id: int | None = None, user: dict = Depends(current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    """Evaluate the ACTUAL local deterministic pipeline. If a restaurant you own is
    given, RAG abstention/citation-integrity is measured against its real reviews."""
    if not is_admin(conn, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requires owning a restaurant")
    if restaurant_id is not None:
        enforce_role(conn, user, restaurant_id, "owner")
    return evaluation.run_all(conn, restaurant_id=restaurant_id)


# ---- Dev-only demo seeding ----

@router.post("/dev/seed-demo")
def seed(user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Idempotent synthetic-data seeding for local demo. Guarded to non-prod and to
    owners. Seeded reviews are flagged is_synthetic so the UI labels them honestly."""
    if settings.is_prod:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not available in production")
    if not is_admin(conn, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requires owning a restaurant")
    mig.migrate(conn)
    return seed_demo(conn)
