"""Review analysis orchestration: run provider, persist, index, record usage."""
from __future__ import annotations

import logging
import time

from ..ai.embeddings import INDEX_VERSION, get_embedding_provider
from ..ai.provider import get_provider
from ..repo import analysis as arepo
from ..repo import ops as orepo
from ..repo import reviews as rrepo
from . import rag

log = logging.getLogger("services.analysis")


def _record_usage(conn, provider, operation: str, *, restaurant_id, user_id, status: str) -> None:
    usage = getattr(provider, "last_usage", None) or {}
    est = None
    if usage.get("input_tokens") is not None and usage.get("output_tokens") is not None:
        est = provider._estimate_cost_micros(usage["input_tokens"], usage["output_tokens"]) \
            if hasattr(provider, "_estimate_cost_micros") else None
    orepo.record_usage(
        conn,
        user_id=user_id, restaurant_id=restaurant_id, operation=operation,
        provider=usage.get("provider", provider.meta().provider),
        model=usage.get("model", provider.meta().model_id),
        input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
        estimated_cost_micros=est, pricing_version=usage.get("pricing_version"),
        latency_ms=usage.get("latency_ms"), status=status,
    )


def index_review(conn, review: dict) -> None:
    emb = get_embedding_provider()
    vector = emb.embed(review["review_text"])
    arepo.upsert_embedding(
        conn, review["id"], review["restaurant_id"],
        embedding_model=emb.model_name, index_version=INDEX_VERSION, vector=vector,
    )


def analyze_review(conn, review_id: int, *, user_id: int | None = None,
                   operation: str = "sentiment_aspects") -> dict:
    review = rrepo.get_review(conn, review_id)
    if not review:
        raise ValueError("review not found")
    provider = get_provider()
    meta = provider.meta()
    rrepo.set_analysis_status(conn, review_id, "processing")
    started = time.perf_counter()
    try:
        result = provider.analyze_review(review["review_text"], review["rating"])
        duration_ms = int((time.perf_counter() - started) * 1000)
        analysis_id = arepo.add_analysis(
            conn, review_id,
            provider=meta.provider, model_id=meta.model_id, model_version=meta.model_version,
            prompt_version=meta.prompt_version, sentiment=result.sentiment,
            confidence=result.confidence,
            aspects=[a.model_dump() for a in result.aspects], topics=result.topics,
            summary=result.summary, status="done", duration_ms=duration_ms,
        )
        rrepo.set_analysis_status(conn, review_id, "done")
        index_review(conn, review)
        rag.invalidate_cache(review["restaurant_id"])
        _record_usage(conn, provider, operation, restaurant_id=review["restaurant_id"],
                      user_id=user_id, status="ok")
        return arepo.list_analyses(conn, review_id)[0] | {"analysis_id": analysis_id}
    except Exception as exc:  # noqa: BLE001
        log.warning("analysis failed", extra={"ctx": {"review_id": review_id, "err": str(exc)}})
        arepo.add_analysis(
            conn, review_id, provider=meta.provider, model_id=meta.model_id,
            model_version=meta.model_version, prompt_version=meta.prompt_version,
            status="failed", error_category=type(exc).__name__,
        )
        rrepo.set_analysis_status(conn, review_id, "failed")
        _record_usage(conn, provider, operation, restaurant_id=review["restaurant_id"],
                      user_id=user_id, status="error")
        raise


def history(conn, review_id: int) -> list[dict]:
    return arepo.list_analyses(conn, review_id)
