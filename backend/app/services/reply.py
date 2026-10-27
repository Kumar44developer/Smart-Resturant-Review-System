"""Reply Studio service: AI drafting + human edit/approval. Never auto-publishes."""
from __future__ import annotations

import time

from ..ai.base import ReviewContext
from ..ai.provider import get_provider
from ..repo import analysis as arepo
from ..repo import drafts as drepo
from ..repo import restaurants as rrepo
from ..repo import reviews as rrepo_rev
from . import ai_usage
from . import analysis as analysis_svc

TONES = {"professional", "friendly", "empathetic", "concise"}


def generate_draft(conn, review_id: int, *, tone: str = "professional", length: str = "medium",
                   created_by: int | None = None) -> dict:
    if tone not in TONES:
        raise ValueError(f"unsupported tone '{tone}'")
    review = rrepo_rev.get_review(conn, review_id)
    if not review:
        raise ValueError("review not found")
    # Drafting is grounded in an actual aspect analysis; run one if missing.
    la = arepo.latest_analysis(conn, review_id)
    if not la:
        analysis_svc.analyze_review(conn, review_id, user_id=created_by, operation="pre_draft_analysis")
        la = arepo.latest_analysis(conn, review_id)
    rest = rrepo.get_restaurant(conn, review["restaurant_id"])
    ctx = ReviewContext(
        review_id=review["id"], text=review["review_text"], rating=review["rating"],
        source=review["source"], aspects=(la["aspect_results"] if la else []),
        restaurant_name=rest["name"] if rest else "", restaurant_context=rest.get("description"),
    )
    provider = get_provider()
    started = time.perf_counter()
    body = provider.draft_reply(ctx, tone, length)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    meta = provider.meta()
    draft = drepo.create_draft(
        conn, review_id, review["restaurant_id"], body, tone,
        provider=meta.provider, model_id=meta.model_id, length=length,
        created_by=created_by, is_ai_generated=1,
    )
    # Label demo output so the UI can mark it explicitly.
    draft["is_demo"] = meta.is_demo
    ai_usage.record(conn, provider, "reply_draft",
                    restaurant_id=review["restaurant_id"], user_id=created_by,
                    measured_ms=elapsed_ms)
    return draft


def edit_draft(conn, draft_id: int, body: str, editor_id: int) -> dict | None:
    return drepo.update_body(conn, draft_id, body, editor_id)


def approve_draft(conn, draft_id: int, approver_id: int) -> dict | None:
    return drepo.set_status(conn, draft_id, "approved", approver_id=approver_id)


def reject_draft(conn, draft_id: int) -> dict | None:
    return drepo.set_status(conn, draft_id, "rejected")


def drafts_for_review(conn, review_id: int) -> list[dict]:
    return drepo.list_drafts_for_review(conn, review_id)
