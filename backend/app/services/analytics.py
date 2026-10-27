"""Analytics computed directly from stored rows (reviews + review_analyses).

Every figure here is aggregated from persisted data, not generated. Trend series
are suppressed when there are too few observations to be meaningful, and missing
values are never rendered as zero. See docs/PROJECT_REPORT.md."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

_MIN_TREND_POINTS = 2


def _window(date_from: str | None, date_to: str | None) -> tuple[list[str], list[Any]]:
    clause = ""
    params: list[Any] = []
    if date_from:
        clause += " AND COALESCE(r.review_ts, r.created_at) >= ?"; params.append(date_from)
    if date_to:
        clause += " AND COALESCE(r.review_ts, r.created_at) <= ?"; params.append(date_to)
    return clause, params


def fetch_scoped(conn: sqlite3.Connection, restaurant_id: int, *,
                 date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    clause, params = _window(date_from, date_to)
    sql = f"""SELECT r.id, r.rating, r.review_ts, r.created_at, r.source, r.analysis_status,
                     r.is_synthetic, la.sentiment, la.confidence, la.aspect_results, la.topics
              FROM reviews r
              LEFT JOIN (
                SELECT review_id, sentiment, confidence, aspect_results, topics,
                       ROW_NUMBER() OVER (PARTITION BY review_id ORDER BY analyzed_at DESC) rn
                FROM review_analyses WHERE status='done'
              ) la ON la.review_id = r.id AND la.rn = 1
              WHERE r.restaurant_id = ? {clause}
              ORDER BY COALESCE(r.review_ts, r.created_at)"""
    rows = conn.execute(sql, (restaurant_id, *params)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["aspect_results"] = json.loads(d.get("aspect_results") or "[]")
        d["topics"] = json.loads(d.get("topics") or "[]")
        out.append(d)
    return out


def _month(row: dict) -> str:
    ts = row.get("review_ts") or row.get("created_at") or ""
    return ts[:7] if len(ts) >= 7 else "unknown"


def overview(conn: sqlite3.Connection, restaurant_id: int, *, date_from=None, date_to=None) -> dict:
    rows = fetch_scoped(conn, restaurant_id, date_from=date_from, date_to=date_to)
    total = len(rows)
    rated = [r["rating"] for r in rows if r["rating"] is not None]
    avg_rating = round(sum(rated) / len(rated), 2) if rated else None
    rating_dist = {str(i): 0 for i in range(1, 6)}
    for r in rated:
        bucket = str(int(round(r)))
        rating_dist[bucket] = rating_dist.get(bucket, 0) + 1

    sent = Counter(r["sentiment"] for r in rows if r["sentiment"])
    analyzed = sum(1 for r in rows if r["sentiment"])
    pending = sum(1 for r in rows if r["analysis_status"] in ("pending", "processing"))
    failed = sum(1 for r in rows if r["analysis_status"] == "failed")

    volume = _volume_series(rows)
    return {
        "total_reviews": total,
        "average_rating": avg_rating,
        "rating_distribution": rating_dist,
        "sentiment_distribution": {
            "positive": sent.get("positive", 0),
            "neutral": sent.get("neutral", 0),
            "negative": sent.get("negative", 0),
        },
        "analyzed_reviews": analyzed,
        "review_volume_over_time": volume,
        "data_quality": {
            "pending": pending, "failed": failed, "analyzed": analyzed,
            "coverage_pct": round(100 * analyzed / total, 1) if total else 0.0,
            "synthetic_count": sum(1 for r in rows if r.get("is_synthetic")),
        },
    }


def _volume_series(rows: list[dict]) -> list[dict]:
    buckets: Counter[str] = Counter()
    for r in rows:
        buckets[_month(r)] += 1
    return [{"period": m, "count": c} for m, c in sorted(buckets.items()) if m != "unknown"]


def sentiment_trend(conn: sqlite3.Connection, restaurant_id: int, *, date_from=None, date_to=None) -> dict:
    rows = fetch_scoped(conn, restaurant_id, date_from=date_from, date_to=date_to)
    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"positive": 0, "neutral": 0, "negative": 0})
    for r in rows:
        if r["sentiment"]:
            agg[_month(r)][r["sentiment"]] += 1
    series = [
        {"period": m, **{k: v for k, v in agg[m].items()}, "total": sum(agg[m].values())}
        for m in sorted(agg) if m != "unknown"
    ]
    return {"enough_data": len(series) >= _MIN_TREND_POINTS, "series": series}


def rating_trend(conn: sqlite3.Connection, restaurant_id: int, *, date_from=None, date_to=None) -> dict:
    rows = fetch_scoped(conn, restaurant_id, date_from=date_from, date_to=date_to)
    by: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["rating"] is not None:
            by[_month(r)].append(r["rating"])
    series = [
        {"period": m, "avg_rating": round(sum(v) / len(v), 2), "count": len(v)}
        for m, v in sorted(by.items()) if m != "unknown"
    ]
    return {"enough_data": len(series) >= _MIN_TREND_POINTS, "series": series}


def aspect_analytics(conn: sqlite3.Connection, restaurant_id: int, *, date_from=None, date_to=None) -> dict:
    rows = fetch_scoped(conn, restaurant_id, date_from=date_from, date_to=date_to)
    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"positive": 0, "neutral": 0, "negative": 0})
    counts = 0
    for r in rows:
        for a in r["aspect_results"]:
            s = a.get("sentiment")
            if s in agg[a["aspect"]]:
                agg[a["aspect"]][s] += 1
                counts += 1
    aspects = [
        {"aspect": name, **mix, "total": sum(mix.values()),
         "net": mix["positive"] - mix["negative"]}
        for name, mix in agg.items()
    ]
    aspects.sort(key=lambda x: (-x["total"]))
    return {"aspect_mentions": counts, "aspects": aspects}


def topic_frequencies(conn: sqlite3.Connection, restaurant_id: int, *, date_from=None, date_to=None,
                      sentiment: str | None = None) -> list[dict]:
    rows = fetch_scoped(conn, restaurant_id, date_from=date_from, date_to=date_to)
    themes = Counter()
    for r in rows:
        if sentiment and r["sentiment"] != sentiment:
            continue
        for t in r["topics"]:
            themes[t] += 1
    return [{"theme": t, "count": c} for t, c in themes.most_common(20)]


def most_praised_themes(conn, restaurant_id, **kw) -> list[dict]:
    return topic_frequencies(conn, restaurant_id, sentiment="positive", **kw)


def most_frequent_complaints(conn, restaurant_id, **kw) -> list[dict]:
    return topic_frequencies(conn, restaurant_id, sentiment="negative", **kw)


def _window_stats(rows: list[dict]) -> dict:
    rated = [r["rating"] for r in rows if r["rating"] is not None]
    sent = Counter(r["sentiment"] for r in rows if r["sentiment"])
    neg = sum(len(r["topics"]) for r in rows if r["sentiment"] == "negative")
    return {
        "total": len(rows),
        "avg_rating": round(sum(rated) / len(rated), 2) if rated else None,
        "positive": sent.get("positive", 0),
        "negative": sent.get("negative", 0),
        "neutral": sent.get("neutral", 0),
        "complaint_mentions": neg,
    }


def period_compare(conn: sqlite3.Connection, restaurant_id: int, *,
                   date_from: str, date_to: str) -> dict:
    """Compare the selected window to the immediately preceding equal-length window."""
    start = datetime.fromisoformat(date_from)
    end = datetime.fromisoformat(date_to)
    span = end - start
    prev_start = start - span
    prev_end = start - timedelta(seconds=1)
    cur = fetch_scoped(conn, restaurant_id, date_from=start.isoformat(), date_to=end.isoformat())
    prev = fetch_scoped(conn, restaurant_id, date_from=prev_start.isoformat(), date_to=prev_end.isoformat())
    cur_s, prev_s = _window_stats(cur), _window_stats(prev)
    delta_rating = (
        round(cur_s["avg_rating"] - prev_s["avg_rating"], 2)
        if cur_s["avg_rating"] is not None and prev_s["avg_rating"] is not None else None
    )
    return {
        "current": cur_s, "previous": prev_s,
        "delta_avg_rating": delta_rating,
        "delta_volume": cur_s["total"] - prev_s["total"],
        "enough_data": cur_s["total"] > 0 and prev_s["total"] > 0,
    }


def location_compare(conn: sqlite3.Connection, restaurant_ids: list[int],
                     *, date_from=None, date_to=None) -> list[dict]:
    from ..repo import restaurants as rrepo
    out = []
    for rid in restaurant_ids:
        rest = rrepo.get_restaurant(conn, rid)
        rows = fetch_scoped(conn, rid, date_from=date_from, date_to=date_to)
        stats = _window_stats(rows)
        out.append({"restaurant_id": rid, "name": rest["name"] if rest else str(rid), **stats})
    out.sort(key=lambda x: (x["avg_rating"] is None, -(x["avg_rating"] or 0)))
    return out
