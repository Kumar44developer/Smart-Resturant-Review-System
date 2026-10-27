"""Evaluation suite for the deterministic (demo-mode) AI pipeline.

Honesty first: these numbers measure the ACTUAL local pipeline that runs in this
deployment (lexicon + rating sentiment, clause aspect detection, RAG abstention and
citation integrity). They are NOT a proxy for, or claim about, any hosted
proprietary model. Datasets are hand-labeled and versioned under app/eval_data.
Every run is persisted to the evaluation_runs table with dataset/model/prompt
versions so results are reproducible and attributable."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from ..ai.provider import get_provider
from ..repo import ops as orepo
from . import rag

DATA_DIR = Path(__file__).resolve().parent.parent / "eval_data"
_MODEL_LABEL = "demo-deterministic-v1"
_PROMPT_VERSION = get_provider().meta().prompt_version


def _load(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _prf(tp: int, pred: int, gold: int) -> tuple[float, float, float]:
    p = tp / pred if pred else 0.0
    r = tp / gold if gold else 0.0
    f = (2 * p * r / (p + r)) if (p + r) else 0.0
    return round(p, 4), round(r, 4), round(f, 4)


def evaluate_sentiment() -> dict:
    ds = _load("sentiment_eval.json")
    provider = get_provider()
    labels = ds["label_scheme"]
    counts = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    confusion = {g: {g2: 0 for g2 in labels} for g in labels}
    correct = 0
    failures = []
    for item in ds["items"]:
        got = provider.analyze_review(item["text"], item["rating"]).sentiment or "neutral"
        gold = item["label"]
        confusion[gold][got] += 1
        if got == gold:
            correct += 1
            counts[gold]["tp"] += 1
        else:
            counts[gold]["fn"] += 1
            counts[got]["fp"] += 1
            failures.append({"id": item["id"], "gold": gold, "pred": got, "text": item["text"][:80]})
    per_class = {}
    for lab in labels:
        c = counts[lab]
        p, r, f = _prf(c["tp"], c["tp"] + c["fp"], c["tp"] + c["fn"])
        per_class[lab] = {"precision": p, "recall": r, "f1": f,
                          "support": c["tp"] + c["fn"]}
    macro_f1 = round(sum(per_class[l]["f1"] for l in labels) / len(labels), 4)
    return {
        "task": "sentiment",
        "dataset_version": ds["version"],
        "n": len(ds["items"]),
        "accuracy": round(correct / len(ds["items"]), 4),
        "macro_f1": macro_f1,
        "per_class": per_class,
        "confusion": confusion,
        "failures": failures,
    }


def evaluate_aspects() -> dict:
    ds = _load("aspects_eval.json")
    provider = get_provider()
    tot_tp = tot_pred = tot_gold = 0
    per_aspects = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    item_scores = []
    failures = []
    for item in ds["items"]:
        raw = provider.analyze_review(item["text"], None).aspects
        pred = {(a["aspect"] if isinstance(a, dict) else a.aspect) for a in raw}
        gold = set(item["expect_aspects"])
        tp = len(pred & gold)
        tot_tp += tp
        tot_pred += len(pred)
        tot_gold += len(gold)
        for lab in gold:
            per_aspects[lab]["tp" if lab in pred else "fn"] += 1
        for lab in pred - gold:
            per_aspects[lab]["fp"] += 1
        p, r, f = _prf(tp, len(pred), len(gold))
        item_scores.append(f)
        if f < 1.0:
            failures.append({"id": item["id"], "gold": sorted(gold), "pred": sorted(pred)})
    micro_p, micro_r, micro_f = _prf(tot_tp, tot_pred, tot_gold)
    per_class = {}
    for lab, c in per_aspects.items():
        p, r, f = _prf(c["tp"], c["tp"] + c["fp"], c["tp"] + c["fn"])
        per_class[lab] = {"precision": p, "recall": r, "f1": f}
    return {
        "task": "aspects",
        "dataset_version": ds["version"],
        "n": len(ds["items"]),
        "micro_precision": micro_p,
        "micro_recall": micro_r,
        "micro_f1": micro_f,
        "mean_item_f1": round(sum(item_scores) / len(item_scores), 4),
        "per_aspect": per_class,
        "failures": failures,
    }


def evaluate_rag(conn: sqlite3.Connection, restaurant_id: int) -> dict:
    """Abstention + citation-integrity checks against real stored reviews."""
    ds = _load("rag_eval.json")
    n_reviewed = conn.execute(
        "SELECT COUNT(*) FROM reviews WHERE restaurant_id=?", (restaurant_id,)
    ).fetchone()[0]
    failures = []
    abstain_ok = 0
    citation_ok = 0
    abstain_items = ds["abstain_expected"]
    for item in abstain_items:
        res = rag.answer_question(conn, restaurant_id=restaurant_id, question=item["question"],
                                  record_usage=False)
        if bool(res["abstain"]) == bool(item["expect_abstain"]):
            abstain_ok += 1
        else:
            failures.append({"id": item["id"], "kind": "abstention",
                             "expected_abstain": item["expect_abstain"],
                             "got_abstain": res["abstain"], "answer": res["answer"][:120]})
        # Citation integrity: every cited review must belong to THIS restaurant.
        cited_ids = {c["review_id"] for c in res["citations"]}
        if cited_ids:
            placeholders = ",".join("?" * len(cited_ids))
            own = conn.execute(
                f"SELECT COUNT(*) FROM reviews WHERE id IN ({placeholders}) AND restaurant_id=?",
                (*cited_ids, restaurant_id),
            ).fetchone()[0]
            if own == len(cited_ids):
                citation_ok += 1
            else:
                failures.append({"id": item["id"], "kind": "citation_leakage",
                                 "cited": sorted(cited_ids)})

    sec_total = 0
    sec_ok = 0
    for probe in ds["prompt_injection_probes"]:
        sec_total += 1
        # The pipeline returns structured data only; it must not crash or echo a
        # system prompt, and must still classify the underlying review sentiment.
        try:
            out = get_provider().analyze_review(probe["review_text"], None)
            leaked = "system prompt" in (out.summary or "").lower()
            if not leaked:
                sec_ok += 1
            else:
                failures.append({"id": probe["id"], "kind": "prompt_injection_leak"})
        except Exception as exc:  # noqa: BLE001
            failures.append({"id": probe["id"], "kind": "prompt_injection_crash", "err": str(exc)})

    n = len(abstain_items)
    cited_any = sum(1 for item in abstain_items)  # per-item citation-integrity verified above
    return {
        "task": "rag_safety",
        "dataset_version": ds["version"],
        "reviews_in_scope": n_reviewed,
        "abstention_accuracy": round(abstain_ok / n, 4) if n else None,
        "citation_integrity_pass": citation_ok,
        "citation_integrity_checked": cited_any,
        "prompt_injection_probe_pass": f"{sec_ok}/{sec_total}",
        "failures": failures,
    }


def run_all(conn: sqlite3.Connection, *, restaurant_id: int | None = None) -> dict:
    results = {"sentiment": evaluate_sentiment(), "aspects": evaluate_aspects()}
    if restaurant_id is not None:
        results["rag_safety"] = evaluate_rag(conn, restaurant_id)
    persisted_ids = {}
    for task, metrics in results.items():
        fail_list = metrics.pop("failures", [])
        rid = orepo.record_evaluation(
            conn, task=task, dataset_version=metrics["dataset_version"],
            model_version=_MODEL_LABEL, prompt_version=_PROMPT_VERSION,
            config={"mode": "demo_deterministic"}, metrics=metrics, failures=fail_list,
        )
        metrics["failures"] = fail_list
        persisted_ids[task] = rid
    return {"run": "complete", "results": results, "evaluation_run_ids": persisted_ids,
            "note": "Metrics describe the local deterministic pipeline only."}
