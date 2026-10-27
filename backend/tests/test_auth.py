"""Auth + RBAC integration tests."""
from __future__ import annotations

import uuid


def test_register_login_and_me(client):
    email = f"auth-{uuid.uuid4().hex[:8]}@test.local"
    r = client.post("/api/v1/auth/register",
                    json={"name": "Auth", "email": email, "password": "password123"})
    assert r.status_code == 201
    tok = r.json()["token"]
    me = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200 and me.json()["email"] == email

    # login again
    li = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    assert li.status_code == 200 and "token" in li.json()


def test_duplicate_email_rejected(client):
    email = f"dup-{uuid.uuid4().hex[:8]}@test.local"
    body = {"name": "A", "email": email, "password": "password123"}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    assert client.post("/api/v1/auth/register", json=body).status_code == 409


def test_weak_password_rejected_by_schema(client):
    email = f"weak-{uuid.uuid4().hex[:8]}@test.local"
    r = client.post("/api/v1/auth/register", json={"name": "W", "email": email, "password": "short"})
    assert r.status_code == 422  # min_length=8 enforced


def test_login_wrong_password_is_401(client):
    email = f"bad-{uuid.uuid4().hex[:8]}@test.local"
    client.post("/api/v1/auth/register", json={"name": "B", "email": email, "password": "password123"})
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert r.status_code == 401


def test_protected_route_requires_auth(client):
    # session-scoped client may hold a cookie from earlier tests; clear it
    client.cookies.clear()
    assert client.get("/api/v1/restaurants").status_code == 401
    assert client.get("/api/v1/restaurants/1/reviews").status_code == 401


def test_role_hierarchy_enforced(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    # viewer invited by owner cannot add members (requires owner)
    vh, viewer = client.post("/api/v1/auth/register",
                             json={"name": "V", "email": f"v-{uuid.uuid4().hex[:8]}@t.local",
                                   "password": "password123"}).json(), None
    # add viewer as 'viewer' role
    ok = client.post(f"/api/v1/restaurants/{rid}/members", headers=headers,
                     json={"email": vh["email"], "role": "viewer"})
    assert ok.status_code == 201
    vhdr = {"Authorization": f"Bearer {vh['token']}"}
    # viewer can read
    assert client.get(f"/api/v1/restaurants/{rid}", headers=vhdr).status_code == 200
    # viewer cannot create a review (needs member)
    r = client.post(f"/api/v1/restaurants/{rid}/reviews", headers=vhdr,
                    json={"review_text": "nope", "rating": 5})
    assert r.status_code == 403
