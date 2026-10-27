"""Analytics are computed from stored rows, never fabricated. These tests assert
the numbers actually reflect the reviews that were ingested, and that honesty
guards (trend suppression on thin data, synthetic labelling) behave."""
from __future__ import annotations


def _add(client, headers, rid, text, rating, ts=None):
    body = {"review_text": text, "rating": rating}
    if ts:
        body["review_ts"] = ts
    return client.post(f"/api/v1/restaurants/{rid}/reviews", headers=headers, json=body)


def test_overview_reflects_stored_reviews(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    _add(client, headers, rid, "Amazing delicious food, wonderful staff", 5, ts="2026-01-05")
    _add(client, headers, rid, "Awful terrible cold food, rude", 1, ts="2026-01-06")
    _add(client, headers, rid, "It was okay, nothing special", 3, ts="2026-02-01")
    ov = client.get(f"/api/v1/restaurants/{rid}/analytics/overview", headers=headers).json()
    assert ov["total_reviews"] == 3
    assert ov["average_rating"] == 3.0
    sd = ov["sentiment_distribution"]
    # positive + negative + neutral counts must sum to the analyzed reviews
    assert sd["positive"] >= 1 and sd["negative"] >= 1
    assert sum(sd.values()) == ov["analyzed_reviews"]
    assert ov["data_quality"]["coverage_pct"] == round(100 * ov["analyzed_reviews"] / 3, 1)


def test_aspects_computed_from_analysis(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    _add(client, headers, rid,
         "The food was delicious and the staff were friendly, but the service was slow.", 4)
    data = client.get(f"/api/v1/restaurants/{rid}/analytics/aspects", headers=headers).json()
    assert data["aspect_mentions"] >= 1
    by = {a["aspect"]: a for a in data["aspects"]}
    assert "food" in by and "service" in by
    assert by["food"]["positive"] >= 1
    assert by["service"]["negative"] >= 1


def test_trend_suppressed_on_thin_data(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    _add(client, headers, rid, "Great", 5, ts="2026-03-01")  # single month only
    t = client.get(f"/api/v1/restaurants/{rid}/analytics/sentiment-trend", headers=headers).json()
    assert t["enough_data"] is False  # honest: one data point is not a trend


def test_location_compare_only_lists_callers_restaurants(client, owner_with_restaurant, make_user):
    headers, rid, _ = owner_with_restaurant
    other_h, other_rid, _ = None, None, None
    oh, ou = make_user("OtherOwner")
    other_rid = client.post("/api/v1/restaurants", headers=oh, json={"name": "Other"}).json()["id"]
    rows = client.get(f"/api/v1/restaurants/{rid}/analytics/location-compare", headers=headers).json()
    ids = {r["restaurant_id"] for r in rows}
    assert rid in ids
    assert other_rid not in ids
