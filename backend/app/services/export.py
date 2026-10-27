"""Exportable reports (JSON + CSV) built from live analytics queries."""
from __future__ import annotations

import csv
import io

from . import analytics, recommendations


def report_dict(conn, restaurant_id: int, *, date_from=None, date_to=None) -> dict:
    return {
        "overview": analytics.overview(conn, restaurant_id, date_from=date_from, date_to=date_to),
        "aspect_analytics": analytics.aspect_analytics(conn, restaurant_id, date_from=date_from, date_to=date_to),
        "top_complaints": analytics.most_frequent_complaints(conn, restaurant_id),
        "top_praise": analytics.most_praised_themes(conn, restaurant_id),
        "recommendations": recommendations.compute(conn, restaurant_id, persist=False),
    }


def to_json(conn, restaurant_id: int, **kw) -> dict:
    return report_dict(conn, restaurant_id, **kw)


def to_csv(conn, restaurant_id: int, **kw) -> str:
    data = report_dict(conn, restaurant_id, **kw)
    buf = io.StringIO()
    w = csv.writer(buf)
    ov = data["overview"]
    w.writerow(["metric", "value"])
    w.writerow(["total_reviews", ov["total_reviews"]])
    w.writerow(["average_rating", ov["average_rating"]])
    for s, c in ov["sentiment_distribution"].items():
        w.writerow([f"sentiment_{s}", c])
    w.writerow([])
    w.writerow(["aspect", "positive", "neutral", "negative", "net"])
    for a in data["aspect_analytics"]["aspects"]:
        w.writerow([a["aspect"], a["positive"], a["neutral"], a["negative"], a["net"]])
    w.writerow([])
    w.writerow(["recommendation", "support_count", "theme"])
    for r in data["recommendations"]:
        w.writerow([r["proposed_action"], r["support_count"], r["supporting_theme"]])
    return buf.getvalue()
