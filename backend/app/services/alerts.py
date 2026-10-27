"""Complaint alerts via deterministic statistical thresholds (not an LLM).

Threshold logic is explicit and documented; alerts require a minimum number of
observations so small-sample noise is not reported as a trend. A customer
complaint is never asserted to be a verified incident - alerts ask for review."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..repo import ops as orepo
from . import analytics

# Documented thresholds
MIN_OBSERVATIONS = 5          # per window, to evaluate a trend at all
RATING_DROP_THRESHOLD = 0.3   # avg star drop vs previous equal window
NEGATIVE_RISE_RATIO = 1.5     # current negatives >= 1.5x previous
ASPECT_RECURRENCE = 3         # >= N negative mentions of one aspect in window


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def detect(conn, restaurant_id: int, *, window_days: int = 14) -> list[dict]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cur_end = now
    cur_start = now - timedelta(days=window_days)
    prev_end = cur_start
    prev_start = cur_start - timedelta(days=window_days)
    created: list[dict] = []

    cur_rows = analytics.fetch_scoped(conn, restaurant_id,
                                      date_from=_iso(cur_start), date_to=_iso(cur_end))
    prev_rows = analytics.fetch_scoped(conn, restaurant_id,
                                       date_from=_iso(prev_start), date_to=_iso(prev_end))

    def _stat(rows):
        rated = [r["rating"] for r in rows if r["rating"] is not None]
        neg = sum(1 for r in rows if r["sentiment"] == "negative")
        return {"n": len(rows), "avg": (sum(rated) / len(rated)) if rated else None, "neg": neg}

    c, p = _stat(cur_rows), _stat(prev_rows)

    # 1. Declining average rating
    if c["n"] >= MIN_OBSERVATIONS and p["n"] >= MIN_OBSERVATIONS and c["avg"] and p["avg"]:
        drop = p["avg"] - c["avg"]
        if drop >= RATING_DROP_THRESHOLD:
            created.append(_upsert(conn, restaurant_id, rule="declining_rating", aspect=None,
                                   window=f"{window_days}d", severity="warning",
                                   metric={"current_avg": round(c["avg"], 2), "previous_avg": round(p["avg"], 2),
                                           "drop": round(drop, 2), "n_current": c["n"], "n_previous": p["n"]},
                                   message=f"Average rating fell {drop:.2f} stars vs the previous "
                                           f"{window_days} days. Investigate recent experiences."))

    # 2. Increasing negative-review volume
    if c["n"] >= MIN_OBSERVATIONS and p["neg"] > 0 and c["neg"] >= NEGATIVE_RISE_RATIO * p["neg"] \
            and c["neg"] - p["neg"] >= 2:
        created.append(_upsert(conn, restaurant_id, rule="rising_negative_volume", aspect=None,
                               window=f"{window_days}d", severity="warning",
                               metric={"current_neg": c["neg"], "previous_neg": p["neg"]},
                               message=f"Negative reviews rose from {p['neg']} to {c['neg']} "
                                       f"in the last {window_days} days."))

    # 3. Recurring aspect complaints within the window
    aspect_neg: dict[str, int] = {}
    for r in cur_rows:
        for a in r["aspect_results"]:
            if a.get("sentiment") == "negative":
                aspect_neg[a["aspect"]] = aspect_neg.get(a["aspect"], 0) + 1
    for aspect, count in aspect_neg.items():
        if count >= ASPECT_RECURRENCE:
            sev = "urgent" if aspect in ("food", "cleanliness") else "warning"
            created.append(_upsert(conn, restaurant_id, rule="recurring_aspect_complaint",
                                   aspect=aspect, window=f"{window_days}d", severity=sev,
                                   metric={"aspect": aspect, "negative_mentions": count},
                                   message=f"{count} negative {aspect} mentions in the last "
                                           f"{window_days} days - review before treating as confirmed."))
    return created


def _upsert(conn, restaurant_id, *, rule, aspect, window, severity, metric, message) -> dict:
    existing = orepo.alert_exists_recent(conn, restaurant_id, rule, aspect)
    if existing:
        # De-duplicate: keep the open alert rather than spamming a new one per run.
        return {**existing, "new": False}
    aid = orepo.add_alert(conn, restaurant_id=restaurant_id, rule=rule, aspect=aspect,
                          window=window, severity=severity, metric=metric, message=message)
    return {"id": aid, "rule": rule, "aspect": aspect, "severity": severity,
            "metric": metric, "message": message, "status": "open", "new": True}
