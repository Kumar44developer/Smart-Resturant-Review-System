"""RAG pipeline: hybrid (semantic + keyword + metadata) retrieval over a single
restaurant's authorized reviews, grounded answer generation, citation validation,
and honest abstention. Retrieval is always scoped to restaurant_id BEFORE any
model call, so one restaurant's documents can never enter another's context.

See docs/RAG_DESIGN.md."""
from __future__ import annotations

import math
import re
import time
from typing import Any

from .. import db
from ..ai.embeddings import get_embedding_provider
from ..ai.nlp import cosine
from ..ai.provider import get_provider
from ..repo import analysis as arepo
from ..repo import conversations as crepo
from . import ai_usage

_TOKEN_RE = re.compile(r"[a-z0-9']+")

# Platform-level scope guard: questions asking for data this product never
# ingests or stores must be refused honestly, regardless of which provider is
# configured or what text retrieval happens to surface. This keeps the assistant
# from dressing up unrelated reviews as an answer to an unanswerable question.
_OUT_OF_SCOPE = re.compile(
    r"\b(revenue|revenues|profit|profits|income|sales (?:figures?|total)|turnover|"
    r"salary|salaries|payroll|wages|supplier|suppliers|wholesale|cost price|"
    r"margin|margins|address|phone number|email|home\b|employee name|staff name)\b",
    re.IGNORECASE,
)


def _asks_for_unstored_data(question: str) -> bool:
    return bool(_OUT_OF_SCOPE.search(question))



def invalidate_cache(restaurant_id: int) -> None:
    # Retrieval recomputes per query; hook kept for future caching layers.
    _ = restaurant_id


def _candidate_ids(conn, restaurant_id: int, *, source=None, date_from=None,
                   date_to=None, rating_min=None, rating_max=None) -> list[int]:
    where = ["restaurant_id = ?"]
    params: list[Any] = [restaurant_id]
    if source:
        where.append("source = ?"); params.append(source)
    if date_from:
        where.append("review_ts >= ?"); params.append(date_from)
    if date_to:
        where.append("review_ts <= ?"); params.append(date_to)
    if rating_min is not None:
        where.append("rating >= ?"); params.append(rating_min)
    if rating_max is not None:
        where.append("rating <= ?"); params.append(rating_max)
    rows = conn.execute(f"SELECT id FROM reviews WHERE {' AND '.join(where)}", params).fetchall()
    return [r["id"] for r in rows]


def _keyword_scores(conn, query: str, candidate_ids: set[int]) -> dict[int, float]:
    terms = _TOKEN_RE.findall(query.lower())
    if not terms:
        return {}
    match = " OR ".join(terms)
    try:
        rows = conn.execute(
            "SELECT rowid AS id, bm25(reviews_fts) AS rank FROM reviews_fts "
            "WHERE reviews_fts MATCH ? ORDER BY rank LIMIT 200", (match,)
        ).fetchall()
    except Exception:
        return {}
    # bm25 is negative-and-lower-is-better; map to a 0..1 score.
    out: dict[int, float] = {}
    for r in rows:
        if r["id"] in candidate_ids:
            out[r["id"]] = 1.0 / (1.0 + math.exp(r["rank"]))
    return out


