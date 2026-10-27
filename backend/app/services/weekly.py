"""Weekly digest assembled from stored analytics + operational state.

Every number is derived from persisted rows via the analytics/alerts services.
Nothing is invented; if a window has too little data the fields honestly report
insufficient_data rather than a fabricated trend. See docs/PROJECT_REPORT.md."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from . import alerts, analytics, recommendations


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def build(conn: sqlite3.Connection, restaurant_id: int, *, week_days: int = 7) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = now - timedelta(days=week_days)
    prev_start = start - timedelta(days=week_days)
    window = dict(date_from=_iso(start), date_to=_iso(now))
    prev_window = dict(date_from=_iso(prev_start), date_to=_iso(start))

    cur = analytics.overview(conn, restaurant_id, **window)
    prev = analytics.overview(conn, restaurant_id, **prev_window)

    cur_avg, prev_avg = cur["average_rating"], prev["average_rating"]
    rating_delta = round(cur_avg - prev_avg, 2) if (cur_avg is not None and prev_avg is not None) else None

    from ..repo import ops as orepo
    open_actions = [a for a in orepo.list_actions(conn, restaurant_id) if a["status"] == "open"]
    open_alerts = orepo.list_alerts(conn, restaurant_id, status="open")

    return {
        "restaurant_id": restaurant_id,
        "window_days": week_days,
        "period": {"from": _iso(start), "to": _iso(now)},
        "enough_data": cur["total_reviews"] > 0,
        "volume": {
            "this_period": cur["total_reviews"],
            "previous_period": prev["total_reviews"],
            "delta": cur["total_reviews"] - prev["total_reviews"],
        },
        "average_rating": {"this_period": cur_avg, "previous_period": prev_avg, "delta": rating_delta},
        "sentiment_distribution": cur["sentiment_distribution"],
        "top_complaints": analytics.most_frequent_complaints(conn, restaurant_id, **window)[:5],
        "top_praise": analytics.most_praised_themes(conn, restaurant_id, **window)[:5],
        "aspect_hotspots": analytics.aspect_analytics(conn, restaurant_id, **window)["aspects"][:5],
        "recommendation_count": len(recommendations.compute(conn, restaurant_id, persist=False)),
        "open_alerts": len(open_alerts),
        "open_actions": len(open_actions),
        "data_quality": cur["data_quality"],
        "generated_at": _iso(now),
    }
