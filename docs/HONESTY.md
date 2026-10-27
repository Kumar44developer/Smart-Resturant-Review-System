# Honesty Guarantees → Code → Tests

The platform's whole premise is **trustworthy** AI. Every principle below is
implemented in code and covered by an automated test — not just asserted in prose.

| # | Principle | Where enforced | Covered by |
|---|-----------|----------------|------------|
| 1 | Metrics are computed from stored rows, never fabricated | `services/analytics.py` aggregates `reviews` + `review_analyses`; thin data sets `enough_data:false` instead of drawing a fake trend | `test_analytics.py::test_overview_reflects_stored_reviews`, `::test_trend_suppressed_on_thin_data` |
| 2 | Every AI insight links to real evidence | `services/rag.py` returns citations validated against the tenant's review ids (`retrieval_citations`) | `test_tenant_isolation.py::test_chat_citations_are_scoped_to_one_tenant` |
| 3 | Facts kept separate from generated interpretation | `review_analyses` stores measured `sentiment`/`aspect_results`/`topics` distinct from the model `summary` | `test_reviews.py::test_create_triggers_analysis_with_mixed_aspects` |
| 4 | Human approval before anything is "sent" | `api/v1/ai.py` approve is manager+ and returns an explicit "nothing published automatically" note; there is **no publish path** | `test_reply_studio.py::test_approval_requires_manager`, `::test_rejected_draft_cannot_be_approved` |
| 5 | AI output is labelled as AI | `response_drafts.is_ai_generated=1` always; `demo`/`DEMO MODE` surfaced from `provider.meta().is_demo` | `test_reply_studio.py::test_draft_is_ai_labeled_and_starts_as_draft` |
| 6 | No fabrication of unstored data | `services/rag.py` out-of-scope guard → `abstain:true, reason:"out_of_scope"` | `test_tenant_isolation.py::test_abstains_on_unstored_data` |
| 7 | Synthetic data is labelled, not passed off as real | `reviews.is_synthetic`; seed sets it; UI shows the count + demo badge | live check (overview `synthetic_count`), `data_quality` in `test_analytics` |
| 8 | Multi-tenant isolation | `deps.enforce_role` resolves membership server-side; client restaurant id never trusted | `test_tenant_isolation.py` (read/chat/analytics/alerts all `403` cross-tenant) |
| 9 | Prompt injection is treated as data | review text is stored & classified, never executed; retrieval stays tenant-scoped regardless of question wording | `test_tenant_isolation.py::test_prompt_injection_in_review_is_treated_as_data` |
| 10 | Replaceable AI providers | `ai/base.LLMProvider` ABC; `demo` and `openai_compat` chosen by env only | all tests run against the swapped-in demo provider |
| 11 | No invented benchmarks | `services/evaluation.py` measures the **actual** deterministic pipeline and persists dataset/model/prompt versions | `test_evaluation.py::test_evaluation_runs_and_persists` |
| 12 | Exact, auditable numbers | costs in integer micro-units (`estimated_cost_micros`) + `pricing_version`; timestamps ISO-8601 UTC | `api/v1/ops.py::usage`; schema `001_init.sql` |
| 13 | Secrets & bodies not leaked | structured access log records method/path/status/ms only; generic 500 hides internals | `main.py` middleware + error handlers |

## Security specifics

- **Password hashing**: `hashlib.scrypt` (n=16384, r=8, p=1, dklen=32), stored as
  `scrypt$N$R$P$salt$hash`. No third-party crypto. → `test_security.py`.
- **Sessions**: HS256 JWT, issuer `smart-review-platform`, delivered as an HttpOnly
  `srr_session` cookie and/or `Authorization: Bearer`. Tampered tokens are rejected.
  → `test_auth.py`, `test_security.py`.
- **RBAC hierarchy**: `viewer < member < manager < owner`; each endpoint declares the
  minimum role. → `test_auth.py::test_role_hierarchy_enforced`, `test_ingestion.py`.
- **Rate limiting**: in-process window limiter on chat/draft endpoints.
  → `test_security.py::test_rate_limit_raises_after_threshold`.

## On the demo/default provider

With no API key the system runs a **deterministic, local** NLP pipeline and openly
labels itself as demo (`demo_mode:true` in `/health`, `DEMO MODE` badge in the UI,
`is_demo` in analysis metadata). Choosing a hosted model is a configuration change
(`AI_PROVIDER=openai_compat` + `AI_API_KEY`) — see [DEPLOYMENT.md](DEPLOYMENT.md).
We never claim hosted-model performance we did not measure.

> Verification note: the guarantees above were confirmed by running the full pytest
> suite (46 passed) and by `verify_e2e.py`, which drives a live `uvicorn` server over
> HTTP and asserts 23/23 end-to-end checks (login/RBAC, analytics vs stored data, RAG
> citations + revenue abstention, mixed-sentiment aspects, draft approval gate, CSV
> preview + idempotent commit, usage across all AI ops, evaluation, error envelope,
> anonymous/tampered-token rejection, dashboard render). See
> [PROJECT_REPORT.md](PROJECT_REPORT.md).
