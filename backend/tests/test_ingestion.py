"""CSV ingestion: preview classifies rows, commit persists valid ones, and unsafe
uploads are rejected. Uploaded content is treated strictly as data."""
from __future__ import annotations

GOOD_CSV = (
    "review_text,rating,date,external_id\n"
    "The pasta was fresh and delicious,5,2026-01-10,ext-1\n"
    "Terrible cold soup and rude staff,1,2026-01-11,ext-2\n"
    ",3,2026-01-12,ext-3\n"          # missing review text -> invalid
    "Duplicate id row,4,2026-01-13,ext-1\n"  # duplicate external id within file
)


def _upload(client, headers, rid, path, content, ctype="text/csv", fname="reviews.csv"):
    return client.post(f"/api/v1/restaurants/{rid}/{path}", headers=headers,
                       files={"file": (fname, content, ctype)})


def test_preview_classifies_rows(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    r = _upload(client, headers, rid, "imports/preview", GOOD_CSV.encode())
    assert r.status_code == 200
    body = r.json()
    # 2 valid, 1 invalid (missing text), 1 duplicate (reused ext-1)
    assert body["counts"]["imported"] == 2
    assert body["counts"]["invalid"] == 1
    assert body["counts"]["duplicate"] == 1


def test_import_commit_persists_and_job_completes(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    r = _upload(client, headers, rid, "imports", GOOD_CSV.encode())
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    # TestClient runs background tasks synchronously, so the job is done by now.
    job = client.get(f"/api/v1/imports/{job_id}", headers=headers).json()
    assert job["status"] in ("completed", "completed_with_errors")
    assert job["imported"] == 2
    listing = client.get(f"/api/v1/restaurants/{rid}/reviews", headers=headers).json()
    assert listing["total"] == 2


def test_non_csv_rejected(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    r = _upload(client, headers, rid, "imports/preview", b"\x00\x01binary",
                ctype="application/octet-stream", fname="payload.bin")
    assert r.status_code == 415


def test_missing_required_column_rejected(client, owner_with_restaurant):
    headers, rid, _ = owner_with_restaurant
    r = _upload(client, headers, rid, "imports/preview", b"foo,bar\n1,2\n")
    assert r.status_code == 400


def test_import_requires_membership_role(client, owner_with_restaurant, make_user):
    headers, rid, _ = owner_with_restaurant
    vh, viewer = make_user("Viewer")
    # register viewer into the restaurant as a low-privilege viewer
    client.post(f"/api/v1/restaurants/{rid}/members", headers=headers,
                json={"email": viewer["email"], "role": "viewer"})
    r = _upload(client, vh, rid, "imports", GOOD_CSV.encode())
    assert r.status_code == 403  # viewers cannot import
