# Architecture

## 1. Overview

A multi-tenant SaaS-style backend that ingests restaurant reviews, derives
structured analytics with a deterministic NLP pipeline (optionally a hosted LLM
behind the same interface), and exposes both a **versioned JSON API** (`/api/v1`)
and a **server-rendered web app** (Jinja2 + HTMX) over the same service layer.

```
                       ┌──────────────────────────────┐
   Browser ──HTTP──▶   │  web/  (Jinja2 + HTMX)        │  ─┐
                       └──────────────────────────────┘   │ shares services
   API client ─HTTP─▶  ┌──────────────────────────────┐   │  & security
                       │  api/v1/  (JSON, Pydantic)    │  ─┘
                       └──────────────┬────────────────┘
                                      │
                       ┌──────────────▼────────────────┐
                       │  services/  (domain logic)     │  analytics, rag, reply,
                       │  authz via deps.enforce_role   │  alerts, recommendations,
                       └───────┬───────────────┬────────┘  evaluation, jobs, export
                               │               │
                    ┌──────────▼───┐   ┌────────▼─────────┐
                    │  repo/ (SQL)  │   │  ai/ (providers)  │
                    │  sqlite3 rows │   │  demo | openai-compat
                    └──────────┬───┘   └────────┬─────────┘
                               │                │
                       ┌───────▼────────────────▼─────┐
                       │ SQLite (WAL) + FTS5 index      │
                       └────────────────────────────────┘
```

**Layering rule:** routers do auth + validation + delegation only. All business
logic lives in `services/`, all SQL lives in `repo/`. The web layer and the JSON
API call the *same* services, so behaviour can never diverge between them.

## 2. Request lifecycle

1. **Middleware** (`main.py`) assigns an `x-request-id`, times the request, and
   emits a structured JSON access log (never logs bodies or secrets).
2. **Auth dependency** (`deps.current_user`) resolves identity from either the
   `srr_session` HttpOnly cookie or an `Authorization: Bearer` JWT.
3. **Authorization** (`deps.enforce_role`) loads the caller's membership for the
   target restaurant and checks the role hierarchy. It **never trusts a client-
   supplied restaurant id** — membership is looked up server-side, so cross-tenant
   access returns `403` before any data is touched.
4. **Service** executes domain logic against the repository layer.
5. **Error handlers** translate exceptions into a consistent
   `{"error": {"code","message",...}}` envelope; unexpected errors return a generic
   500 without leaking internals.

## 3. Data model (SQLite)

Defined in `app/migrations/001_init.sql`, applied by a dependency-free versioned
runner (`schema_migrations` table; files named `NNN_*.sql`).

