"""Pluggable embedding providers behind one interface.

Default = deterministic hashing vectorizer (pure Python, works offline and under
the local security policy). A real OpenAI-compatible /v1/embeddings provider is
used automatically when AI_EMBEDDING_MODEL is configured, without any change to
calling code. See docs/RAG_DESIGN.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from ..config import settings
from .nlp import hash_embed

INDEX_VERSION = "idx-1"


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder(EmbeddingProvider):
    model_name = "hashing-256"

    def embed(self, text: str) -> list[float]:
        return hash_embed(text, dim=256)


class OpenAICompatEmbedder(EmbeddingProvider):
    def __init__(self, model: str) -> None:
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def embed(self, text: str) -> list[float]:
        url = settings.ai_base_url.rstrip("/") + "/embeddings"
        headers = {"Authorization": f"Bearer {settings.ai_api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
            resp = client.post(url, json={"model": self._model, "input": text}, headers=headers)
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]


_singleton: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    global _singleton
    if _singleton is None:
        if settings.ai_embedding_model and settings.ai_api_key:
            _singleton = OpenAICompatEmbedder(settings.ai_embedding_model)
        else:
            _singleton = HashingEmbedder()
    return _singleton
