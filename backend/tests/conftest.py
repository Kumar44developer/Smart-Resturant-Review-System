"""Pytest fixtures.

A single throwaway SQLite file is used for the whole session; each test creates
users/restaurants with unique emails so tests stay independent without needing to
reset the database. The app runs in demo mode (deterministic local pipeline), so no
network or AI credentials are required for any test to be meaningful."""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

# Put the backend root on sys.path so `import app...` works when running pytest here.
BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Configure the environment BEFORE the app (and its settings singleton) is imported.
_DB = os.path.join(tempfile.mkdtemp(), "pytest.db")
os.environ["DATABASE_PATH"] = _DB
os.environ["AI_PROVIDER"] = "demo"
os.environ["SECRET_KEY"] = "pytest-secret-key-at-least-32-bytes-long"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _email(prefix: str = "u") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@test.local"


@pytest.fixture
def make_user(client):
    """Factory returning (bearer_headers, user_dict) for a freshly registered user."""
    def _make(name: str = "Test User") -> tuple[dict, dict]:
        email = _email()
        r = client.post("/api/v1/auth/register",
                        json={"name": name, "email": email, "password": "password123"})
        assert r.status_code == 201, r.text
        data = r.json()
        return {"Authorization": f"Bearer {data['token']}"}, data
    return _make


@pytest.fixture
def owner_with_restaurant(client, make_user):
    """A user who owns a restaurant. Returns (headers, restaurant_id, user_dict)."""
    headers, user = make_user("Owner")
    r = client.post("/api/v1/restaurants", headers=headers,
                    json={"name": f"R-{uuid.uuid4().hex[:6]}", "location": "Town"})
    assert r.status_code == 201, r.text
    return headers, r.json()["id"], user
