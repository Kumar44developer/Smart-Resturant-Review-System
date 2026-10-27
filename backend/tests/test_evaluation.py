"""Evaluation measures the ACTUAL deterministic pipeline and persists runs.
These tests confirm access control (owner/admin only) and that metrics describe
local pipeline behaviour rather than invented benchmark claims."""
from __future__ import annotations


def _owner_with_reviews(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    for text, rating in [
        ("The food was fresh and the staff were friendly", 5),
        ("Terrible service, cold food, long waiting time", 1),
        ("Nice atmosphere but the pasta was average", 3),
    ]:
        client.post(f"/api/v1/restaurants/{rid}/reviews", headers=headers,
                    json={"review_text": text, "rating": rating})
    return headers, rid


def test_evaluation_run_requires_admin(client, make_user):
    headers, _ = make_user("NoRestaurant")  # owns nothing -> not admin
    r = client.post("/api/v1/evaluation/run", headers=headers)
    assert r.status_code == 403


def test_evaluation_runs_and_persists(client, owner_with_restaurant):
    headers, rid = _owner_with_reviews(client, owner_with_restaurant)
    r = client.post("/api/v1/evaluation/run", headers=headers, params={"restaurant_id": rid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run"] == "complete"
    assert "sentiment" in body["results"]
    assert "aspects" in body["results"]
    assert "rag_safety" in body["results"]
    # Honesty: the result is explicitly scoped to the local pipeline.
    assert "local deterministic pipeline" in body["note"].lower()
    # Each evaluated task was persisted as an evaluation run.
    runs = client.get("/api/v1/evaluation/runs", headers=headers).json()
    tasks = {run["task"] for run in runs}
    assert {"sentiment", "aspects"}.issubset(tasks)
    # Stored metrics are real numbers, not placeholders.
    sent_run = next(run for run in runs if run["task"] == "sentiment")
    assert isinstance(sent_run["metrics"].get("accuracy"), (int, float))
