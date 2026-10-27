"""Analytics endpoints. Every figure is computed from stored review rows via the
analytics service - nothing here is fabricated or generated. Endpoints are scoped
to a restaurant and require at least the viewer role (tenant isolation)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from ...deps import current_user, enforce_role, get_db
from ...repo import restaurants as rrepo
from ...services import analytics

router = APIRouter(tags=["analytics"])


def _scoped(conn, user, restaurant_id, min_role="viewer"):
    enforce_role(conn, user, restaurant_id, min_role)
    return restaurant_id


@router.get("/restaurants/{restaurant_id}/analytics/overview")
def overview(restaurant_id: int, date_from: str | None = None, date_to: str | None = None,
             user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _scoped(conn, user, restaurant_id)
    return analytics.overview(conn, restaurant_id, date_from=date_from, date_to=date_to)


@router.get("/restaurants/{restaurant_id}/analytics/sentiment-trend")
def sentiment_trend(restaurant_id: int, date_from: str | None = None, date_to: str | None = None,
                    user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _scoped(conn, user, restaurant_id)
    return analytics.sentiment_trend(conn, restaurant_id, date_from=date_from, date_to=date_to)


@router.get("/restaurants/{restaurant_id}/analytics/rating-trend")
def rating_trend(restaurant_id: int, date_from: str | None = None, date_to: str | None = None,
                 user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _scoped(conn, user, restaurant_id)
    return analytics.rating_trend(conn, restaurant_id, date_from=date_from, date_to=date_to)


@router.get("/restaurants/{restaurant_id}/analytics/aspects")
def aspects(restaurant_id: int, date_from: str | None = None, date_to: str | None = None,
            user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _scoped(conn, user, restaurant_id)
    return analytics.aspect_analytics(conn, restaurant_id, date_from=date_from, date_to=date_to)


@router.get("/restaurants/{restaurant_id}/analytics/themes")
def themes(restaurant_id: int, sentiment: str | None = None,
           date_from: str | None = None, date_to: str | None = None,
           user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _scoped(conn, user, restaurant_id)
    return analytics.topic_frequencies(conn, restaurant_id, sentiment=sentiment,
                                       date_from=date_from, date_to=date_to)


@router.get("/restaurants/{restaurant_id}/analytics/period-compare")
def period_compare(restaurant_id: int, date_from: str = Query(...), date_to: str = Query(...),
                   user: dict = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _scoped(conn, user, restaurant_id)
    return analytics.period_compare(conn, restaurant_id, date_from=date_from, date_to=date_to)


@router.get("/restaurants/{restaurant_id}/analytics/location-compare")
def location_compare(restaurant_id: int, user: dict = Depends(current_user),
                     conn: sqlite3.Connection = Depends(get_db)):
    """Compare the caller's own restaurants. Only locations the user can view are
    ever included, so cross-tenant leakage is impossible by construction."""
    _scoped(conn, user, restaurant_id)
    owned = [r["id"] for r in rrepo.list_restaurants_for_user(conn, user["id"])]
    return analytics.location_compare(conn, owned)
