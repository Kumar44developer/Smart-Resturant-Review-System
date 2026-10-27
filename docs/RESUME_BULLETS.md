# Resume Bullets

Copy-adapt to taste. Every bullet is **true and demonstrable** from this repo.

## One-liner (project header)
**Smart Restaurant Review Intelligence Platform** — FastAPI + SQLite(FTS5) + pluggable
LLM/RAG; turns customer reviews into evidence-linked analytics with human-in-the-loop
reply drafting. [demo: 46 passing tests + 23/23 live HTTP checks, UI + versioned API]

## Experience bullets

**Backend / AI Engineering — Review Intelligence Platform (Python, FastAPI)**
- Designed a **multi-tenant** analytics backend (restaurants as tenants) with a
  server-enforced **RBAC** model (viewer→member→manager→owner); membership is resolved
  server-side so cross-tenant access is impossible by construction — validated by an
  automated isolation suite.
- Built a **retrieval-grounded (RAG) assistant** with **hybrid retrieval** (semantic
  cosine over stored embeddings + SQLite **FTS5 bm25**); every answer is backed by
  **validated citations** scoped to the requester's own data, and the system **abstains**
  on questions about data it never ingested (e.g. revenue).
- Implemented a **deterministic NLP pipeline** (lexicon + rating sentiment, per-clause
  aspect detection that preserves *mixed* sentiment, controlled topic taxonomy) behind a
  **provider-agnostic `LLMProvider` interface**, letting a hosted OpenAI-compatible model
  (Groq) be swapped in via configuration with zero business-logic changes.
- Shipped an **AI Reply Studio** that drafts responses grounded in real analysis, always
  labels output as AI, and requires **manager approval** with **no automatic publish
  path** — enforcing human-in-the-loop for all external comms.
- Delivered a full **CSV ingestion** pipeline: preview/classification, column-alias
  detection, rating/date normalisation, idempotent duplicate handling, transactional
  commit, and **row-level error reporting**.
- Added **operational intelligence**: threshold-based anomaly alerts, recommendations
  linked to supporting review ids, weekly digests, JSON/CSV reports, and per-tenant
  usage/cost accounting (recorded for **every** AI op — analysis, RAG chat, drafting)
  stored in **integer micro-units** (no float drift).
- Wrote an **evaluation harness** measuring the *actual* pipeline (sentiment
  accuracy **0.889** / macro-F1 **0.869**; aspect micro-F1 **0.927**; RAG abstention
  **1.0**, citation-integrity **100%**, prompt-injection probes **2/2**) and persisting
  each run with dataset/model/prompt versions.
- Engineered trust end-to-end: **scrypt** password hashing, **HS256 JWT** HttpOnly
  sessions, structured JSON logging that never records bodies/secrets, in-process rate
  limiting, prompt-injection-as-data handling, and consistent error envelopes.
- Authored a **server-rendered dashboard** (Jinja2 + HTMX, pure-CSS charts) requiring **no
  JS build**, sharing one service layer with the JSON API so UI and API can never diverge.

## Skills surfaced (keywords)
`Python` · `FastAPI` · `SQLite/FTS5` · `REST API design` · `RAG` · `hybrid retrieval` ·
`embeddings` · `NLP / sentiment & aspect-based analysis` · `multi-tenancy & RBAC` ·
`JWT & scrypt auth` · `LLM provider abstraction` · `human-in-the-loop AI` ·
`prompt-injection defense` · `pytest` · `Docker` · `CI` · `structured logging` ·
`cost accounting` · `data integrity / honest metrics`

## Notes for interviewers
- Runs entirely offline in **demo mode** (no API keys) with reproducible numbers.
- The pure-Python runtime was a deliberate response to a locked-down Windows host
  (Smart App Control + no admin) — the production path (Postgres/SQLAlchemy/scikit-learn/
  pgvector/Celery) is documented and isolated behind existing seams.
