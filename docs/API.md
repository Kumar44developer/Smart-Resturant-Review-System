# API Reference (`/api/v1`)

Interactive docs (Swagger UI) are served at **`GET /docs`** and the raw schema at
**`GET /openapi.json`**. This page is a stable summary.

## Authentication

- **JWT HS256** issued by issuer `smart-review-platform`.
- Send it either as an `Authorization: Bearer <token>` header **or** rely on the
  `srr_session` HttpOnly cookie set by `/api/v1/auth/login` (used by the web UI).
- Roles, lowest→highest: `viewer < member < manager < owner`. Authorization is
  resolved **server-side from membership**; a client-supplied restaurant id is
  never trusted. Wrong tenant ⇒ `403`, no membership ⇒ `403`, anonymous ⇒ `401`.

Errors use a consistent envelope:

```json
{ "error": { "code": "not_found", "message": "Review not found" } }
```

`422` validation errors add a `details` array. Unexpected errors return a generic
`500` that does not leak internals.

---

## Auth & users

| Method | Path | Role | Notes |
|--------|------|------|-------|
| POST | `/auth/register` | public | `{name,email,password}` (password ≥ 8). Returns `{token, id, email, name}`. `409` on duplicate email. |
| POST | `/auth/login` | public | `{email,password}`. `401` on bad credentials. Sets cookie + returns bearer token. |
| POST | `/auth/logout` | any | Clears the session cookie. |
| GET | `/users/me` | authed | Current user profile. |

## Restaurants & members

| Method | Path | Role |
|--------|------|------|
| POST | `/restaurants` | authed (creator becomes `owner`) |
| GET | `/restaurants` | authed — lists only restaurants the caller belongs to |
| GET | `/restaurants/{id}` | viewer+ |
| PATCH | `/restaurants/{id}` | manager+ |
| GET | `/restaurants/{id}/members` | manager+ |
| POST | `/restaurants/{id}/members` | owner — `{email, role}`; `404` if no such user |

Body `RestaurantIn`: `name` (1–200), `description?`, `location?`, `timezone=UTC`.

## Reviews

| Method | Path | Role | Notes |
|--------|------|------|-------|
| GET | `/restaurants/{id}/reviews` | viewer+ | Filters: `q` (FTS5), `sentiment`, `source`, `rating_min/max`, `date_from/to`, `sort`, `order`, `page`, `size`. Returns `{items,total,limit,offset}`; each item carries a computed `sentiment`. |
| POST | `/restaurants/{id}/reviews` | member+ | `ReviewIn`. Triggers async analysis. `409` on duplicate `(source, external_source_id)`. |
| GET | `/reviews/{id}` | viewer+ | Includes `latest_analysis`. |
| PATCH | `/reviews/{id}` | manager+ | Editing `review_text` marks analysis `stale`. |
| DELETE | `/reviews/{id}` | manager+ | Also drops the stored embedding. |
| POST | `/reviews/{id}/analyze` | member+ | (Re)run analysis synchronously. |
| GET | `/reviews/{id}/analyses` | viewer+ | Full analysis history. |
| POST | `/restaurants/{id}/reviews/analyze-pending` | member+ | Queue pending/stale/failed rows. |

`ReviewIn`: `review_text` (1–5000), `rating?` (1–5), `source=manual`,
`external_source_id?`, `author_name?`, `review_ts?`, `language=en`.

## CSV ingestion

| Method | Path | Role | Notes |
|--------|------|------|-------|
| POST | `/restaurants/{id}/imports/preview` | member+ | Multipart `file`. Returns classified `columns/counts/total_rows/sample_valid/sample_invalid`. |
| POST | `/restaurants/{id}/imports` | member+ | Returns `202 {job_id,status:"queued"}`; commits valid rows in a background job. |
| GET | `/imports/{job_id}` | viewer+ (tenant-checked) | Job status incl. `imported`, `duplicate_count`, `invalid_count`, `error_details`. |

Only `.csv` is accepted (`415`), size-limited (`413`), and a missing review-text
column is rejected (`400`). Column aliases (e.g. `review`, `stars`, `date`) are
auto-detected; ratings on 1–10/1–100 scales are normalized. Uploaded content is
treated strictly as **data**.

