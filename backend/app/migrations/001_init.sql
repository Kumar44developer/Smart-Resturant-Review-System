-- Smart Restaurant Review Intelligence Platform - initial schema (SQLite dialect).
-- Timestamps are ISO-8601 UTC text. Monetary values use integer micro-units to
-- avoid float drift. JSON-shaped columns are TEXT (validated in the app layer).

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE restaurants (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    description TEXT,
    location    TEXT,
    timezone    TEXT    NOT NULL DEFAULT 'UTC',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE memberships (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    role          TEXT    NOT NULL CHECK (role IN ('owner','manager','member','viewer')),
    status        TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active','invited','revoked')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, restaurant_id)
);

CREATE TABLE reviews (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id      INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    external_source_id TEXT,
    source             TEXT    NOT NULL DEFAULT 'manual',
    author_name        TEXT,
    rating             REAL    CHECK (rating IS NULL OR (rating >= 1 AND rating <= 5)),
    review_text        TEXT    NOT NULL,
    review_ts          TEXT,
    import_ts          TEXT    NOT NULL DEFAULT (datetime('now')),
    language           TEXT    NOT NULL DEFAULT 'en',
    analysis_status    TEXT    NOT NULL DEFAULT 'pending'
                         CHECK (analysis_status IN ('pending','processing','done','failed','stale')),
    is_synthetic       INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (restaurant_id, source, external_source_id)
);
CREATE INDEX idx_reviews_restaurant_ts ON reviews (restaurant_id, review_ts);
CREATE INDEX idx_reviews_status ON reviews (analysis_status);
CREATE INDEX idx_reviews_sentiment_lookup ON reviews (restaurant_id, source);

-- Full-text search over review bodies (keyword side of hybrid retrieval).
CREATE VIRTUAL TABLE reviews_fts USING fts5 (
    review_text,
    content='reviews',
    content_rowid='id'
);
CREATE TRIGGER reviews_ai AFTER INSERT ON reviews BEGIN
    INSERT INTO reviews_fts (rowid, review_text) VALUES (new.id, new.review_text);
END;
CREATE TRIGGER reviews_ad AFTER DELETE ON reviews BEGIN
    INSERT INTO reviews_fts (reviews_fts, rowid, review_text) VALUES ('delete', old.id, old.review_text);
END;
CREATE TRIGGER reviews_au AFTER UPDATE ON reviews BEGIN
    INSERT INTO reviews_fts (reviews_fts, rowid, review_text) VALUES ('delete', old.id, old.review_text);
    INSERT INTO reviews_fts (rowid, review_text) VALUES (new.id, new.review_text);
END;

CREATE TABLE review_analyses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id       INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    model_provider  TEXT    NOT NULL,
    model_id        TEXT    NOT NULL,
    model_version   TEXT,
    prompt_version  TEXT    NOT NULL,
    sentiment       TEXT    CHECK (sentiment IN ('positive','neutral','negative')),
    confidence      REAL,
    aspect_results  TEXT,   -- JSON array
    topics          TEXT,   -- JSON array
    summary         TEXT,
    status          TEXT    NOT NULL DEFAULT 'done' CHECK (status IN ('done','failed')),
    duration_ms     INTEGER,
    error_category  TEXT,
    analyzed_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_analyses_review ON review_analyses (review_id);

CREATE TABLE review_embeddings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id       INTEGER NOT NULL UNIQUE REFERENCES reviews(id) ON DELETE CASCADE,
    restaurant_id   INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    embedding_model TEXT    NOT NULL,
    index_version   TEXT    NOT NULL,
    dim             INTEGER NOT NULL,
    vector          TEXT    NOT NULL,   -- JSON array of floats
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_embeddings_restaurant ON review_embeddings (restaurant_id);

CREATE TABLE response_drafts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id     INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    body          TEXT    NOT NULL,
    tone          TEXT    NOT NULL,
    length        TEXT    NOT NULL DEFAULT 'medium',
    model_provider TEXT   NOT NULL,
    model_id      TEXT    NOT NULL,
    is_ai_generated INTEGER NOT NULL DEFAULT 1,
    status        TEXT    NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','edited','approved','rejected')),
    created_by    INTEGER REFERENCES users(id),
    approved_by   INTEGER REFERENCES users(id),
    approved_at   TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_drafts_review ON response_drafts (review_id);

CREATE TABLE import_jobs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id  INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    filename       TEXT    NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued','preview','running','completed','completed_with_errors','failed')),
    total_rows     INTEGER NOT NULL DEFAULT 0,
    imported       INTEGER NOT NULL DEFAULT 0,
    skipped        INTEGER NOT NULL DEFAULT 0,
    invalid_count  INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    error_details  TEXT,   -- JSON array of {row, field, message}
    started_at     TEXT,
    completed_at   TEXT,
    created_by     INTEGER REFERENCES users(id),
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE conversation_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE conversation_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES conversation_sessions(id) ON DELETE CASCADE,
    role       TEXT    NOT NULL CHECK (role IN ('user','assistant')),
    content    TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_messages_session ON conversation_messages (session_id);

CREATE TABLE retrieval_citations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      INTEGER NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
    review_id       INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    rank            INTEGER NOT NULL,
    retrieval_score REAL,
    excerpt         TEXT
);
CREATE INDEX idx_citations_message ON retrieval_citations (message_id);

