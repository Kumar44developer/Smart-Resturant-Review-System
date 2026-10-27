"""Pure-Python NLP building blocks (no numpy / no scikit-learn).

These replace the libraries named in the original plan because the local
Windows Smart App Control policy blocks their compiled wheels. Implementations
are real (not stubs): lexicon sentiment, TF bag-of-words Multinomial Naive Bayes,
aspect detection, controlled topic normalization, and a hashing-vectorizer +
cosine similarity used for semantic retrieval in demo mode. See docs/AI_DESIGN.md.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from typing import Iterable

# ---------------------------------------------------------------- tokenizer
_TOKEN_RE = re.compile(r"[a-z']+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


# ---------------------------------------------------------------- sentiment lexicon
_POS = {
    "good", "great", "awesome", "excellent", "amazing", "fantastic", "love", "loved",
    "delicious", "tasty", "fresh", "friendly", "helpful", "quick", "fast", "clean",
    "cozy", "wonderful", "best", "recommend", "recommended", "happy", "impressive",
    "perfect", "nice", "warm", "generous", "value", "tender", "professional",
}
_NEG = {
    "bad", "terrible", "awful", "horrible", "poor", "slow", "cold", "dirty", "rude",
    "disappointing", "disappointed", "overpriced", "expensive", "soggy", "stale",
    "worst", "never", "waited", "delay", "delayed", "burnt", "bland", "gross",
    "unfriendly", "unclean", "undercooked", "overcooked", "mushy", "noise", "noisy",
    "refuse", "refused", "unappetizing", "understaffed",
}
_INTENSIFIERS = {"very", "extremely", "really", "so", "incredibly", "super"}
_NEGATORS = {"not", "no", "never", "hardly", "barely", "isnt", "wasnt", "dont", "doesnt"}

ASPECTS = [
    "food", "service", "pricing", "cleanliness", "ambience",
    "delivery", "portion", "waiting_time", "staff", "overall",
]

_ASPECT_KEYWORDS: dict[str, list[str]] = {
    "food": ["food", "dish", "dishes", "meal", "pasta", "pizza", "burger", "steak", "salad",
             "soup", "curry", "rice", "noodle", "dessert", "coffee", "taste", "flavor", "sauce"],
    "service": ["service", "servicing", "server", "servers", "waiter", "waitress", "attended"],
    "pricing": ["price", "prices", "cost", "expensive", "cheap", "affordable", "overpriced", "value", "bill"],
    "cleanliness": ["clean", "cleanliness", "hygiene", "dirty", "spotless", "restroom", "kitchen"],
    "ambience": ["ambience", "ambiance", "atmosphere", "decor", "lighting", "music", "cozy", "noise", "noisy", "view"],
    "delivery": ["delivery", "deliver", "courier", "packaging", "packed", "takeaway", "takeout", "rider"],
    "portion": ["portion", "portions", "serving", "servings", "quantity", "size", "generous", "small"],
    "waiting_time": ["wait", "waited", "waiting", "queue", "delay", "delayed", "slow", "time"],
    "staff": ["staff", "employee", "employees", "cashier", "host", "crew", "bartender"],
    "overall": ["overall", "experience", "visit", "restaurant", "place", "everything", "would", "again"],
}

# Controlled topic taxonomy: normalized label -> trigger phrases. Prevents
# uncontrolled duplicate labels from appearing across reviews.
_TOPIC_PATTERNS: list[tuple[str, list[str]]] = [
    ("Fresh food", ["fresh food", "fresh ingredients", "so fresh"]),
    ("Tasty food", ["delicious", "tasty", "flavorful", "flavour"]),
    ("Slow service", ["slow service", "took forever", "waited a long time", "so slow", "slow to"]),
    ("Friendly staff", ["friendly staff", "friendly server", "welcoming", "nice staff", "attentive"]),
    ("Rude staff", ["rude", "unfriendly", "dismissive", "ignored us"]),
    ("High prices", ["expensive", "overpriced", "pricey", "too much for"]),
    ("Good value", ["good value", "great value", "affordable", "fair price", "worth it"]),
    ("Small portions", ["small portion", "tiny portion", "not enough food", "portion was small"]),
    ("Generous portions", ["generous portion", "huge portion", "lots of food"]),
    ("Clean environment", ["clean", "spotless", "well kept", "hygienic"]),
    ("Dirty environment", ["dirty", "filthy", "sticky table", "unclean"]),
    ("Cozy ambience", ["cozy", "warm atmosphere", "nice ambience", "lovely decor"]),
    ("Noisy environment", ["noisy", "loud music", "too loud"]),
    ("Late delivery", ["late delivery", "delivery was slow", "took long to deliver", "cold when it arrived"]),
    ("Poor packaging", ["packaging", "spilled", "leaked", "messy packaging"]),
    ("Bad food safety", ["got sick", "food poisoning", "undercooked", "raw", "bad stomach"]),
]


def lexicon_sentiment(text: str) -> tuple[str, float]:
    """Baseline classifier: returns (label, score in [-1, 1])."""
    tokens = tokenize(text)
    score = 0.0
    for i, tok in enumerate(tokens):
        w = 1.0
        prev = tokens[i - 1] if i else ""
        prev2 = tokens[i - 2] if i >= 2 else ""
        if prev in _INTENSIFIERS or prev2 in _INTENSIFIERS:
            w = 1.6
        negated = prev in _NEGATORS or prev2 in _NEGATORS
        if tok in _POS:
            score += -w if negated else w
        elif tok in _NEG:
            score += w if negated else -w
    magnitude = math.tanh(score / 4.0)
    if magnitude > 0.15:
        return "positive", magnitude
    if magnitude < -0.15:
        return "negative", magnitude
    return "neutral", magnitude


def rating_to_sentiment(rating: float | None) -> str | None:
    if rating is None:
        return None
    if rating >= 4:
        return "positive"
    if rating <= 2:
        return "negative"
    return "neutral"


def _sentence_score(sentence: str) -> float:
    return lexicon_sentiment(sentence)[1]


def detect_aspects(text: str) -> list[dict]:
    """Return per-aspect sentiment with a supporting excerpt. Mixed opinions kept.

    Scoring is done per CLAUSE (split on sentence and comma/semicolon boundaries)
    so a single sentence like "food was great, but service was slow" correctly
    yields food=positive and service=negative instead of cancelling to neutral."""
    clauses = [c for c in re.split(r"(?<=[.!?])\s+|[,\n;]", text.strip()) if c and c.strip()]
    found: dict[str, dict] = {}
    for clause in clauses:
        c_tokens = set(tokenize(clause))
        score = _sentence_score(clause)
        label = "positive" if score > 0.12 else "negative" if score < -0.12 else "neutral"
        for aspect, keywords in _ASPECT_KEYWORDS.items():
            hit = next((kw for kw in keywords if kw in c_tokens), None)
            if not hit:
                continue
            excerpt = clause.strip()
            current = found.get(aspect)
            # keep the clause with the strongest sentiment signal for this aspect;
            # tie-break by preferring a non-neutral reading.
            if current is None or abs(score) > abs(current["score"]):
                found[aspect] = {
                    "aspect": aspect, "sentiment": label,
                    "score": score, "excerpt": excerpt,
                }
    return list(found.values())


def extract_topics(text: str) -> list[str]:
    low = text.lower()
    topics: list[str] = []
    for label, patterns in _TOPIC_PATTERNS:
        if any(p in low for p in patterns) and label not in topics:
            topics.append(label)
    return topics


# ---------------------------------------------------------------- hashing embeddings
def hash_embed(text: str, dim: int = 256) -> list[float]:
    """Deterministic signed hashing vectorizer (feature hashing) + L2 normalize.

    Free of any corpus/idf and of numpy; stable across processes, which is what
    demo-mode retrieval needs. A real provider embedder plugs in behind the same
    interface in production (see ai/embeddings.py)."""
    vec = [0.0] * dim
    tokens = tokenize(text)
    for tok, cnt in Counter(tokens).items():
        h = int(hashlib.blake2b(tok.encode(), digest_size=8).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) & 1 else -1.0
        vec[idx] += sign * (1.0 + math.log(cnt))
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


# ---------------------------------------------------------------- baseline NB classifier
class BagOfWordsNB:
    """Multinomial Naive Bayes with Laplace smoothing over bag-of-words counts.

    Trained on the labeled synthetic corpus; provides a real, reproducible
    baseline model to compare against the LLM classifier in the eval report."""

    def __init__(self) -> None:
        self.class_counts: Counter[str] = Counter()
        self.term_counts: dict[str, Counter[str]] = defaultdict(Counter)
        self.class_total: Counter[str] = Counter()
        self.vocab: set[str] = set()
        self.trained = False

    def fit(self, docs: Iterable[tuple[str, str]]) -> "BagOfWordsNB":
        for text, label in docs:
            self.class_counts[label] += 1
            toks = tokenize(text)
            self.vocab.update(toks)
            self.term_counts[label].update(toks)
            self.class_total[label] += len(toks)
        self.trained = True
        return self

    def predict_proba(self, text: str) -> dict[str, float]:
        total_docs = sum(self.class_counts.values()) or 1
        V = len(self.vocab) or 1
        scores: dict[str, float] = {}
        toks = tokenize(text)
        for label in self.class_counts:
            logp = math.log(self.class_counts[label] / total_docs)
            denom = self.class_total[label] + V
            for tok in toks:
                num = self.term_counts[label][tok] + 1
                logp += math.log(num / denom)
            scores[label] = logp
        return scores

    def predict(self, text: str) -> tuple[str, float]:
        probs = self.predict_proba(text)
        if not probs:
            return "neutral", 0.0
        # softmax for a calibrated-looking confidence value
        m = max(probs.values())
        exp = {k: math.exp(v - m) for k, v in probs.items()}
        s = sum(exp.values()) or 1.0
        norm = {k: v / s for k, v in exp.items()}
        label = max(norm, key=norm.get)
        return label, round(norm[label], 4)