| Table | Purpose |
|-------|---------|
| `users` | accounts; `password_hash` is `scrypt$N$R$P$salt$hash` |
| `restaurants` | tenant root |
| `memberships` | user↔restaurant with role `owner/manager/member/viewer` |
| `reviews` | immutable-ish raw data; `analysis_status`, `is_synthetic`, unique `(restaurant,source,external_id)` for idempotent import |
| `reviews_fts` | FTS5 virtual table + insert/update/delete triggers (keyword retrieval) |
| `review_analyses` | per-run measured output: sentiment, confidence, `aspect_results` JSON, `topics` JSON, model/prompt versions |
| `review_embeddings` | stored vectors (JSON) per review + index version |
| `response_drafts` | AI reply drafts; `is_ai_generated`, lifecycle `draft→edited→approved/rejected` |
| `import_jobs` | CSV import lifecycle + row-level error details |
| `conversation_sessions/messages` + `retrieval_citations` | RAG chat history with validated citations |
| `ai_usage_records` | token/latency/**cost in integer micro-units** + pricing version |
| `audit_events` | who-did-what, non-sensitive metadata only |
| `recommendations` / `alerts` / `actions` | operational outputs, each traceable to supporting review ids |
| `evaluation_runs` | persisted measured metrics with dataset/model/prompt versions |

Design notes:
- **Money & metrics are exact**: costs use integer micro-units, timestamps are ISO-8601 UTC text.
- **JSON-shaped columns are TEXT**, validated/coerced in the app layer (keeps SQLite portable).
- **Analysis is append-only** (`review_analyses` rows per run) so history is preserved; the
  "latest" analysis is resolved with a `ROW_NUMBER()` window per review.

## 4. Connection handling (`db.py`)

- `sqlite3` with `foreign_keys=ON`, `check_same_thread=False`, `isolation_level=None`
  (explicit transaction control), `row_factory=sqlite3.Row`.
- WAL mode for concurrent readers.
- A **thread-local** connection is reused per request via the `get_db` dependency.
- Background tasks open **their own** connection (never share the request thread's).

## 5. AI layer (`ai/`)

- `base.LLMProvider` is an abstract interface: `analyze_review`, `summarize`,
  `draft_reply`, `embed`, `meta`.
- `demo.DemoProvider` — deterministic, runs the pure-Python NLP in `ai/nlp.py`
  (lexicon + rating sentiment, per-clause aspect detection, controlled topic
  taxonomy). **This is what runs with no API key**, and it reports
  `meta().is_demo = True` so the UI can label it.
- `openai_compat.OpenAICompatProvider` — talks to any OpenAI-compatible endpoint
  (default configured for Groq). Providers are **swappable via env only**; no
  business logic changes, satisfying "AI providers must be replaceable".
- `provider.get_provider()` returns the demo provider whenever
  `settings.demo_mode` is true.

## 6. Retrieval-Augmented Analytics (`services/rag.py`)

Hybrid retrieval, **tenant-scoped before any model call**:

1. Filter candidate reviews to the requesting restaurant only.
2. Score = `0.6 · cosine(embedding)` + `0.4 · FTS bm25`.
3. Build a grounded answer from retrieved excerpts.
4. **Citation validation**: cited review ids are intersected with the allowed set;
   anything not owned by the tenant is dropped.
5. **Out-of-scope abstention**: a provider-independent regex guard detects questions
   about data the platform never ingests (revenue, PII, etc.) and returns
   `abstain=True, reason="out_of_scope"` with empty citations — it will not guess.

## 7. Reply Studio (`services/reply.py`)

Drafts are generated from the review's *measured* analysis (complaint aspects,
rating), always flagged `is_ai_generated=1`, and start in `draft`. Editing moves
them to `edited`; approval requires **manager+** and only records human sign-off —
there is **no code path that publishes a reply to any external platform**.

## 8. Operational intelligence

- `alerts.detect` — deterministic thresholds over recent windows; stores the
  measured `metric` JSON so the alert is explainable.
- `recommendations.compute` — aggregates negative aspects/themes into prioritised
  actions, each carrying `supporting_review_ids`.
- `weekly.build` — a digest assembled only from stored analytics/alerts/recs.
- `export.to_json/to_csv` — reports computed live from the tenant's rows.

## 9. Rate limiting & guards (`services/guards.py`)

An in-process token/window limiter keyed per user+action protects chat/draft
endpoints. Input text is length-bounded and sanitized. **Prompt-injection content
is stored and classified as data**, never executed or allowed to steer retrieval
scope (covered by `test_tenant_isolation.py`).

## 10. Web layer (`web/`)

- `mount_web(app)` attaches Jinja2 templates + static files and registers routes.
- Every page redirects to `/login` when unauthenticated; role gates mirror the API.
- HTMX + a pure-CSS bar chart system keep the UI fully **offline-capable** — no JS
  build, no CDN dependency.

## 11. Testing strategy

`tests/` runs against a throwaway SQLite DB in **demo mode** (no network), using
FastAPI's `TestClient` (background tasks run synchronously, so import/analysis jobs
complete inside the request). Coverage spans auth/RBAC, tenant isolation, review
analysis, mixed-sentiment preservation, analytics accuracy vs stored rows, CSV
ingestion classification, RAG citations + abstention, Reply Studio approval rules,
and evaluation persistence. See `docs/HONESTY.md` for guarantee→test mapping.