CREATE TABLE ai_usage_records (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER REFERENCES users(id),
    restaurant_id      INTEGER REFERENCES restaurants(id),
    operation          TEXT    NOT NULL,
    provider           TEXT    NOT NULL,
    model              TEXT    NOT NULL,
    input_tokens       INTEGER,
    output_tokens      INTEGER,
    estimated_cost_micros INTEGER,   -- integer micro-units for exact precision
    pricing_version    TEXT,
    latency_ms         INTEGER,
    status             TEXT    NOT NULL CHECK (status IN ('ok','error','fallback')),
    created_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_usage_scope ON ai_usage_records (restaurant_id, created_at);

CREATE TABLE audit_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER REFERENCES users(id),
    restaurant_id INTEGER REFERENCES restaurants(id),
    action        TEXT    NOT NULL,
    resource_type TEXT    NOT NULL,
    resource_id   TEXT,
    metadata      TEXT,   -- JSON, non-sensitive only
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_audit_scope ON audit_events (restaurant_id, created_at);

CREATE TABLE recommendations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id    INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    proposed_action  TEXT    NOT NULL,
    supporting_theme TEXT,
    supporting_review_ids TEXT,   -- JSON array
    support_count    INTEGER NOT NULL DEFAULT 0,
    priority_rationale TEXT,
    uncertainty      TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_recs_restaurant ON recommendations (restaurant_id);

CREATE TABLE alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    rule          TEXT    NOT NULL,
    aspect        TEXT,
    window        TEXT,
    severity      TEXT    NOT NULL CHECK (severity IN ('info','warning','urgent')),
    metric        TEXT,   -- JSON: measured values behind the deterministic threshold
    message       TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open','reviewed','dismissed')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    reviewed_at   TEXT
);
CREATE INDEX idx_alerts_restaurant ON alerts (restaurant_id, status);

CREATE TABLE actions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id  INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    title          TEXT    NOT NULL,
    description    TEXT,
    status         TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','completed')),
    owner_user_id  INTEGER REFERENCES users(id),
    due_date       TEXT,
    resolution_note TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE action_review_links (
    action_id INTEGER NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
    review_id INTEGER NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    PRIMARY KEY (action_id, review_id)
);

CREATE TABLE evaluation_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task            TEXT    NOT NULL,
    dataset_version TEXT    NOT NULL,
    model_version   TEXT    NOT NULL,
    prompt_version  TEXT    NOT NULL,
    config          TEXT,   -- JSON
    metrics         TEXT    NOT NULL,   -- JSON metric values (measured, not hardcoded)
    failures        TEXT,   -- JSON failure examples
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
