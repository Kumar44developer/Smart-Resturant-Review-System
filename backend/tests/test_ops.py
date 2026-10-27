"""Operational endpoints: actions (incl. the status-patch regression), alerts,
recommendations, weekly digest, reports, usage & audit — all tenant-scoped."""
from __future__ import annotations


def _review(client, headers, rid, text="Terrible slow service and cold food", rating=1):
    return client.post(f"/api/v1/restaurants/{rid}/reviews", headers=headers,
                       json={"review_text": text, "rating": rating}).json()["id"]


def test_action_create_and_status_lifecycle(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    review_id = _review(client, headers, rid)
    created = client.post(f"/api/v1/restaurants/{rid}/actions", headers=headers,
                          json={"title": "Fix wait times", "review_ids": [review_id]})
    assert created.status_code == 201
    action = created.json()
    assert action["status"] == "open"
    assert review_id in action["review_ids"]

    # valid transition (matches the stored CHECK constraint)
    ok = client.patch(f"/api/v1/actions/{action['id']}", headers=headers,
                      json={"status": "completed", "resolution_note": "Added a till"})
    assert ok.status_code == 200 and ok.json()["status"] == "completed"

    # a value outside the stored constraint must be rejected at validation (422),
    # never reach the DB and blow up as a 500. This guards the ActionPatch schema.
    bad = client.patch(f"/api/v1/actions/{action['id']}", headers=headers,
                       json={"status": "done"})
    assert bad.status_code == 422


def test_action_cannot_link_foreign_review(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    # a review belonging to a different restaurant
    other_email = f"x-{rid}-other@t.local"
    other = client.post("/api/v1/auth/register",
                        json={"name": "X", "email": other_email, "password": "password123"}).json()
    oh = {"Authorization": f"Bearer {other['token']}"}
    other_rid = client.post("/api/v1/restaurants", headers=oh, json={"name": "Other"}).json()["id"]
    foreign_review = _review(client, oh, other_rid)

    resp = client.post(f"/api/v1/restaurants/{rid}/actions", headers=headers,
                       json={"title": "sneaky", "review_ids": [foreign_review]})
    assert resp.status_code == 400  # cross-tenant link refused


def test_recommendations_are_evidence_backed(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    for _ in range(3):
        _review(client, headers, rid, "The service was painfully slow and the food was cold", 1)
    computed = client.post(f"/api/v1/restaurants/{rid}/recommendations/compute", headers=headers)
    assert computed.status_code == 200
    recs = computed.json()
    assert len(recs) >= 1
    assert recs[0]["support_count"] >= 2
    assert recs[0]["supporting_review_ids"]  # every rec links real reviews
    listed = client.get(f"/api/v1/restaurants/{rid}/recommendations", headers=headers).json()
    assert len(listed) >= 1


def test_weekly_and_reports(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    _review(client, headers, rid, "Great food, lovely staff", 5)
    wk = client.get(f"/api/v1/restaurants/{rid}/weekly", headers=headers)
    assert wk.status_code == 200 and "generated_at" in wk.json()
    rep = client.get(f"/api/v1/restaurants/{rid}/report", headers=headers)
    assert rep.status_code == 200 and "overview" in rep.json()
    csv = client.get(f"/api/v1/restaurants/{rid}/report.csv", headers=headers)
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert "total_reviews" in csv.text


def test_usage_and_audit_require_manager(client, owner_with_restaurant, make_user):
    headers, rid, _ = owner_with_restaurant
    # manager+ can view usage/audit
    assert client.get(f"/api/v1/restaurants/{rid}/usage", headers=headers).status_code == 200
    aud = client.get(f"/api/v1/restaurants/{rid}/audit", headers=headers)
    assert aud.status_code == 200
    # a viewer cannot
    vh, viewer = make_user("Viewer")
    client.post(f"/api/v1/restaurants/{rid}/members", headers=headers,
                json={"email": viewer["email"], "role": "viewer"})
    assert client.get(f"/api/v1/restaurants/{rid}/usage", headers=vh).status_code == 403


def test_alert_detect_and_triage(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    for _ in range(4):
        _review(client, headers, rid, "Awful service, long waiting time, rude staff", 1)
    det = client.post(f"/api/v1/restaurants/{rid}/alerts/detect", headers=headers,
                      params={"window_days": 120})
    assert det.status_code == 200 and "detected" in det.json()
    alerts = client.get(f"/api/v1/restaurants/{rid}/alerts", headers=headers).json()
    if alerts:  # detection is data-dependent; triage whatever exists
        aid = alerts[0]["id"]
        assert client.post(f"/api/v1/alerts/{aid}/review", headers=headers).status_code == 200


def test_usage_accounts_for_chat_and_draft_operations(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    review_id = _review(client, headers, rid, "The food was great but service was slow", 3)
    before = client.get(f"/api/v1/restaurants/{rid}/usage", headers=headers).json()["operations"]
    # one RAG question and one reply draft each record a usage row for this tenant
    client.post(f"/api/v1/restaurants/{rid}/chat", headers=headers,
                json={"question": "what do people say about the food?"})
    client.post(f"/api/v1/reviews/{review_id}/drafts", headers=headers, json={})
    after = client.get(f"/api/v1/restaurants/{rid}/usage", headers=headers).json()
    assert after["operations"] - before >= 2
    # demo provider records no real tokens, so cost must stay honest (0, not invented)
    assert after["cost_field"] == "estimated_cost_micros"
    assert after["cost_micros"] == 0

