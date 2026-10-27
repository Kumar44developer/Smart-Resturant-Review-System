"""Provider factory: picks the configured LLM provider from settings."""
from __future__ import annotations

from .base import LLMProvider
from .demo import DemoProvider
from .openai_compat import OpenAICompatProvider

_cache: dict[str, LLMProvider] = {}


def get_provider() -> LLMProvider:
    from ..config import settings
    kind = "demo" if settings.demo_mode else "openai_compat"
    if kind not in _cache:
        _cache[kind] = DemoProvider() if kind == "demo" else OpenAICompatProvider()
    return _cache[kind]
