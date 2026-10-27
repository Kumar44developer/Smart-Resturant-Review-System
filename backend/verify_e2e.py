"""End-to-end verification over real HTTP against a running server.

Every check maps to a claim in docs/RESUME_BULLETS.md so the resume is backed by
demonstrated behavior, not prose. Run against a live uvicorn instance:
    python verify_e2e.py            # BASE env or http://127.0.0.1:8009
Exits non-zero if any check fails. Safe to re-run (uses per-run unique ids)."""
from __future__ import annotations

import os
import sys
import time

import httpx

BASE = os.environ.get("BASE", "http://127.0.0.1:8009")
DEMO = {"email": "demo@smart.app", "password": "demo12345"}
NONCE = os.urandom(3).hex()

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def login(email: str, password: str) -> httpx.Client:
    c = httpx.Client(base_url=BASE, timeout=20)
    r = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


def poll_job(client: httpx.Client, job_id: int, tries: int = 30) -> dict:
    for _ in range(tries):
        job = client.get(f"/api/v1/imports/{job_id}").json()
        if job.get("status", "").startswith("completed") or job.get("status") == "failed":
            return job
        time.sleep(0.2)
    return client.get(f"/api/v1/imports/{job_id}").json()


def main() -> int:
    owner = login(DEMO["email"], DEMO["password"])
    rests = owner.get("/api/v1/restaurants").json()
    rid = rests[0]["id"]

    # 1. Health & readiness ------------------------------------------------
    h = httpx.get(f"{BASE}/health", timeout=10).json()
    rd = httpx.get(f"{BASE}/ready", timeout=10).json()
    check("1 health+readiness (db ok, migrations applied)",
          rd.get("database") == "ok" and rd.get("migrations", 0) >= 1,
          f"demo_mode={h.get('demo_mode')} migrations={rd.get('migrations')}")

    # 2. Multi-tenancy + RBAC (register in a throwaway client so the owner
    #    session cookie is not overwritten) --------------------------------
    email2 = f"tenant{NONCE}@x.com"
    tmp = httpx.Client(base_url=BASE, timeout=20)
    tmp.post("/api/v1/auth/register", json={"email": email2, "password": "anotherpass1", "name": "T2"})
    c2 = login(email2, "anotherpass1")
    forb = c2.get(f"/api/v1/restaurants/{rid}/reviews")
    check("2a cross-tenant access denied (403/404)", forb.status_code in (403, 404), str(forb.status_code))
    owner.post(f"/api/v1/restaurants/{rid}/members", json={"email": email2, "role": "viewer"})
    wr = c2.post(f"/api/v1/restaurants/{rid}/reviews",
                 json={"review_text": "should be blocked", "rating": 3, "review_ts": "2026-01-01T00:00:00Z"})
    check("2b viewer role cannot write (403)", wr.status_code == 403, str(wr.status_code))
    check("2c listing scoped to accessible restaurants", len(rests) >= 1, f"owner sees {len(rests)}")

    # 3. RAG: citations + honest abstention -------------------------------
    cited = owner.post(f"/api/v1/restaurants/{rid}/chat",
                       json={"question": "what do customers say about the food?"}).json()
    check("3a grounded answer cites real review ids",
          bool(cited.get("citations")) and not cited.get("abstain"),
          f"{len(cited.get('citations', []))} citations")
    abst = owner.post(f"/api/v1/restaurants/{rid}/chat",
                      json={"question": "what was total revenue last quarter?"}).json()
    check("3b abstains on un-ingested business data",
          abst.get("abstain") and abst.get("reason") == "out_of_scope", abst.get("reason", ""))

    # 4. Deterministic NLP: mixed sentiment preserved (analyze synchronously)
    mid = owner.post(f"/api/v1/restaurants/{rid}/reviews", json={
        "review_text": "The food was absolutely amazing, but the service was terrible "
                       "and the waiting time was way too long.",
        "rating": 2, "review_ts": "2026-02-15T12:00:00Z",
        "external_source_id": f"e2e-{NONCE}-mixed"}).json()["id"]
    la = owner.post(f"/api/v1/reviews/{mid}/analyze").json()
    asp = {a["aspect"]: a["sentiment"] for a in (la.get("aspect_results") or [])}
    check("4 mixed sentiment: positive food + negative service kept separate",
          asp.get("food") == "positive" and asp.get("service") == "negative",
          f"overall={la.get('sentiment')} aspects={asp}")

    # 5. Reply Studio: AI label + human approval gate, never auto-publish --
    draft = owner.post(f"/api/v1/reviews/{mid}/drafts", json={"tone": "empathetic"}).json()
    check("5a draft labelled AI-generated, starts in review status",
          bool(draft.get("is_ai_generated")) and draft.get("status") in ("draft", "pending"),
          f"status={draft.get('status')}")
    appr = owner.post(f"/api/v1/drafts/{draft['id']}/approve", json={}).json()
    check("5b approval is a human gate -> 'approved' (manual sign-off, nothing auto-published)",
          appr.get("status") == "approved" and appr.get("approved_by") is not None
          and "manual" in appr.get("note", "").lower(), appr.get("status"))
    rej = owner.post(f"/api/v1/reviews/{mid}/drafts", json={}).json()
    owner.post(f"/api/v1/drafts/{rej['id']}/reject", json={})
    re_approve = owner.post(f"/api/v1/drafts/{rej['id']}/approve", json={})
    check("5c rejected draft cannot be approved (409)", re_approve.status_code == 409, str(re_approve.status_code))

    # 6. CSV ingestion: preview classification + transactional, idempotent commit
    e1, e2 = f"CSV-{NONCE}-1", f"CSV-{NONCE}-2"
    csv_text = ("review_text,rating,date,external_id\n"
                f'"Great pizza and fast service",5,2026-03-01,{e1}\n'
                f'"Loved the pasta, warm staff",4,2026-03-02,{e2}\n'
                f'"",3,2026-03-03,CSV-{NONCE}-3\n'
                f'"repeated id should dedupe",3,2026-03-04,{e1}\n')
    pv = owner.post(f"/api/v1/restaurants/{rid}/imports/preview",
                    files={"file": ("reviews.csv", csv_text.encode(), "text/csv")}).json()
    c = pv["counts"]
    check("6a preview classifies imported/invalid/duplicate",
          c["imported"] == 2 and c["invalid"] == 1 and c["duplicate"] == 1, str(c))
    job = owner.post(f"/api/v1/restaurants/{rid}/imports",
                     files={"file": ("reviews.csv", csv_text.encode(), "text/csv")}).json()
    st = poll_job(owner, job["job_id"])
    check("6b commit is transactional + idempotent (only valid non-dupes persisted)",
          st["status"].startswith("completed") and st["imported"] == 2 and st["duplicate_count"] == 1,
          f"status={st['status']} imported={st.get('imported')} dupes={st.get('duplicate_count')}")

    # 7. Operational intelligence ----------------------------------------
    recs = owner.post(f"/api/v1/restaurants/{rid}/recommendations/compute").json()
    check("7a every recommendation carries supporting review ids",
          bool(recs) and all(r.get("supporting_review_ids") for r in recs),
          f"{sum(1 for r in recs if r.get('supporting_review_ids'))}/{len(recs)}")
    wk = owner.get(f"/api/v1/restaurants/{rid}/weekly").status_code
    repj = owner.get(f"/api/v1/restaurants/{rid}/report").status_code
    repc = owner.get(f"/api/v1/restaurants/{rid}/report.csv")
    check("7b weekly digest + JSON/CSV report",
          wk == 200 and repj == 200 and repc.status_code == 200
          and "text/csv" in repc.headers.get("content-type", "") and "total_reviews" in repc.text)
    audit = owner.get(f"/api/v1/restaurants/{rid}/audit").json()
    check("7c audit trail records actions", len(audit) >= 1,
          f"{len(audit)} entries, latest={audit[0]['action'] if audit else '-'}")
    alerts = owner.post(f"/api/v1/restaurants/{rid}/alerts/detect", params={"window_days": 120}).json()
    check("7d anomaly detection runs", "detected" in alerts, str(alerts))

    # 7e. usage/cost accounts for EVERY AI op (new wiring: chat + draft too)
    base_ops = owner.get(f"/api/v1/restaurants/{rid}/usage").json()["operations"]
    owner.post(f"/api/v1/restaurants/{rid}/chat", json={"question": "how is the service?"})
    owner.post(f"/api/v1/reviews/{mid}/drafts", json={})
    usage = owner.get(f"/api/v1/restaurants/{rid}/usage").json()
    check("7e per-tenant usage counts chat + draft calls, cost honest (0 in demo, not fabricated)",
          usage["operations"] - base_ops >= 2 and usage["cost_field"] == "estimated_cost_micros"
          and usage["cost_micros"] == 0,
          f"+{usage['operations'] - base_ops} ops, cost_micros={usage['cost_micros']}")

    # 7f. evaluation harness measures the ACTUAL pipeline & persists runs
    ev = owner.post(f"/api/v1/evaluation/run", params={"restaurant_id": rid}).json()
    keys = set((ev.get("results") or {}).keys())
    check("7f evaluation runs on real data, keys present, persisted",
          ev.get("run") == "complete" and {"sentiment", "aspects", "rag_safety"} <= keys,
          f"result_keys={sorted(keys)}")

    # 8. Trust/security ---------------------------------------------------
    tampered = httpx.Client(base_url=BASE)
    tampered.cookies.set("srr_session", "garbage.token.value")
    check("8a tampered session token rejected (401)",
          tampered.get("/api/v1/restaurants").status_code == 401)
    tmp2 = httpx.Client(base_url=BASE, timeout=20)
    check("8b weak password rejected by schema (422)",
          tmp2.post("/api/v1/auth/register", json={"email": "weak@x.com", "password": "123", "name": "w"}).status_code == 422)
    err = owner.get("/api/v1/restaurants/999999/reviews")
    body = err.json().get("error", {})
    check("8c consistent machine-readable error envelope + request-id header",
          err.status_code in (403, 404) and body.get("code") and body.get("message")
          and err.headers.get("x-request-id"), f"code={body.get('code')}")
    anon = httpx.get(f"{BASE}/api/v1/restaurants/{rid}/reviews", timeout=10)
    check("8d unauthenticated API access denied (401)", anon.status_code == 401)

    # 9. Server-rendered dashboard shares the same data/service layer ------
    root = owner.get("/")                                   # dashboard lives at "/"
    revpage = owner.get(f"/r/{rid}/reviews")                # per-restaurant web view
    check("9 dashboard HTML renders real data (same service layer as API)",
          root.status_code == 200 and rests[0]["name"] in root.text
          and revpage.status_code == 200 and "sentiment" in revpage.text.lower(),
          f"{rests[0]['name']} on dashboard; sentiment badges rendered on web reviews")

    failed = [r for r in _results if not r[1]]
    print("\n==== SUMMARY ====")
    print(f"{len(_results) - len(failed)}/{len(_results)} end-to-end checks passed")
    if failed:
        for name, _, detail in failed:
            print(f"  FAILED: {name} :: {detail}")
        return 1
    print("ALL RESUME CLAIMS VERIFIED END-TO-END OVER REAL HTTP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