def retrieve(conn, restaurant_id: int, query: str, *, k: int = 6,
             filters: dict | None = None) -> list[dict]:
    filters = filters or {}
    cand_ids = _candidate_ids(
        conn, restaurant_id,
        source=filters.get("source"), date_from=filters.get("date_from"),
        date_to=filters.get("date_to"), rating_min=filters.get("rating_min"),
        rating_max=filters.get("rating_max"),
    )
    if not cand_ids:
        return []
    cand_set = set(cand_ids)

    # Semantic scores via stored embeddings.
    emb = get_embedding_provider()
    qvec = emb.embed(query) if query.strip() else None
    sem: dict[int, float] = {}
    if qvec:
        for row in arepo.get_embeddings(conn, restaurant_id):
            if row["review_id"] in cand_set:
                sem[row["review_id"]] = cosine(qvec, row["vector"])

    kw = _keyword_scores(conn, query, cand_set)

    scored: list[tuple[float, int]] = []
    ids = cand_set | set(sem) | set(kw)
    for rid in ids:
        score = 0.6 * sem.get(rid, 0.0) + 0.4 * kw.get(rid, 0.0)
        scored.append((score, rid))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    results: list[dict] = []
    for score, rid in scored:
        row = db.query_one(conn, "SELECT * FROM reviews WHERE id = ?", (rid,))
        if not row:
            continue
        la = arepo.latest_analysis(conn, rid)
        sentiment = la["sentiment"] if la else None
        topics = la["topics"] if la else []
        aspects = la["aspect_results"] if la else []

        # Post-retrieval metadata filters that need analysis results.
        if filters.get("sentiment") and sentiment != filters["sentiment"]:
            continue
        if filters.get("aspect"):
            wanted = filters["aspect"]
            want_sent = filters.get("aspect_sentiment")
            if not any(a.get("aspect") == wanted and (not want_sent or a.get("sentiment") == want_sent)
                       for a in aspects):
                continue
        excerpt = _excerpt_for(row["review_text"], aspects, wanted_aspect=filters.get("aspect"))
        results.append({
            "review_id": rid, "rating": row["rating"], "review_ts": row["review_ts"],
            "source": row["source"], "sentiment": sentiment, "topics": topics,
            "aspects": aspects, "excerpt": excerpt, "score": round(score, 4),
            "text": row["review_text"],
        })
        if len(results) >= k:
            break
    return results


def _excerpt_for(text: str, aspects: list[dict], wanted_aspect: str | None) -> str:
    for a in aspects:
        if wanted_aspect and a.get("aspect") != wanted_aspect:
            continue
        if a.get("excerpt"):
            return a["excerpt"][:400]
    return text[:300]


def answer_question(conn, *, restaurant_id: int, question: str, filters: dict | None = None,
                   session_id: int | None = None, user_id: int | None = None,
                   history: list[dict] | None = None, record_usage: bool = True) -> dict:
    # Honest abstention for questions outside the data the platform stores.
    if _asks_for_unstored_data(question):
        refusal = (
            "I can only answer from the review data stored for this restaurant. "
            "That question asks for information the platform never ingests "
            "(for example financials or personal details), so I won't guess."
        )
        saved_message_id = None
        if session_id is not None:
            crepo.add_message(conn, session_id, "user", question)
            saved_message_id = crepo.add_message(conn, session_id, "assistant", refusal)
        return {"answer": refusal, "abstain": True, "reason": "out_of_scope",
                "citations": [], "message_id": saved_message_id, "demo": get_provider().meta().is_demo}

    evidence = retrieve(conn, restaurant_id, question, k=6, filters=filters)
    provider = get_provider()
    started = time.perf_counter()
    result = provider.answer_with_evidence(question, evidence, history)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if record_usage:
        ai_usage.record(conn, provider, "chat_rag", restaurant_id=restaurant_id,
                        user_id=user_id, status="ok", measured_ms=elapsed_ms)

    allowed_ids = {e["review_id"] for e in evidence}
    # Enforce citation validity (defense-in-depth for demo provider too).
    result.cited_review_ids = [rid for rid in result.cited_review_ids if rid in allowed_ids]

    # Persist conversation + citations.
    saved_message_id = None
    ev_by_id = {e["review_id"]: e for e in evidence}
    if session_id is not None:
        crepo.add_message(conn, session_id, "user", question)
        saved_message_id = crepo.add_message(conn, session_id, "assistant", result.answer)
        for rank, rid in enumerate(result.cited_review_ids, start=1):
            crepo.add_citation(conn, saved_message_id, rid, rank,
                               ev_by_id.get(rid, {}).get("score"),
                               ev_by_id.get(rid, {}).get("excerpt"))

    cited = [
        {k: e[k] for k in ("review_id", "rating", "review_ts", "excerpt", "sentiment")}
        for e in evidence if e["review_id"] in set(result.cited_review_ids)
    ]
    return {
        "answer": result.answer,
        "abstain": result.abstain,
        "reason": result.reason,
        "citations": cited,
        "message_id": saved_message_id,
        "demo": provider.meta().is_demo,
    }
