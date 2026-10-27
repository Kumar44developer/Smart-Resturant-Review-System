"""API v1 router aggregator. Mounts every versioned resource router under a single
``api_router`` that ``main.py`` includes at ``/api/v1``."""
from __future__ import annotations

from fastapi import APIRouter

from . import ai, analytics, auth, ingestion, ops, restaurants, reviews

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(restaurants.router)
api_router.include_router(reviews.router)
api_router.include_router(ingestion.router)
api_router.include_router(analytics.router)
api_router.include_router(ai.router)
api_router.include_router(ops.router)

__all__ = ["api_router"]
