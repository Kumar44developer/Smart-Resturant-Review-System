# Deployment

Two deployment stories, kept clearly separate so nothing is overclaimed:

- **A. The runnable build in this repo** — pure-Python, SQLite, demo provider. This is
  what has actually been executed and verified here.
- **B. The production target** — Postgres + SQLAlchemy + scikit-learn + hosted LLM.
  Provided as configuration/guidance; **not** run in this environment (blocked by
  Windows Smart App Control + no admin). 

---

## A. Runnable build (verified)

### Local

```powershell
cd backend
python -m venv ..\.venv
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe manage.py seed-demo
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8008
```

### Docker

```powershell
docker compose up --build
```

`Dockerfile` (repo root) builds a slim Python image; `docker-compose.yml` runs the API,
mounts a named volume for the SQLite file, and runs migrations on start. Healthcheck
hits `/ready`.

### Configuration (env)

Copy `.env.example` → `.env`. Key settings:

| Var | Default | Meaning |
|-----|---------|---------|
| `APP_ENV` | `dev` | `prod` disables `/dev/seed-demo` and verbose logs |
| `SECRET_KEY` | dev value | **must** be a ≥32-byte random value in prod |
| `DATABASE_PATH` | `./data/app.db` | SQLite file location |
| `AI_PROVIDER` | `demo` | `demo` or `openai_compat` |
| `AI_BASE_URL` | Groq URL | OpenAI-compatible base URL |
| `AI_API_KEY` | *(empty)* | when set + provider `openai_compat`, uses the hosted model |
| `AI_CHAT_MODEL` | `llama-3.3-70b-versatile` | hosted chat model id |
| `AI_EMBEDDING_MODEL` | *(empty)* | set to use hosted embeddings instead of hashing |
| `CORS_ORIGINS` | `http://localhost:8000` | comma-separated |
| `RATE_LIMIT_PER_MIN` | `120` | in-process limiter window |
| `MAX_UPLOAD_MB` | `5` | CSV upload cap |

When `AI_PROVIDER != openai_compat` **or** `AI_API_KEY` is empty, `settings.demo_mode`
is `true` and the app labels every response/analysis as demo — by design.

### Production hardening checklist (SQLite build)

- Put the app behind TLS (Caddy/nginx) and set a real `SECRET_KEY`.
- Move from in-process rate limiting to a shared store (Redis) if you run >1 worker.
- SQLite is single-writer: run **one** Uvicorn worker per volume, or migrate to Postgres (B).
- Ship structured logs (`app.access` JSON) to your log pipeline; they already omit bodies/secrets.

---

## B. Production target (documented, not run here)

The reference architecture swaps infrastructure without touching business logic:

| Component | Swap | How it plugs in |
|-----------|------|-----------------|
| Database | SQLite → **Postgres** | Replace `repo/*` SQL (mostly ANSI-compatible) or adopt SQLAlchemy Core; `db.connect()` → engine/session |
| ORM | hand-written repos → **SQLAlchemy 2.x** | models mirror `001_init.sql`; `row_factory` rows → ORM objects |
| NLP | pure-Python lexicon → **scikit-learn** classifier | implement `LLMProvider`/an `Analyzer` with a trained model; keep `analyze_review()` contract |
| Embeddings | hashing → **pgvector** + hosted embeddings | `review_embeddings` → `vector` column + ANN index |
| Search | FTS5 → **Postgres FTS / OpenSearch** | the keyword half of hybrid retrieval |
| Jobs | FastAPI BackgroundTasks → **Celery/RQ + Redis** | `services/jobs.py` callables move to tasks unchanged |
| LLM | demo → **Groq/OpenAI-compatible** | already first-class via `OpenAICompatProvider`; set env |
| Front-end | Jinja2/HTMX → optional React/Next | JSON API is already complete; SPA consumes `/api/v1` |

`requirements.txt` in this repo intentionally lists only the pure-Python runtime. A
production `requirements.in` would add `psycopg[binary]`, `SQLAlchemy`, `scikit-learn`,
`celery`, `redis`, `alembic`. **These are not installed or executed here** because the
local security policy blocks their native wheels; they are named as the migration path,
not as a working claim.

> Honesty: this document describes a *plan*, validated only by the interface seams that
> already exist (`LLMProvider` ABC, repository layer isolation, env-driven provider
> selection). The Postgres/sklearn path has not been run in this environment.
