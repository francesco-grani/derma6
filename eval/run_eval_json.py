#!/usr/bin/env python3
"""Standalone deepeval runner — outputs a JSON array of results to stdout.

Run from the project root:
    python eval/run_eval_json.py

deepeval console output goes to stderr; only the JSON array goes to stdout.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure deepeval finds the API key.
# When launched via the backend, OPENAI_API_KEY is injected explicitly.
# When run standalone, fall back to loading .env ourselves.
_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
if not _key:
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
        load_dotenv(Path(__file__).parent.parent / ".env")
        _key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    except ImportError:
        pass
os.environ["OPENAI_API_KEY"] = _key or ""
os.environ["OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"

try:
    from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval
    from deepeval.test_case import LLMTestCase

    try:
        from deepeval.test_case import SingleTurnParams as _EvalParams
    except ImportError:
        from deepeval.test_case import LLMTestCaseParams as _EvalParams  # type: ignore[no-redef]
except ImportError as exc:
    print(json.dumps({"error": f"deepeval not installed: {exc}"}), flush=True)
    sys.exit(1)

_JUDGE_MODEL = "gpt-4o-mini"
_DATASET_PATH = Path(__file__).parent / "golden_dataset.json"

with _DATASET_PATH.open() as _f:
    _GOLDEN: list[dict[str, Any]] = json.load(_f)

_BY_ID: dict[str, dict] = {c["id"]: c for c in _GOLDEN}


def _build(case_id: str) -> LLMTestCase:
    row = _BY_ID[case_id]
    return LLMTestCase(
        input=row["input"],
        actual_output=row["actual_output"],
        expected_output=row.get("expected_output"),
        retrieval_context=row.get("retrieval_context") or None,
    )


# ── Metric factories (mirrors test_deepeval_evaluations.py) ──────────────────

def _spf_standard() -> GEval:
    return GEval(
        name="SPF Standard Enforcement",
        criteria=(
            "The response must recommend SPF 50+ (and PA+++ where mentioned) as the minimum. "
            "It must NOT suggest that SPF 30 or SPF 15 is sufficient. "
            "If the user asked for lower SPF, the response must explain why SPF 50+ is better."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.7,
        model=_JUDGE_MODEL,
    )


def _answer_relevancy() -> AnswerRelevancyMetric:
    return AnswerRelevancyMetric(threshold=0.7, model=_JUDGE_MODEL)


def _faithfulness() -> FaithfulnessMetric:
    return FaithfulnessMetric(threshold=0.7, model=_JUDGE_MODEL)


def _conflict_format() -> GEval:
    return GEval(
        name="Conflict Checker Output Format",
        criteria=(
            "The response must contain a 'Verdict:' line and a 'Reason:' line. "
            "The verdict must be one of: do-not-use, use-at-different-times, "
            "use-with-caution, safe, unknown_ingredient. "
            "The reason must be a non-empty explanation."
        ),
        evaluation_params=[_EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _routine_order() -> GEval:
    return GEval(
        name="Routine Order Correctness",
        criteria=(
            "Given the input products, the response must list only those products in the correct "
            "canonical skincare order: cleanser first, then toner, then serum, then moisturiser, "
            "then SPF last. Steps not present in the input must be omitted — do not penalise for "
            "missing steps that were never provided. Products that ARE listed must appear in "
            "ascending step-number order consistent with the canonical sequence."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _phased_intro() -> GEval:
    return GEval(
        name="Phased Introduction Schedule",
        criteria=(
            "The response must present a week-by-week schedule. "
            "Each active must be introduced gradually, not all at once. "
            "The schedule should span at least 2 weeks per active."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.7,
        model=_JUDGE_MODEL,
    )


def _safety() -> GEval:
    return GEval(
        name="Safety and Non-Toxicity",
        criteria=(
            "The response must be safe skincare advice. "
            "It must not recommend explicitly dangerous ingredient combinations. "
            "The tone must be helpful and cautionary where appropriate."
        ),
        evaluation_params=[_EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _unknown_ingredient() -> GEval:
    return GEval(
        name="Unknown Ingredient Handling",
        criteria=(
            "For unknown ingredients the response must: "
            "1) Return verdict 'unknown_ingredient'. "
            "2) Recommend consulting a professional. "
            "3) List the unknown ingredients clearly."
        ),
        evaluation_params=[_EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _unclassifiable_items() -> GEval:
    return GEval(
        name="Unclassifiable Items Reporting",
        criteria=(
            "Known items must be ordered correctly. "
            "Unknown items must appear in an 'Unclassifiable items:' section — "
            "they must not be silently ignored."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _oily_skin() -> GEval:
    return GEval(
        name="Oily Skin Classification",
        criteria=(
            "Given a description with oily-skin symptoms (shiny, greasy, excess sebum), "
            "the classified type must be 'oily'. "
            "The response must confirm the profile was updated."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _sensitive_skin() -> GEval:
    return GEval(
        name="Sensitive Skin Classification",
        criteria=(
            "Given reactive symptoms (redness, stinging), classified type must be 'sensitive'. "
            "Characteristics must mention reactivity or irritation."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _conflict_warning_in_schedule() -> GEval:
    return GEval(
        name="Conflict Warning in Schedule",
        criteria=(
            "When a known incompatible pair is included the response must: "
            "1) Include a warning about the conflict. "
            "2) Schedule the two conflicting actives in separate weeks. "
            "3) Still provide a usable schedule for both."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _domain_relevance() -> GEval:
    return GEval(
        name="Skincare Domain Relevance",
        criteria=(
            "The response must stay within the skincare domain (UV protection, skin health, etc.). "
            "It must not include off-topic information."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.9,
        model=_JUDGE_MODEL,
    )


# ── Test case configurations ──────────────────────────────────────────────────

_TESTS: list[dict[str, Any]] = [
    {"id": "spf-01",        "name": "test_spf_enforces_50_plus",            "metrics": [_spf_standard, _answer_relevancy]},
    {"id": "spf-02",        "name": "test_spf_redirects_low_spf",           "metrics": [_spf_standard]},
    {"id": "conflict-01",   "name": "test_conflict_known_pair_format",      "metrics": [_conflict_format, _safety]},
    {"id": "conflict-02",   "name": "test_conflict_unknown_ingredient",     "metrics": [_unknown_ingredient]},
    {"id": "routine-01",    "name": "test_routine_correct_order",           "metrics": [_routine_order]},
    {"id": "routine-02",    "name": "test_routine_unclassifiable_reported", "metrics": [_unclassifiable_items]},
    {"id": "skin-type-01",  "name": "test_skin_type_oily_classification",   "metrics": [_oily_skin]},
    {"id": "skin-type-02",  "name": "test_skin_type_sensitive_classification", "metrics": [_sensitive_skin]},
    {"id": "intro-01",      "name": "test_intro_phased_schedule",           "metrics": [_phased_intro]},
    {"id": "intro-02",      "name": "test_intro_conflict_warning",          "metrics": [_conflict_warning_in_schedule, _phased_intro]},
    {"id": "kb-01",         "name": "test_kb_search_relevance_and_faithfulness", "metrics": [_answer_relevancy, _faithfulness]},
    {"id": "kb-02",         "name": "test_kb_search_domain_scope",          "metrics": [_domain_relevance, _faithfulness]},
]


def _measure(metric: Any, test_case: LLMTestCase) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        metric.measure(test_case)
        score = float(getattr(metric, "score", 0.0) or 0.0)
        threshold = float(getattr(metric, "threshold", 0.0) or 0.0)
        if hasattr(metric, "is_successful"):
            passed = bool(metric.is_successful())
        else:
            passed = score >= threshold
        reason = getattr(metric, "reason", None)
    except Exception as exc:
        score = 0.0
        threshold = float(getattr(metric, "threshold", 0.0) or 0.0)
        passed = False
        reason = str(exc)
    return {
        "name": getattr(metric, "name", type(metric).__name__),
        "score": round(score, 4),
        "threshold": threshold,
        "passed": passed,
        "reason": reason,
        "duration_s": round(time.perf_counter() - t0, 2),
    }


def main() -> None:
    results: list[dict[str, Any]] = []
    for cfg in _TESTS:
        row = _BY_ID[cfg["id"]]
        test_case = _build(cfg["id"])
        metric_results: list[dict] = []
        all_passed = True
        for metric_fn in cfg["metrics"]:
            metric = metric_fn()
            mr = _measure(metric, test_case)
            metric_results.append(mr)
            if not mr["passed"]:
                all_passed = False
        results.append({
            "test_id": cfg["id"],
            "test_name": cfg["name"],
            "tool": row["tool"],
            "input": row["input"],
            "expected_output": row.get("expected_output"),
            "passed": all_passed,
            "metrics": metric_results,
        })
        # flush progress to stderr so the caller knows we're alive
        print(f"[eval] {cfg['id']} → {'PASS' if all_passed else 'FAIL'}", file=sys.stderr, flush=True)

    print(json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
