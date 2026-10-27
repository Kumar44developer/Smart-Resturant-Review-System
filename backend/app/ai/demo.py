"""Deterministic, clearly-labeled demo provider.

Produces real, reproducible results from the local NLP module (no external
call), so the entire application is usable and testable without any AI
credentials. Every output is labeled demo in metadata/UI. See docs/AI_DESIGN.md.
"""
from __future__ import annotations

from collections import Counter

from .base import LLMProvider, ProviderMeta, ReviewContext
from .nlp import detect_aspects, extract_topics, lexicon_sentiment, rating_to_sentiment
from .schemas import AnalysisResult, ChatAnswer

_SERIOUS = ("got sick", "food poisoning", "undercooked", "raw", "allergen", "allergy",
             "hair", "insect", "bug", "vomit", "hospital")


class DemoProvider(LLMProvider):
    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            provider="demo", model_id="deterministic-nlp-v1",
            model_version="1.0", prompt_version=self.PROMPT_VERSION, is_demo=True,
        )

    def analyze_review(self, text: str, rating: float | None) -> AnalysisResult:
        label, score = lexicon_sentiment(text)
        # Fall back to the explicit star rating only when the text is neutral.
        if label == "neutral" and rating is not None:
            label = rating_to_sentiment(rating) or label
        aspects = detect_aspects(text)
        topics = extract_topics(text)
        summary = self._summary(label, topics, aspects)
        return AnalysisResult(
            sentiment=label,
            confidence=round(min(0.99, 0.5 + abs(score) / 2), 3),
            aspects=aspects,  # type: ignore[arg-type]
            topics=topics,
            summary=summary,
        )

    @staticmethod
    def _summary(label: str, topics: list[str], aspects: list[dict]) -> str:
        tone = {"positive": "Positive", "negative": "Negative", "neutral": "Mixed/neutral"}[label]
        themes = ", ".join(topics[:4]) if topics else "general experience"
        return f"{tone} review touching on {themes}."

    def draft_reply(self, ctx: ReviewContext, tone: str, length: str) -> str:
        neg_aspects = [a["aspect"] for a in ctx.aspects if a.get("sentiment") == "negative"]
        pos_aspects = [a["aspect"] for a in ctx.aspects if a.get("sentiment") == "positive"]
        low = ctx.text.lower()
        serious = any(k in low for k in _SERIOUS)

        greeting = "Hi there," if tone == "friendly" else "Dear guest,"
        parts = [greeting]
        if pos_aspects:
            parts.append(f"Thank you for the kind words about our {', '.join(pos_aspects[:2])}.")
        if neg_aspects:
            parts.append(
                f"We're sorry to hear your {', '.join(neg_aspects[:2])} experience fell short of what we aim for."
            )
        elif not pos_aspects:
            parts.append("Thank you for taking the time to share your feedback.")
        if serious:
            parts.append(
                "Your mention of a possible food-safety concern is important to us; "
                "a member of our team will follow up with you directly to understand exactly what happened."
            )
        else:
            parts.append("We've shared your notes with the team as we review how to improve.")
        if tone == "concise":
            parts = parts[:3]
        if tone == "empathetic":
            parts.append("We genuinely want to do better by you.")
        parts.append("— The management team")
        return " ".join(parts).strip()

    def answer_with_evidence(self, question: str, evidence: list[dict],
                             conversation: list[dict] | None = None) -> ChatAnswer:
        if not evidence:
            return ChatAnswer(
                answer="I don't have enough stored review evidence in the selected scope to answer that reliably.",
                abstain=True, reason="no_evidence",
            )
        ids = [e["review_id"] for e in evidence]
        themes = Counter()
        for e in evidence:
            for t in (e.get("topics") or []):
                themes[t] += 1
        top = ", ".join(f"{t} ({c})" for t, c in themes.most_common(3)) or "no repeated themes"
        n = len(evidence)
        answer = (
            f"Based on {n} matching review(s), the most frequent themes are: {top}. "
            "See the cited reviews below for the supporting excerpts."
        )
        return ChatAnswer(answer=answer, cited_review_ids=ids, abstain=False)
