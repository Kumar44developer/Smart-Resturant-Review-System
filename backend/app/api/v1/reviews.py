from __future__ import annotations

import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from ...deps import current_user, enforce_role, get_db
from ...repo import analysis as arepo
from ...repo import reviews as rrepo
from ...schemas import ReviewIn, ReviewPatch
from ...services import analysis as analysis_svc
from ...services import jobs

router = APIRouter(tags=["reviews"])


def _load_review_scoped(conn, user, review_id, min_role):
    review = rrepo.get_review(conn, review_id)
    if not review:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    enforce_role(conn, user, review["restaurant_id"], min_role)
    return review


@router.get("/restaurants/{restaurant_id}/reviews")
def list_reviews(restaurant_id: int, user: dict = Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db),
                 q: str | None = None, sentiment: str | None = None, source: str | None = None,
                 rating_min: float | None = Query(default=None, ge=1, le=5),
                 rating_max: float | None = Query(default=None, ge=1, le=5),
                 date_from: str | None = None, date_to: str | None = None,
                 sort: str = "review_ts", order: str = "desc",
                 page: int = Query(default=1, ge=1), size: int = Query(default=20, ge=1, le=100)):
    enforce_role(conn, user, restaurant_id, "viewer")
    return rrepo.search(conn, restaurant_id, q=q, sentiment=sentiment, source=source,
                        rating_min=rating_min, rating_max=rating_max, date_from=date_from,
                        date_to=date_to, sort=sort, order=order, limit=size, offset=(page - 1) * size)


@router.post("/restaurants/{restaurant_id}/reviews", status_code=status.HTTP_201_CREATED)
def create_review(restaurant_id: int, body: ReviewIn, background: BackgroundTasks,
                  user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "member")
    if body.external_source_id and rrepo.duplicate_exists(conn, restaurant_id, body.source,
                                                          body.external_source_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Duplicate review for this source/external id")
    review = rrepo.create_review(conn, restaurant_id, body.review_text, rating=body.rating,
                                 source=body.source, external_source_id=body.external_source_id,
                                 author_name=body.author_name, review_ts=body.review_ts,
                                 language=body.language)
    background.add_task(_analyze_async, review["id"], user["id"])
    return review


def _analyze_async(review_id: int, user_id: int) -> None:
    from ... import db
    conn = db.connect()
    try:
        analysis_svc.analyze_review(conn, review_id, user_id=user_id)
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()


@router.get("/reviews/{review_id}")
def get_review(review_id: int, user: dict = Depends(current_user),
               conn: sqlite3.Connection = Depends(get_db)):
    review = _load_review_scoped(conn, user, review_id, "viewer")
    return {**review, "latest_analysis": arepo.latest_analysis(conn, review_id)}


@router.patch("/reviews/{review_id}")
def patch_review(review_id: int, body: ReviewPatch, user: dict = Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    _load_review_scoped(conn, user, review_id, "manager")
    updated = rrepo.update_review(conn, review_id, **body.model_dump(exclude_none=True))
    # editing review text makes prior analysis stale
    if body.review_text:
        rrepo.set_analysis_status(conn, review_id, "stale")
    return updated


@router.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_review(review_id: int, user: dict = Depends(current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    _load_review_scoped(conn, user, review_id, "manager")
    arepo.delete_embedding(conn, review_id)
    rrepo.delete_review(conn, review_id)


@router.post("/reviews/{review_id}/analyze")
def analyze(review_id: int, user: dict = Depends(current_user),
           conn: sqlite3.Connection = Depends(get_db)):
    _load_review_scoped(conn, user, review_id, "member")
    return analysis_svc.analyze_review(conn, review_id, user_id=user["id"])


@router.get("/reviews/{review_id}/analyses")
def analyses(review_id: int, user: dict = Depends(current_user),
             conn: sqlite3.Connection = Depends(get_db)):
    _load_review_scoped(conn, user, review_id, "viewer")
    return arepo.list_analyses(conn, review_id)


@router.post("/restaurants/{restaurant_id}/reviews/analyze-pending")
def analyze_pending(restaurant_id: int, background: BackgroundTasks,
                    user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    enforce_role(conn, user, restaurant_id, "member")
    background.add_task(_analyze_pending_async, restaurant_id)
    return {"queued": True}


def _analyze_pending_async(restaurant_id: int) -> None:
    from ... import db
    conn = db.connect()
    try:
        jobs.analyze_pending(conn, restaurant_id)
    finally:
        conn.close()
