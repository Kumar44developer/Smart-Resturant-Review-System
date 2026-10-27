"""Web UI routes. Every value rendered here comes from the same services the JSON
API uses. The UI does not compute or invent anything; it displays stored, measured
facts and clearly labels demo/synthetic data and AI-generated text."""
from __future__ import annotations

import sqlite3
from pathlib import Path as _Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import db as _db
from .. import security
from ..config import settings
from ..deps import SESSION_COOKIE, enforce_role
from ..repo import analysis as arepo
from ..repo import conversations as crepo
from ..repo import drafts as drepo
from ..repo import ops as orepo
from ..repo import restaurants as rrepo
from ..repo import reviews as rrepo_rev
from ..repo import users as urepo
from ..services import alerts as alerts_svc
from ..services import analysis as analysis_svc
from ..services import analytics, evaluation, export, jobs, rag, recommendations, reply, weekly
from ..services.seed import seed_demo

templates = Jinja2Templates(directory=str(_Path(__file__).resolve().parent.parent / "templates"))
router = APIRouter()

# Web pages treat any auth/role HTTPException as a friendly redirect/403 render.
def _get_db() -> sqlite3.Connection:
    return _db.get_conn()


def _context(request, user, *, restaurant=None, role=None, nav="", **extra):
    base = {
        "request": request,
        "user": user,
        "demo_mode": settings.demo_mode,
        "nav": nav,
        "restaurants": rrepo.list_restaurants_for_user(_db.get_conn(), user["id"]) if user else [],
        "restaurant": restaurant,
        "role": role,
    }
    base.update(extra)
    return base


def _require_role(conn, user, restaurant_id, min_role):
    """Returns (membership, restaurant) or raises RedirectResponse via exception."""
    enforce_role(conn, user, restaurant_id, min_role)
    rest = rrepo.get_restaurant(conn, restaurant_id)
    return rrepo.get_membership(conn, user["id"], restaurant_id), rest


# ---------------------------------------------------------------- auth
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, register: bool = False,
               conn: sqlite3.Connection = Depends(_get_db)):
    if optional_user_with_conn(request, conn):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html",
                                      {"demo_mode": settings.demo_mode, "register": register})


def optional_user_with_conn(request: Request, conn):
    from ..deps import _extract_token
    token = _extract_token(request)
    if not token:
        return None
    payload = security.decode_token(token)
    if not payload:
        return None
    u = urepo.get_user(conn, int(payload["sub"]))
    return u if u and u["status"] == "active" else None


@router.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...),
                 conn: sqlite3.Connection = Depends(_get_db)):
    user = urepo.get_user_by_email(conn, email.strip().lower())
    if not user or not security.verify_password(password, user["password_hash"]) or user["status"] != "active":
        return templates.TemplateResponse(request, "login.html",
                                          {"error": "Invalid email or password.", "demo_mode": settings.demo_mode},
                                          status_code=401)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(SESSION_COOKIE, security.create_token(user["id"], user["email"]),
                    httponly=True, samesite="lax", secure=False, max_age=60 * 60 * 24)
    return resp


@router.post("/register")
def register_submit(request: Request, name: str = Form(...), email: str = Form(...),
                    password: str = Form(...), conn: sqlite3.Connection = Depends(_get_db)):
    email = email.strip().lower()
    if urepo.get_user_by_email(conn, email):
        return templates.TemplateResponse(request, "login.html",
                                          {"error": "Email already registered.", "register": True,
                                           "demo_mode": settings.demo_mode}, status_code=400)
    try:
        user = urepo.create_user(conn, name, email, password)
    except ValueError as exc:
        return templates.TemplateResponse(request, "login.html",
                                          {"error": str(exc), "register": True, "demo_mode": settings.demo_mode},
                                          status_code=400)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(SESSION_COOKIE, security.create_token(user["id"], user["email"]),
                    httponly=True, samesite="lax", secure=False, max_age=60 * 60 * 24)
    return resp


@router.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


def _me(request: Request, conn):
    user = optional_user_with_conn(request, conn)
    return user


