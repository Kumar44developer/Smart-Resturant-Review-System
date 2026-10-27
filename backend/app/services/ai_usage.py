"""Shared AI usage accounting.

Records one row per model/provider *call* so the per-tenant `usage` endpoint
reflects every AI operation (analysis, RAG chat, reply drafting), not just
analysis. With the local demo provider there are no real tokens, so cost stays
NULL (we never fabricate a number); latency falls back to measured wall time.
With a hosted provider, real token counts and estimated micro-unit cost are
recorded alongside the pricing version."""
from __future__ import annotations

from ..repo import ops as orepo


def record(conn, provider, operation: str, *, restaurant_id=None, user_id=None,
           status: str = "ok", measured_ms: int | None = None) -> None:
    usage = getattr(provider, "last_usage", None) or {}
    in_tok = usage.get("input_tokens")
    out_tok = usage.get("output_tokens")
    est = None
    if in_tok is not None and out_tok is not None and hasattr(provider, "_estimate_cost_micros"):
        est = provider._estimate_cost_micros(in_tok, out_tok)
    meta = provider.meta()
    orepo.record_usage(
        conn, user_id=user_id, restaurant_id=restaurant_id, operation=operation,
        provider=usage.get("provider", meta.provider),
        model=usage.get("model", meta.model_id),
        input_tokens=in_tok, output_tokens=out_tok,
        estimated_cost_micros=est, pricing_version=usage.get("pricing_version"),
        latency_ms=usage.get("latency_ms", measured_ms), status=status,
    )
