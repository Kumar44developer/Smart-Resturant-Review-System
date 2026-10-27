# AI Design

How the AI layer works, what is *measured* vs *generated*, and why the default
provider is honest by construction. Referenced from `ai/nlp.py`, `ai/demo.py`,
`ai/embeddings.py`, and `services/recommendations.py`.

## 1. The provider seam

`ai/base.py` defines an abstract `LLMProvider`:

| Method | Purpose |
|--------|---------|
| `analyze_review(text, rating)` → `AnalysisResult` | sentiment label + confidence + aspects + topics + summary |
| `draft_reply(ctx, tone, length)` → str | grounded response draft |
| `answer_with_evidence(question, evidence, history)` → `ChatAnswer` | RAG answer + cited review ids + abstain flag |
| `meta()` → `ProviderMeta` | provider/model/prompt versions + `is_demo` |

`provider.get_provider()` returns the **demo** provider whenever
`settings.demo_mode` is true (no `AI_API_KEY` or `AI_PROVIDER != openai_compat`);
otherwise the **OpenAI-compatible** (Groq) adapter. Business logic never branches
on which provider is active — swapping is pure configuration.

## 2. Deterministic NLP (`ai/nlp.py`) — the demo pipeline

Real implementations, not stubs, written to avoid numpy/scikit-learn (blocked by
Smart App Control on the host):

- **Tokenizer**: `[a-z']+` over lowercased text.
- **Lexicon sentiment**: positive/negative word lists with **intensifiers** (×1.6)
  and **negators** (flip). Score is squashed with `tanh(score/4)`; thresholds
  ±0.15 → positive/neutral/negative.
- **Rating fallback**: `DemoProvider.analyze_review` uses the star rating
  (≥4 positive, ≤2 negative) **only when the text itself reads neutral**, so an
  explicit signal isn't discarded but text still wins.
- **Aspect detection**: scores **per clause** (split on `.!?` boundaries and
  `, ; \n`) against a keyword lexicon for 10 aspects, keeping the strongest-
  sentiment clause per aspect with its excerpt. This preserves **mixed sentiment**
  ("food great, service slow" → food=positive, service=negative).
- **Topic extraction**: a **controlled taxonomy** (`_TOPIC_PATTERNS`) of trigger
  phrases → normalised labels, preventing label drift across reviews.
- **BagOfWordsNB**: a from-scratch Multinomial Naive Bayes (Laplace-smoothed) kept
  as a reproducible baseline for the eval report.
- **hash_embed**: signed feature hashing (blake2b, dim 256, `1+log(count)` weights,
  L2-normalised) + `cosine`. Deterministic and corpus-free — ideal for offline
  retrieval. A real embedder plugs in behind `EmbeddingProvider` unchanged.

## 3. Measured facts vs generated interpretation

`AnalysisResult` keeps them distinct, and so does the `review_analyses` table:

- **Measured** (deterministic, reproducible): `sentiment`, `confidence`,
  `aspects` (each with a supporting `excerpt`), `topics`.
- **Generated** (model narration): `summary`. In the demo provider the summary is a
  literal template over the measured themes ("Negative review touching on Slow
  service, Rude staff.") — never a claim the data doesn't support.

A hosted model may produce a richer `summary`, but the measured fields remain the
source of truth for dashboards; summaries are labelled as interpretation.

## 4. Demo answer generation

`DemoProvider.answer_with_evidence`:
- **No evidence in scope → abstain** (`reason="no_evidence"`), with an honest message.
- Otherwise it aggregates the retrieved reviews' **topics** into a frequency count
  and answers strictly from those, citing **all** retrieved review ids. The RAG
  layer then re-validates those citations against the tenant's allowed set.

This is intentionally modest: in demo mode the assistant reports *what the stored
reviews say*, and points at them, rather than inventing narrative.

## 5. Reply drafting (`draft_reply`)

Assembled from the review's **measured** aspects: thanks for positive aspects, an
apology naming the negative ones, and a **food-safety escalation branch** when
serious keywords appear ("got sick", "undercooked", "hair"…). Tone/length are
controls, not fabrications. Output is always stored with `is_ai_generated=1` and
requires human approval before it could ever be sent (there is no send path).

## 6. Recommendations = measured correlation, not causation

`services/recommendations.py` turns repeated negative aspects into prioritised
actions. Every recommendation carries `supporting_review_ids`, a `support_count`,
a `priority_rationale` (frequency-based), and an explicit `uncertainty` note:
*"Correlation with dissatisfaction only; no causal or revenue impact is measured."*

## 7. Guarding honesty in evaluation

`services/evaluation.py` measures **this** pipeline (not a hosted model it didn't
run): sentiment accuracy/macro-F1 + confusion, aspect micro-P/R/F1 + mean item-F1,
and RAG abstention + citation-integrity + prompt-injection probes. Each run is
persisted with `dataset_version`, `model_version` (`demo-deterministic-v1`), and
`prompt_version`, and the result is stamped with:
*"Metrics describe the local deterministic pipeline only."*