@router.post("/r/new")
def create_restaurant(request: Request, name: str = Form(...),
                      conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    rest = rrepo.create_restaurant(conn, name.strip(), user["id"])
    return RedirectResponse(f"/?r={rest['id']}", status_code=302)


# ---------------------------------------------------------------- dashboard
@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, r: int | None = Query(default=None, alias="r"),
              conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    rest_list = rrepo.list_restaurants_for_user(conn, user["id"])
    if not rest_list:
        return templates.TemplateResponse(request, "dashboard.html",
                                          _context(request, user, nav="dashboard", empty=True))
    restaurant_id = r or rest_list[0]["id"]
    membership, rest = _require_role(conn, user, restaurant_id, "viewer")
    overview = analytics.overview(conn, restaurant_id)
    wk = weekly.build(conn, restaurant_id)
    recent = rrepo_rev.search(conn, restaurant_id, limit=5, offset=0)["items"]
    open_alerts = orepo.list_alerts(conn, restaurant_id, status="open")
    return templates.TemplateResponse(request, "dashboard.html", _context(
        request, user, restaurant=rest, role=membership["role"], nav="dashboard",
        overview=overview, weekly=wk, recent=recent, open_alerts=open_alerts,
        trend=analytics.sentiment_trend(conn, restaurant_id),
        rating_trend=analytics.rating_trend(conn, restaurant_id),
    ))


# ---------------------------------------------------------------- reviews
@router.get("/r/{rid}/reviews", response_class=HTMLResponse)
def reviews_page(rid: int, request: Request, q: str | None = None, sentiment: str | None = None,
                 source: str | None = None, page: int = 1, size: int = 20,
                 conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    membership, rest = _require_role(conn, user, rid, "viewer")
    data = rrepo_rev.search(conn, rid, q=q, sentiment=sentiment, source=source,
                            limit=size, offset=(page - 1) * size)
    total_pages = max(1, (data["total"] + size - 1) // size)
    return templates.TemplateResponse(request, "reviews.html", _context(
        request, user, restaurant=rest, role=membership["role"], nav="reviews",
        result=data, q=q, sentiment=sentiment, source=source, page=page,
        size=size, total_pages=total_pages,
    ))


@router.post("/r/{rid}/reviews")
def review_create(rid: int, request: Request, conn: sqlite3.Connection = Depends(_get_db),
                  review_text: str = Form(...), rating: str | None = Form(default=None),
                  author_name: str | None = Form(default=None), source: str = Form(default="manual")):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    _require_role(conn, user, rid, "member")
    rating_val = float(rating) if rating not in (None, "", "none") else None
    review = rrepo_rev.create_review(conn, rid, review_text, rating=rating_val,
                                     source=source, author_name=author_name)
    try:
        analysis_svc.analyze_review(conn, review["id"], user_id=user["id"])
    except Exception:  # noqa: BLE001
        pass
    return RedirectResponse(f"/r/{rid}/reviews", status_code=302)


@router.get("/reviews/{review_id}", response_class=HTMLResponse)
def review_detail(review_id: int, request: Request, conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    review = rrepo_rev.get_review(conn, review_id)
    if not review:
        raise StarletteHTTPException(404, "Review not found")
    membership, rest = _require_role(conn, user, review["restaurant_id"], "viewer")
    la = arepo.latest_analysis(conn, review_id)
    drafts = drepo.list_drafts_for_review(conn, review_id)
    return templates.TemplateResponse(request, "review_detail.html", _context(
        request, user, restaurant=rest, role=membership["role"], nav="reviews",
        review=review, analysis=la, drafts=drafts,
    ))


# ---------------------------------------------------------------- analytics
@router.get("/r/{rid}/analytics", response_class=HTMLResponse)
def analytics_page(rid: int, request: Request, conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    membership, rest = _require_role(conn, user, rid, "viewer")
    return templates.TemplateResponse(request, "analytics.html", _context(
        request, user, restaurant=rest, role=membership["role"], nav="analytics",
        overview=analytics.overview(conn, rid),
        aspects=analytics.aspect_analytics(conn, rid),
        complaints=analytics.most_frequent_complaints(conn, rid),
        praise=analytics.most_praised_themes(conn, rid),
        sentiment_trend=analytics.sentiment_trend(conn, rid),
        rating_trend=analytics.rating_trend(conn, rid),
        recs=recommendations.compute(conn, rid, persist=False),
    ))


# ---------------------------------------------------------------- chat (RAG)
@router.get("/r/{rid}/chat", response_class=HTMLResponse)
def chat_page(rid: int, request: Request, session_id: int | None = None,
              conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    membership, rest = _require_role(conn, user, rid, "viewer")
    messages = []
    if session_id is not None:
        session = crepo.get_session(conn, session_id)
        if session and session["user_id"] == user["id"]:
            for m in crepo.list_messages(conn, session_id):
                messages.append({**m, "citations": crepo.citations_for_message(conn, m["id"])})
    sessions = crepo.list_sessions_for_user(conn, user["id"])
    return templates.TemplateResponse(request, "chat.html", _context(
        request, user, restaurant=rest, role=membership["role"], nav="chat",
        messages=messages, session_id=session_id, sessions=sessions,
    ))


@router.post("/r/{rid}/chat")
def chat_ask(rid: int, request: Request, question: str = Form(...),
             session_id: int | None = Form(default=None),
             conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    _require_role(conn, user, rid, "viewer")
    if not session_id:
        session_id = crepo.create_session(conn, user["id"], rid)["id"]
    result = rag.answer_question(conn, restaurant_id=rid, question=question.strip(),
                                 session_id=session_id, user_id=user["id"])
    return RedirectResponse(f"/r/{rid}/chat?session_id={session_id}", status_code=302)


# ---------------------------------------------------------------- reply studio
@router.get("/r/{rid}/replies", response_class=HTMLResponse)
def replies_page(rid: int, request: Request, conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    membership, rest = _require_role(conn, user, rid, "viewer")
    # Reviews most worth a response: recent negatives without an approved draft.
    rows = analytics.fetch_scoped(conn, rid)
    candidates = []
    for r in rows:
        if r["sentiment"] in ("negative", "neutral"):
            full = rrepo_rev.get_review(conn, r["id"])
            drafts = drepo.list_drafts_for_review(conn, r["id"])
            approved = any(d["status"] == "approved" for d in drafts)
            candidates.append({"review": full, "drafts": drafts, "has_approved": approved})
    candidates = candidates[:25]
    return templates.TemplateResponse(request, "replies.html", _context(
        request, user, restaurant=rest, role=membership["role"], nav="replies",
        candidates=candidates,
    ))


@router.post("/reviews/{review_id}/draft")
def draft_generate(review_id: int, request: Request, tone: str = Form(default="professional"),
                   length: str = Form(default="medium"), conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    review = rrepo_rev.get_review(conn, review_id)
    _require_role(conn, user, review["restaurant_id"], "member")
    try:
        reply.generate_draft(conn, review_id, tone=tone, length=length, created_by=user["id"])
    except ValueError:
        pass
    return RedirectResponse(f"/reviews/{review_id}", status_code=302)


@router.post("/drafts/{draft_id}/approve")
def draft_approve(draft_id: int, request: Request,
                  conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    draft = drepo.get_draft(conn, draft_id)
    _require_role(conn, user, draft["restaurant_id"], "manager")
    reply.approve_draft(conn, draft_id, user["id"])
    orepo.audit(conn, actor_user_id=user["id"], restaurant_id=draft["restaurant_id"],
                action="draft.approve", resource_type="draft", resource_id=draft_id)
    return RedirectResponse(f"/reviews/{draft['review_id']}", status_code=302)


@router.post("/drafts/{draft_id}/edit")
def draft_edit(draft_id: int, request: Request, body: str = Form(...),
               conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    draft = drepo.get_draft(conn, draft_id)
    _require_role(conn, user, draft["restaurant_id"], "member")
    reply.edit_draft(conn, draft_id, body, user["id"])
    return RedirectResponse(f"/reviews/{draft['review_id']}", status_code=302)


# ---------------------------------------------------------------- alerts & actions
@router.get("/r/{rid}/alerts", response_class=HTMLResponse)
def alerts_page(rid: int, request: Request, conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    membership, rest = _require_role(conn, user, rid, "viewer")
    return templates.TemplateResponse(request, "alerts.html", _context(
        request, user, restaurant=rest, role=membership["role"], nav="alerts",
        alerts=orepo.list_alerts(conn, rid), actions=orepo.list_actions(conn, rid),
    ))


@router.post("/r/{rid}/alerts/detect")
def alerts_detect(rid: int, request: Request, conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    _require_role(conn, user, rid, "manager")
    alerts_svc.detect(conn, rid)
    return RedirectResponse(f"/r/{rid}/alerts", status_code=302)


@router.post("/alerts/{alert_id}/status")
def alert_status(alert_id: int, request: Request, new_status: str = Form(...),
                 conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    row = conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    _require_role(conn, user, row["restaurant_id"], "manager")
    if new_status in ("reviewed", "dismissed"):
        orepo.set_alert_status(conn, alert_id, new_status)
    return RedirectResponse(f"/r/{row['restaurant_id']}/alerts", status_code=302)


@router.post("/r/{rid}/actions")
def action_create(rid: int, request: Request, title: str = Form(...),
                  due_date: str | None = Form(default=None), conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    _require_role(conn, user, rid, "member")
    orepo.create_action(conn, restaurant_id=rid, title=title, description=None,
                        owner_user_id=user["id"], due_date=due_date or None, review_ids=[])
    return RedirectResponse(f"/r/{rid}/alerts", status_code=302)


@router.post("/actions/{action_id}/status")
def action_status(action_id: int, request: Request, new_status: str = Form(...),
                  conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    action = orepo.get_action(conn, action_id)
    _require_role(conn, user, action["restaurant_id"], "member")
    orepo.update_action(conn, action_id, status=new_status)
    return RedirectResponse(f"/r/{action['restaurant_id']}/alerts", status_code=302)


# ---------------------------------------------------------------- ops / developer
@router.get("/r/{rid}/report")
def web_report_json(rid: int, request: Request, conn: sqlite3.Connection = Depends(_get_db)):
    from fastapi.responses import JSONResponse
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    _require_role(conn, user, rid, "viewer")
    return JSONResponse(export.to_json(conn, rid))


@router.get("/r/{rid}/report.csv")
def web_report_csv(rid: int, request: Request, conn: sqlite3.Connection = Depends(_get_db)):
    from fastapi.responses import Response
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    _require_role(conn, user, rid, "viewer")
    return Response(export.to_csv(conn, rid), media_type="text/csv",
                    headers={"content-disposition": f'attachment; filename="report-{rid}.csv"'})


# ---------------------------------------------------------------- ops / developer
@router.get("/r/{rid}/ops", response_class=HTMLResponse)
def ops_page(rid: int, request: Request, conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    membership, rest = _require_role(conn, user, rid, "manager")
    return templates.TemplateResponse(request, "ops.html", _context(
        request, user, restaurant=rest, role=membership["role"], nav="ops",
        usage=orepo.usage_summary(conn, rid), audit=orepo.recent_audit(conn, rid, limit=30),
    ))


@router.get("/ops/evaluation", response_class=HTMLResponse)
def eval_page(request: Request, conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    runs = orepo.list_evaluations(conn)
    return templates.TemplateResponse(request, "evaluation.html", _context(
        request, user, nav="evaluation", runs=runs,
    ))


@router.post("/ops/evaluation/run")
def eval_run(request: Request, restaurant_id: int | None = Form(default=None),
             conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    evaluation.run_all(conn, restaurant_id=restaurant_id)
    return RedirectResponse("/ops/evaluation", status_code=302)


@router.post("/ops/seed-demo")
def seed(request: Request, conn: sqlite3.Connection = Depends(_get_db)):
    """Load the synthetic demo dataset (owners only, non-prod). Data is labeled
    is_synthetic so it is visibly distinguished from real reviews."""
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not settings.is_prod:
        seed_demo(conn)
    return RedirectResponse("/", status_code=302)


@router.post("/r/{rid}/analyze-pending")
def analyze_pending(rid: int, request: Request, conn: sqlite3.Connection = Depends(_get_db)):
    user = _me(request, conn)
    if not user:
        return RedirectResponse("/login", status_code=302)
    _require_role(conn, user, rid, "member")
    jobs.analyze_pending(conn, rid)
    return RedirectResponse(f"/r/{rid}/reviews", status_code=302)
