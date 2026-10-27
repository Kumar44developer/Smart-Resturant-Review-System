"""Evidence-backed recommendations, derived deterministically from stored
analytics. Each recommendation links the theme, supporting review IDs and count.
Measured trends stay separate from generated interpretation (docs/AI_DESIGN.md)."""
from __future__ import annotations

import sqlite3

from ..repo import ops as orepo
from . import analytics


def _action_for_aspect(aspect: str, sentiment: str) -> str:
    map_ = {
        "waiting_time": "Review staffing levels and order throughput during peak hours.",
        "service": "Coach front-of-house service standards and follow up on slow orders.",
        "delivery": "Audit delivery partner timing and order packaging integrity.",
        "pricing": "Re-examine menu pricing/value vs competitors for flagged items.",
        "portion": "Standardize portion sizing for dishes flagged as too small.",
        "cleanliness": "Increase cleaning frequency and restroom/tables checks.",
        "food": "Investigate quality consistency on the dishes customers disliked.",
        "staff": "Address reported staff behaviour through training/1:1s.",
        "ambience": "Assess noise level and seating comfort.",
        "overall": "Follow up on overall experience drivers with recent guests.",
    }
    return map_.get(aspect, "Investigate the recurring complaint theme.")


def compute(conn: sqlite3.Connection, restaurant_id: int, *, persist: bool = True,
            min_support: int = 2) -> list[dict]:
    aspects = analytics.aspect_analytics(conn, restaurant_id)["aspects"]
    rows = analytics.fetch_scoped(conn, restaurant_id)

    # Map each negatively-mentioned aspect to the reviews that support it.
    support: dict[str, list[int]] = {}
    for r in rows:
        for a in r["aspect_results"]:
            if a.get("sentiment") == "negative":
                support.setdefault(a["aspect"], []).append(r["id"])

    recs: list[dict] = []
    for aspect_mix in aspects:
        aspect = aspect_mix["aspect"]
        ids = support.get(aspect, [])
        if len(ids) < min_support:
            continue
        ratio = len(ids) / len(rows) if rows else 0
        rec = {
            "proposed_action": _action_for_aspect(aspect, "negative"),
            "supporting_theme": f"{aspect} complaints",
            "supporting_review_ids": ids[:20],
            "support_count": len(ids),
            "priority_rationale": (
                f"{len(ids)} negative {aspect} mentions ({ratio:.0%} of reviews in scope). "
                "Prioritized by frequency of supporting evidence."
            ),
            "uncertainty": (
                "Correlation with dissatisfaction only; no causal or revenue impact is measured."
            ),
        }
        recs.append(rec)
        if persist:
            orepo.add_recommendation(conn, restaurant_id=restaurant_id, **rec)
    recs.sort(key=lambda x: -x["support_count"])
    return recs


def list_persisted(conn: sqlite3.Connection, restaurant_id: int) -> list[dict]:
    return orepo.list_recommendations(conn, restaurant_id)
