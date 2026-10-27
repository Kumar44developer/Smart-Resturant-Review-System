# Project Report — Smart Restaurant Review Intelligence Platform

**Status:** feature-complete runnable build; all automated tests pass; live server
verified over HTTP. This report describes **what was actually built and measured**,
and is explicit about where the implementation deviates from the original spec and why.

---

## 1. Executive summary

The platform converts raw restaurant customer reviews into trustworthy, evidence-linked
business intelligence:

- Structured **sentiment + per-aspect** analytics computed from stored data.
- **Trends, themes, period and multi-location comparisons** — suppressed when data is
  too thin, never faked.
- A **retrieval-grounded (RAG) chat** assistant that cites the exact reviews behind
  every claim and **refuses** to answer about data it never ingested.
- An **AI Reply Studio** that drafts responses grounded in the real analysis, always
  labelled AI, and gated behind mandatory human approval — with no publish path at all.
- **Operational intelligence**: anomaly alerts, prioritised recommendations with
  supporting review ids, weekly digests, JSON/CSV reports, usage and audit logs.
- An **evaluation harness** that measures the *actual* pipeline and persists each run.

Every honesty principle in the brief is implemented in code and covered by tests
(see [HONESTY.md](HONESTY.md)).

---

## 2. Verified results

### 2.1 Automated tests

```
46 passed
```

Coverage by file: `test_security` (hashing/JWT/sanitize/rate-limit), `test_auth`
(register/login/RBAC/validation), `test_reviews` (analysis, mixed-sentiment, dup guard,
FTS, filters, stale-on-edit), `test_tenant_isolation` (cross-tenant 403 everywhere,
citation scoping, abstention, prompt-injection-as-data), `test_reply_studio` (AI labelling,
grounding, manager-only approval, rejected→cannot-approve), `test_analytics`
(metrics vs stored rows, thin-data suppression, own-locations only),
`test_ingestion` (preview classification, commit, type/role guards),
`test_evaluation` (admin gate, measured+persisted runs), `test_ops` (action status
lifecycle + the DB-constraint regression, cross-tenant link refusal, evidence-backed
recommendations, weekly/reports, usage/audit manager gate, alert triage, and per-tenant
usage accounting across **every** AI op — analysis, RAG chat, and reply drafting).
Runs in-process, demo provider,
throwaway SQLite — **no network or credentials needed**.

### 2.2 Live end-to-end verification (`verify_e2e.py`)

`backend/verify_e2e.py` drives a **running `uvicorn` server over real HTTP** and asserts
each resume claim end-to-end:

```
23/23 end-to-end checks passed
```

It covers: health/readiness; cross-tenant 403 and viewer-write 403; RAG citations +
out-of-scope abstention; mixed-sentiment aspect separation; AI-labelled draft with a human
approval gate (and rejected→cannot-approve 409); CSV preview classification + transactional,
idempotent commit; evidence-backed recommendations; weekly/JSON/CSV reports; audit; anomaly
detection; usage counting chat+draft with cost honestly 0 in demo; evaluation run + persistence;
tampered-token 401, weak-password 422, error envelope + request-id, anonymous 401; and the
server-rendered dashboard showing real data. Re-run it any time against a live server
(`python verify_e2e.py`) — it uses per-run unique ids so it is safe to repeat.

### 2.3 Live server (manual spot-checks)

- `GET /health` → `{"status":"ok","demo_mode":true}`
- `GET /ready` → `{"status":"ready","database":"ok","migrations":1,"demo_mode":true}`
- Seed: `seed-demo` loads **156 synthetic reviews** across the demo owner's restaurants;
  Bella Napoli (id 1) carries 83.
- Dashboard renders with the **DEMO MODE** badge.
- `GET /analytics/overview` for Bella Napoli returned:
  - `total_reviews: 83`, `average_rating: 3.31`
  - `sentiment_distribution: {positive: 41, neutral: 18, negative: 24}` (sums to 83)
  - `data_quality: {coverage_pct: 100.0, synthetic_count: 83, pending: 0, failed: 0}`
- RAG chat on a service question returned **6 citations**, all owned by the tenant.
- The same chat asked "What was our total revenue last quarter?" →
  `abstain: true`, `reason: "out_of_scope"` (honest refusal).
- `GET /report.csv` → `200`, `text/csv`, ~1 KB.
- Unauthenticated API request → `401`.

