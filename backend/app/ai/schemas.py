"""Validated model-output schemas. Malformed LLM results are rejected here."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .nlp import ASPECTS

Sentiment = Literal["positive", "neutral", "negative"]


class AspectResult(BaseModel):
    aspect: str
    sentiment: Sentiment
    excerpt: str | None = None
    explanation: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("aspect")
    @classmethod
    def _norm_aspect(cls, v: str) -> str:
        v = v.strip().lower().replace(" ", "_")
        if v not in ASPECTS:
            raise ValueError(f"unknown aspect '{v}'")
        return v


class AnalysisResult(BaseModel):
    sentiment: Sentiment
    confidence: float | None = Field(default=None, ge=0, le=1)
    aspects: list[AspectResult] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    summary: str | None = None


class ChatAnswer(BaseModel):
    answer: str
    cited_review_ids: list[int] = Field(default_factory=list)
    abstain: bool = False
    reason: str | None = None


class Recommendation(BaseModel):
    proposed_action: str
    supporting_theme: str | None = None
    supporting_review_ids: list[int] = Field(default_factory=list)
    support_count: int = 0
    priority_rationale: str | None = None
    uncertainty: str | None = None
