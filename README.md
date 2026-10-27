# Smart Restaurant Review Intelligence Platform

Turn raw customer reviews into **actionable, evidence-linked business intelligence**:
sentiment & aspect analytics, trend reporting, a retrieval-grounded chat assistant
(RAG), AI-assisted reply drafting with mandatory human approval, operational alerts,
and recommendation tracking.

Built as a real, runnable backend + server-rendered web app — not a mockup.

---

## Honest by design (read this first)

This project is explicitly about **trustworthy** AI. The rules below are enforced in
code and covered by tests, not just written here:

1. **Every dashboard metric is computed from stored rows.** No invented numbers.
   Thin data yields suppressed trends (`enough_data: false`) rather than fake lines.
2. **Every AI insight links to supporting evidence.** RAG answers cite review IDs that
   are validated to belong to the asking tenant before anything is returned.
3. **Measured facts are kept separate from generated interpretations.** Analysis output
   stores the deterministic sentiment/aspect result and the model's summary distinctly.
4. **Nothing external is auto-published.** Reply drafts are labelled AI-generated and
   require an explicit human approval step by a manager+ user.
5. **Synthetic data is labelled.** Demo/seed reviews carry `is_synthetic=1` and the UI
   shows a `DEMO MODE` badge.
6. **No fabricated integrations or benchmarks.** The AI provider is a pluggable adapter;
   with no API key it runs a deterministic local pipeline and says so.

See [`docs/HONESTY.md`](docs/HONESTY.md) for how each guarantee maps to code + tests.

---

## Why this stack (a real constraint, honestly noted)

The reference design targets **Postgres + SQLAlchemy + scikit-learn + a hosted LLM**.
This particular machine enforces **Windows Smart App Control**, which blocks the
unsigned native binaries those packages ship, **and** has no administrator credentials
available (Node.js/npm cannot be installed either).

So the runnable implementation here is a **100% pure-Python** stack that needs **no
native binaries and no Node**:

| Concern        | Runnable build (this repo)          | Production variant (documented, not run here) |
|----------------|-------------------------------------|-----------------------------------------------|
| Web framework  | FastAPI + Uvicorn                   | Same                                            |
| Database       | stdlib `sqlite3` (WAL + FTS5)       | Postgres + SQLAlchemy                           |
| ORM            | hand-written repository SQL layer   | SQLAlchemy models                               |
| NLP / analytics| pure-Python lexicon + aspect engine | scikit-learn classifiers                        |
| Front-end      | Jinja2 + HTMX (server-rendered CSS) | Same, or a React/Next build                     |
| LLM            | deterministic `DemoProvider`        | Groq / OpenAI-compatible adapter                |

The production path is described in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). It is
provided as configuration and guidance, and is **not** claimed to have been executed in
this environment.

**There is no `package.json` and no npm build step** — the UI is server-rendered. You do
not need Node.js to run this project.

---

## Quickstart

Requires Python 3.11+ (verified on 3.14). A ready virtualenv lives at `./.venv`.

```powershell
# from the repository root, PowerShell
cd backend

# 1. (first time only) install deps into a venv
python -m venv ..\.venv
..\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. create schema + demo data (idempotent)
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py seed-demo

# 3. run the app
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8008
```

Open <http://127.0.0.1:8008/> and sign in with the demo owner:

```
email:    demo@smart.app
password: demo12345
```

Health & readiness: `GET /health`, `GET /ready`. Interactive API docs: `GET /docs`.

### Run the tests

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

The suite (46 tests) runs entirely in-process with a throwaway SQLite DB and the local
deterministic pipeline — no network or credentials required.

### Verify end-to-end over real HTTP

With a server running (see above), `verify_e2e.py` drives it over HTTP and asserts every
capability claimed on the resume (RBAC, RAG citations + abstention, mixed sentiment, the
draft approval gate, CSV preview + idempotent commit, usage across all AI ops, evaluation,
error envelope, auth rejections, dashboard render):

```powershell
cd backend
..\.venv\Scripts\python.exe verify_e2e.py    # 23/23 end-to-end checks
```

---

## What you can do in the app

- **Dashboard** — KPIs (review volume, average rating, sentiment mix, analysis coverage)
  computed live from stored data.
- **Reviews** — CRUD, full-text (FTS5) search, sentiment/rating/source filters, mixed
  per-aspect sentiment preserved on a single review.
- **Analytics** — sentiment & rating trends, aspect breakdowns, theme frequencies,
  period-over-period and cross-location comparison (own restaurants only).
- **Ask (RAG chat)** — grounded Q&A with clickable evidence citations; honestly refuses
  questions about data that was never ingested (e.g. revenue).
- **Reply Studio** — draft empathetic responses grounded in real analysis, edit them,
  then approve (manager+) — approval never publishes anything automatically.
- **Operations** — anomaly alerts, action items, evidence-backed recommendations, weekly
  digest, JSON/CSV reports, per-tenant usage & audit logs.
- **Evaluation** — measures the *actual* local pipeline (sentiment accuracy/macro-F1,
  aspect micro-P/R/F1, RAG abstention & citation integrity) and persists each run.

## Layout

```
backend/
  app/
    main.py            FastAPI assembly: lifespan, CORS, logging, error handlers
    config.py          env/.env settings (stdlib only)
    db.py              sqlite3 connection helpers (WAL, FTS5, thread-local)
    security.py        scrypt password hashing + JWT
    deps.py            auth dependencies + RBAC (enforce_role)
    migrations/        versioned SQL (runner in app/migrations/__init__.py)
    repo/              data access (users, restaurants, reviews, analysis, ops, ...)
    services/          analytics, rag, reply, alerts, recommendations, evaluation, jobs, ai_usage
    ai/                provider adapters (demo + openai_compat), nlp, embeddings
    api/v1/            versioned JSON API routers
    web/               Jinja2 + HTMX server-rendered UI
    templates/ static/  UI
  tests/               pytest suite
  verify_e2e.py        end-to-end checks over real HTTP (needs a running server)
docs/                  architecture, API, honesty, deployment, project report
```

## More

- [Architecture](docs/ARCHITECTURE.md)
- [AI design](docs/AI_DESIGN.md)
- [RAG design](docs/RAG_DESIGN.md)
- [API reference](docs/API.md)
- [Honesty guarantees → code/tests](docs/HONESTY.md)
- [Deployment & production variant](docs/DEPLOYMENT.md)
- [Project report](docs/PROJECT_REPORT.md)
- [Demo script](docs/DEMO_SCRIPT.md)
- [Resume bullets](docs/RESUME_BULLETS.md)