### 2.4 Evaluation (measured on the *actual* local deterministic pipeline)

Datasets are hand-labelled and versioned (`2026-10-handlabel`) under
`app/eval_data/`. These numbers describe the demo NLP pipeline **only** — they are not
a claim about any hosted model.

**Sentiment** (n = 18):

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|-----|---------|
| positive | 0.75 | 1.00 | 0.857 | 6 |
| neutral | 1.00 | 0.60 | 0.750 | 5 |
| negative | 1.00 | 1.00 | 1.000 | 7 |
| **Accuracy** | | | **0.889** | |
| **Macro F1** | | | **0.869** | |

Failures (2, as expected): neutral reviews leaned positive via mild praise words —
recorded, not hidden.

**Aspect detection** (n = 8): micro-precision **0.905**, micro-recall **0.950**,
micro-F1 **0.927**, mean item-F1 **0.941**. Perfect on food/pricing/portion/ambience;
service/waiting_time slightly over-triggered (precision 0.67) — again kept as real
failures in the persisted run.

**RAG safety** (83 reviews in scope): abstention accuracy **1.00**, citation integrity
**1/1** cited-answer check passed (all citations in-tenant), prompt-injection probes
**2/2** handled as data (no crash, no system-prompt leakage).

---

## 3. What "done" includes

- Versioned JSON API (`/api/v1`) with a consistent error envelope, OpenAPI at `/docs`.
- Server-rendered web app (Jinja2 + HTMX, pure-CSS charts) sharing the same services.
- Multi-tenant RBAC (viewer/member/manager/owner) resolved server-side from membership.
- CSV ingestion with preview, column-alias detection, rating/date normalisation,
  duplicate handling, transactional commit, row-level error reporting.
- Hybrid retrieval (semantic cosine over stored embeddings + FTS5 bm25), tenant-scoped.
- Structured JSON logging with request-id + latency; secrets/bodies never logged.
- Integer micro-unit cost accounting with per-call pricing version, recorded for **every**
  AI operation (analysis, RAG chat, reply drafting). In demo mode tokens/cost stay
  honestly NULL/0 because no external model is called.
- `manage.py` (migrate/status/seed-demo), dependency-free migration runner, `.env` loader.
- Docker + compose, CI workflow, documentation set, demo script, resume bullets.

## 4. Honest deviations from the spec

The original brief envisioned **Postgres + SQLAlchemy + scikit-learn + a hosted LLM +
(possibly) a JS front-end**. On this machine:

- Windows **Smart App Control** blocks the unsigned native binaries those libraries ship.
- There are **no administrator credentials**, so Node.js/npm cannot be installed and the
  security policy cannot be changed.

Therefore the **runnable** implementation is a 100% pure-Python stack (stdlib `sqlite3`
with FTS5, hand-written repositories, a deterministic pure-Python NLP pipeline, a Jinja2/
HTMX UI, and a pluggable LLM adapter that defaults to a demo provider). This is a real,
working system — not a simulation — and every metric above was actually produced by it.

The production target (Postgres/SQLAlchemy/scikit-learn/pgvector/Celery/hosted LLM) is
documented as a migration path in [DEPLOYMENT.md](DEPLOYMENT.md). It leans on seams that
already exist (the `LLMProvider` ABC, isolated repository layer, env-driven provider
selection). **It has not been executed here, and we do not claim it has.**

## 5. Known limitations

- **Rate limiting and background jobs are in-process.** Correct for a single worker;
  multi-worker deployments need Redis/Celery (documented).
- **SQLite is single-writer.** Fine for demo/dev; production should move to Postgres.
- **NLP is lexicon-based.** Solid on the labelled set but not a trained classifier;
  swap-in path is the `LLMProvider`/analyzer interface.
- **Embeddings use feature hashing** (256-d) unless a hosted embedding model is set.
- The web UI is server-rendered; there is deliberately **no SPA** in this build.

## 6. Reproducing

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q         # 46 passed
..\.venv\Scripts\python.exe manage.py seed-demo   # idempotent
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8008
# sign in at http://127.0.0.1:8008/ as demo@smart.app / demo12345
# with the server running, verify every resume claim over real HTTP:
..\.venv\Scripts\python.exe verify_e2e.py         # 23/23 checks (BASE=http://127.0.0.1:8008)
```
