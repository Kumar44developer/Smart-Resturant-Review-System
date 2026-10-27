"""Reply Studio: drafts are labeled AI, require human approval, and are never auto-published."""
from __future__ import annotations

import uuid


def _neg_review(client, headers, rid):
    return client.post(f"/api/v1/restaurants/{rid}/reviews", headers=headers, json={
        "review_text": "Terrible service and the food was cold. Rude staff.", "rating": 1}).json()["id"]


def test_draft_is_ai_labeled_and_starts_as_draft(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    review_id = _neg_review(client, headers, rid)
    d = client.post(f"/api/v1/reviews/{review_id}/drafts", headers=headers,
                    json={"tone": "empathetic", "length": "medium"})
    assert d.status_code == 201
    body = d.json()
    assert body["is_ai_generated"] == 1
    assert body["status"] == "draft"


def test_draft_grounded_in_analysis_even_if_missing(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    review_id = _neg_review(client, headers, rid)
    d = client.post(f"/api/v1/reviews/{review_id}/drafts", headers=headers, json={}).json()
    # The reply references the complaint aspects (service/food/staff) from real analysis.
    assert any(w in d["body"].lower() for w in ["service", "food", "staff"])


def test_approval_requires_manager(client, owner_with_restaurant, make_user):
    headers, rid, _ = owner_with_restaurant
    review_id = _neg_review(client, headers, rid)
    draft = client.post(f"/api/v1/reviews/{review_id}/drafts", headers=headers, json={}).json()
    # add a member (not manager) and a viewer
    mh, muser = make_user("Member")
    client.post(f"/api/v1/restaurants/{rid}/members", headers=headers,
                json={"email": muser["email"], "role": "member"})
    # member can generate but NOT approve
    vemail = f"v-{uuid.uuid4().hex[:8]}@t.local"
    vh = client.post("/api/v1/auth/register",
                     json={"name": "V", "email": vemail, "password": "password123"}).json()
    client.post(f"/api/v1/restaurants/{rid}/members", headers=headers,
                json={"email": vh["email"], "role": "viewer"})
    vhdr = {"Authorization": f"Bearer {vh['token']}"}
    assert client.post(f"/api/v1/drafts/{draft['id']}/approve", headers=vhdr).status_code == 403
    # owner (manager+) can approve
    ok = client.post(f"/api/v1/drafts/{draft['id']}/approve", headers=headers)
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert "not" in ok.json()["note"].lower() or "manual" in ok.json()["note"].lower()


def test_rejected_draft_cannot_be_approved(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    review_id = _neg_review(client, headers, rid)
    draft = client.post(f"/api/v1/reviews/{review_id}/drafts", headers=headers, json={}).json()
    client.post(f"/api/v1/drafts/{draft['id']}/reject", headers=headers)
    assert client.post(f"/api/v1/drafts/{draft['id']}/approve", headers=headers).status_code == 409


def test_edit_marks_draft_edited(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    review_id = _neg_review(client, headers, rid)
    draft = client.post(f"/api/v1/reviews/{review_id}/drafts", headers=headers, json={}).json()
    e = client.patch(f"/api/v1/drafts/{draft['id']}", headers=headers,
                     json={"body": "Our own human-written apology and remediation."})
    assert e.status_code == 200 and e.json()["status"] == "edited"
