"""Conversational analytics (RAG) + Reply Studio endpoints.

Honesty controls enforced here:
- Retrieval/answer is always scoped to a restaurant the caller can access.
- The chat question is treated as untrusted and length-bounded; prompt-injection
  in review content is handled inside the provider/answer path (abstention +
  citation validation), never by trusting model output.
- Drafts are ALWAYS labeled AI-generated and require explicit human approval;
  no endpoint here publishes anything externally."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ...deps import current_user, enforce_role, get_db
from ...repo import conversations as crepo
from ...repo import drafts as drepo
from ...repo import ops as orepo
from ...repo import reviews as rrepo
from ...schemas import ChatIn, DraftEdit, DraftIn
from ...services import guards, rag, reply

router = APIRouter(tags=["ai"])


# ---- Conversational analytics (RAG) ----

@router.post("/restaurants/{restaurant_id}/chat/sessions", status_code=status.HTTP_201_CREATED)
def create_session(restaurant_id: int, user: dict = Depends(current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "viewer")
    return crepo.create_session(conn, user["id"], restaurant_id)


@router.get("/chat/sessions")
def list_sessions(user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return crepo.list_sessions_for_user(conn, user["id"])


@router.get("/chat/sessions/{session_id}/messages")
def session_messages(session_id: int, user: dict = Depends(current_user),
                     conn: sqlite3.Connection = Depends(get_db)):
    session = crepo.get_session(conn, session_id)
    if not session or session["user_id"] != user["id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    enforce_role(conn, user, session["restaurant_id"], "viewer")
    msgs = []
    for m in crepo.list_messages(conn, session_id):
        msgs.append({**m, "citations": crepo.citations_for_message(conn, m["id"])})
    return msgs


@router.post("/restaurants/{restaurant_id}/chat")
def ask(restaurant_id: int, body: ChatIn, user: dict = Depends(current_user),
        conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "viewer")
    guards.rate_limit(f"chat:{user['id']}")
    question = guards.sanitize_text(body.question, limit=1000)
    if not question:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Question is empty after sanitization")

    session_id = body.session_id
    if session_id is not None:
        session = crepo.get_session(conn, session_id)
        if not session or session["user_id"] != user["id"] or session["restaurant_id"] != restaurant_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "session_id does not belong to this user/restaurant")

    history = None
    if session_id is not None:
        prior = crepo.list_messages(conn, session_id)[-6:]
        history = [{"role": m["role"], "content": m["content"]} for m in prior]

    result = rag.answer_question(conn, restaurant_id=restaurant_id, question=question,
                                 filters=body.filters, session_id=session_id,
                                 user_id=user["id"], history=history)
    orepo.audit(conn, actor_user_id=user["id"], restaurant_id=restaurant_id,
                action="chat.ask", resource_type="restaurant", resource_id=restaurant_id,
                metadata={"abstain": result["abstain"], "citations": len(result["citations"])})
    return result


# ---- Reply Studio ----

def _review_scoped(conn, user, review_id, min_role):
    review = rrepo.get_review(conn, review_id)
    if not review:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    enforce_role(conn, user, review["restaurant_id"], min_role)
    return review


@router.post("/reviews/{review_id}/drafts", status_code=status.HTTP_201_CREATED)
def generate_draft(review_id: int, body: DraftIn, user: dict = Depends(current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    _review_scoped(conn, user, review_id, "member")
    guards.rate_limit(f"draft:{user['id']}")
    try:
        draft = reply.generate_draft(conn, review_id, tone=body.tone, length=body.length,
                                     created_by=user["id"])
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    orepo.audit(conn, actor_user_id=user["id"], restaurant_id=draft["restaurant_id"],
                action="draft.generate", resource_type="draft", resource_id=draft["id"],
                metadata={"tone": body.tone, "is_demo": draft.get("is_demo")})
    return draft


@router.get("/reviews/{review_id}/drafts")
def list_drafts(review_id: int, user: dict = Depends(current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    _review_scoped(conn, user, review_id, "viewer")
    return reply.drafts_for_review(conn, review_id)


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: int, user: dict = Depends(current_user),
              conn: sqlite3.Connection = Depends(get_db)):
    draft = drepo.get_draft(conn, draft_id)
    if not draft:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    enforce_role(conn, user, draft["restaurant_id"], "viewer")
    return draft


@router.patch("/drafts/{draft_id}")
def edit_draft(draft_id: int, body: DraftEdit, user: dict = Depends(current_user),
               conn: sqlite3.Connection = Depends(get_db)):
    draft = drepo.get_draft(conn, draft_id)
    if not draft:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    enforce_role(conn, user, draft["restaurant_id"], "member")
    updated = reply.edit_draft(conn, draft_id, guards.sanitize_text(body.body, limit=4000), user["id"])
    orepo.audit(conn, actor_user_id=user["id"], restaurant_id=draft["restaurant_id"],
                action="draft.edit", resource_type="draft", resource_id=draft_id)
    return updated


@router.post("/drafts/{draft_id}/approve")
def approve_draft(draft_id: int, user: dict = Depends(current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    """Mark a draft approved for eventual manual sending. This records human sign-off
    only - it does NOT transmit anything to any external platform."""
    draft = drepo.get_draft(conn, draft_id)
    if not draft:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    enforce_role(conn, user, draft["restaurant_id"], "manager")
    if draft["status"] in ("rejected",):
        raise HTTPException(status.HTTP_409_CONFLICT, "Rejected drafts cannot be approved; create a new draft")
    updated = reply.approve_draft(conn, draft_id, user["id"])
    orepo.audit(conn, actor_user_id=user["id"], restaurant_id=draft["restaurant_id"],
                action="draft.approve", resource_type="draft", resource_id=draft_id)
    return {**updated, "note": "Approved for manual review/sending. Nothing was published automatically."}


@router.post("/drafts/{draft_id}/reject")
def reject_draft(draft_id: int, user: dict = Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    draft = drepo.get_draft(conn, draft_id)
    if not draft:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    enforce_role(conn, user, draft["restaurant_id"], "manager")
    updated = reply.reject_draft(conn, draft_id)
    orepo.audit(conn, actor_user_id=user["id"], restaurant_id=draft["restaurant_id"],
                action="draft.reject", resource_type="draft", resource_id=draft_id)
    return updated
