"""Review CRUD + analysis integration tests."""
from __future__ import annotations


def _create(client, headers, rid, text, rating=None, external=None, source="manual"):
    body = {"review_text": text, "source": source}
    if rating is not None:
        body["rating"] = rating
    if external:
        body["external_source_id"] = external
    return client.post(f"/api/v1/restaurants/{rid}/reviews", headers=headers, json=body)


def test_create_triggers_analysis_with_mixed_aspects(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    r = _create(client, headers, rid,
                "The food was delicious and the staff were friendly, but the service was slow.",
                rating=4)
    assert r.status_code == 201
    review = client.get(f"/api/v1/reviews/{r.json()['id']}", headers=headers).json()
    la = review["latest_analysis"]
    assert la and la["status"] == "done"
    aspects = {a["aspect"]: a["sentiment"] for a in la["aspect_results"]}
    assert aspects.get("food") == "positive"
    assert aspects.get("service") == "negative"


def test_duplicate_external_id_conflict(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    a = _create(client, headers, rid, "Great pasta", external="rev-123", source="google")
    assert a.status_code == 201
    b = _create(client, headers, rid, "Great pasta again", external="rev-123", source="google")
    assert b.status_code == 409


def test_full_text_search(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    _create(client, headers, rid, "The tiramisu dessert was heavenly and fresh")
    _create(client, headers, rid, "Terrible cold soup, never coming back")
    res = client.get(f"/api/v1/restaurants/{rid}/reviews", headers=headers,
                     params={"q": "tiramisu"}).json()
    assert res["total"] >= 1
    assert all("tiramisu" in it["review_text"].lower() for it in res["items"])


def test_sentiment_filter(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    _create(client, headers, rid, "Amazing wonderful delicious food", rating=5)
    _create(client, headers, rid, "Awful terrible rude staff", rating=1)
    neg = client.get(f"/api/v1/restaurants/{rid}/reviews", headers=headers,
                     params={"sentiment": "negative"}).json()
    assert neg["total"] >= 1
    assert all(it["sentiment"] == "negative" for it in neg["items"])


def test_edit_marks_analysis_stale(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    rid_ = _create(client, headers, rid, "Nice food", rating=4).json()["id"]
    # owner has role 'owner' (>= manager) so patch is allowed
    patch = client.patch(f"/api/v1/reviews/{rid_}", headers=headers,
                         json={"review_text": "Completely changed text about service"})
    assert patch.status_code == 200
    got = client.get(f"/api/v1/reviews/{rid_}", headers=headers).json()
    assert got["analysis_status"] == "stale"


def test_manual_analyze_endpoint(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    _ = _create(client, headers, rid, "The waiting time was extremely long and frustrating", rating=2)
    # analyze-pending should process any pending/stale/failed rows
    q = client.post(f"/api/v1/restaurants/{rid}/reviews/analyze-pending", headers=headers)
    assert q.status_code == 200 and q.json()["queued"] is True
