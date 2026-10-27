"""Provider-neutral LLM interface. Providers are replaceable behind this ABC."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .schemas import AnalysisResult, ChatAnswer


@dataclass
class ReviewContext:
    review_id: int
    text: str
    rating: float | None
    source: str
    aspects: list[dict]
    restaurant_name: str
    restaurant_context: str | None


@dataclass
class ProviderMeta:
    provider: str
    model_id: str
    model_version: str
    prompt_version: str
    is_demo: bool


class LLMProvider(ABC):
    PROMPT_VERSION = "v1"

    @abstractmethod
    def meta(self) -> ProviderMeta: ...

    @abstractmethod
    def analyze_review(self, text: str, rating: float | None) -> AnalysisResult: ...

    @abstractmethod
    def draft_reply(self, ctx: ReviewContext, tone: str, length: str) -> str: ...

    @abstractmethod
    def answer_with_evidence(self, question: str, evidence: list[dict],
                             conversation: list[dict] | None = None) -> ChatAnswer: ...