## Analytics (all computed from stored rows)

| Method | Path | Returns |
|--------|------|---------|
| GET | `/restaurants/{id}/analytics/overview` | totals, avg rating, rating & sentiment distributions, volume series, `data_quality` (coverage %, synthetic count, pending/failed) |
| GET | `/restaurants/{id}/analytics/sentiment-trend` | `{enough_data, series}` (suppressed when < 2 periods) |
| GET | `/restaurants/{id}/analytics/rating-trend` | `{enough_data, series}` |
| GET | `/restaurants/{id}/analytics/aspects` | per-aspect positive/neutral/negative + net |
| GET | `/restaurants/{id}/analytics/themes` | theme frequencies (optional `sentiment` filter) |
| GET | `/restaurants/{id}/analytics/period-compare?date_from&date_to` | current vs preceding equal window + deltas |
| GET | `/restaurants/{id}/analytics/location-compare` | comparison restricted to the caller's own restaurants |

## Conversational analytics (RAG)

| Method | Path | Role | Notes |
|--------|------|------|-------|
| POST | `/restaurants/{id}/chat/sessions` | viewer+ | Create a session. |
| GET | `/chat/sessions` | authed | Caller's sessions. |
| GET | `/chat/sessions/{id}/messages` | owner of session | Messages with their citations. |
| POST | `/restaurants/{id}/chat` | viewer+ | `ChatIn {question, session_id?, filters?}`. Rate-limited. Returns `{answer, abstain, reason?, citations[], message_id, demo}`. **Abstains** on data never ingested (e.g. revenue). |

## Reply Studio

| Method | Path | Role | Notes |
|--------|------|------|-------|
| POST | `/reviews/{id}/drafts` | member+ | `DraftIn {tone, length}`. Always `is_ai_generated=1`, status `draft`. |
| GET | `/reviews/{id}/drafts` | viewer+ | Draft history for a review. |
| GET | `/drafts/{id}` | viewer+ | |
| PATCH | `/drafts/{id}` | member+ | `DraftEdit {body}` → status `edited`. |
| POST | `/drafts/{id}/approve` | **manager+** | Records human sign-off only. **Publishes nothing.** `409` if already rejected. |
| POST | `/drafts/{id}/reject` | manager+ | |

## Operations

| Method | Path | Role |
|--------|------|------|
| GET | `/restaurants/{id}/alerts` | viewer+ (`state` filter) |
| POST | `/restaurants/{id}/alerts/detect?window_days` | manager+ |
| POST | `/alerts/{id}/review` · `/dismiss` | manager+ |
| GET | `/restaurants/{id}/actions` | viewer+ |
| POST | `/restaurants/{id}/actions` | member+ (validates linked reviews are in-tenant) |
| PATCH | `/actions/{id}` | member+ |
| GET | `/restaurants/{id}/recommendations` | viewer+ |
| POST | `/restaurants/{id}/recommendations/compute` | manager+ |
| GET | `/restaurants/{id}/report` · `/report.csv` | viewer+ (CSV is `text/csv` download) |
| GET | `/restaurants/{id}/weekly?week_days` | viewer+ |
| GET | `/restaurants/{id}/usage` | manager+ (cost as integer micro-units + pricing version) |
| GET | `/restaurants/{id}/audit` | manager+ |

## Evaluation & dev

| Method | Path | Role | Notes |
|--------|------|------|-------|
| GET | `/evaluation/runs` | admin* | Persisted measured runs. |
| POST | `/evaluation/run?restaurant_id?` | admin* | Measures the **actual local pipeline**; note says results describe the deterministic pipeline only. |
| POST | `/dev/seed-demo` | admin*, non-prod | Idempotent synthetic seed; rows flagged `is_synthetic`. |

\* "admin" here = any user that owns at least one restaurant (there is no separate
super-user role in this build).

## Liveness

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | `{status, service, demo_mode}` |
| GET | `/ready` | verifies DB + applied migration count |
