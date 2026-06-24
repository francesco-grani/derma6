#!/usr/bin/env python3
"""Standalone deepeval runner — outputs a JSON array of results to stdout.

Run from the project root:
    python eval/run_eval_json.py

deepeval console output goes to stderr; only the JSON array goes to stdout.

Live capture (recommended before a full eval run):
    python eval/capture_outputs.py --update-golden
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
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualPrecisionMetric,
        ContextualRecallMetric,
        ContextualRelevancyMetric,
        FaithfulnessMetric,
        GEval,
    )
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


# ── Metric factories ──────────────────────────────────────────────────────────

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


def _contextual_relevancy() -> ContextualRelevancyMetric:
    return ContextualRelevancyMetric(threshold=0.7, model=_JUDGE_MODEL)


def _contextual_precision() -> ContextualPrecisionMetric:
    return ContextualPrecisionMetric(threshold=0.7, model=_JUDGE_MODEL)


def _contextual_recall() -> ContextualRecallMetric:
    return ContextualRecallMetric(threshold=0.7, model=_JUDGE_MODEL)


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


class _RoutineOrderMetric:
    """Programmatic check: canonical order cleanser → toner → serum → moisturiser → spf.

    Uses string-position comparison rather than an LLM judge, which hallucinated
    wrong facts about skincare canonical order (see handoff 2026-06-24).
    """

    name = "Routine Order Correctness"
    threshold = 0.8
    score: float = 0.0
    reason: str | None = None

    def measure(self, test_case: Any) -> float:
        out = test_case.actual_output.lower()
        _canonical = ["cleanser", "toner", "serum", "moisturiser", "spf"]
        positions = {s: out.find(f"{s}:") for s in _canonical}
        present = {k: v for k, v in positions.items() if v >= 0}
        ordered = [s for s in _canonical if s in present]
        if ordered == sorted(ordered, key=lambda s: present[s]):
            self.score = 1.0
            self.reason = f"Correct order: {' → '.join(ordered)}"
        else:
            self.score = 0.0
            self.reason = "Out-of-order: " + ", ".join(
                f"{s}@{present[s]}" for s in ordered
            )
        return self.score

    def is_successful(self) -> bool:
        return self.score >= self.threshold


def _routine_order() -> _RoutineOrderMetric:
    return _RoutineOrderMetric()


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


class _UnclassifiableItemsMetric:
    """Programmatic check: every input item must appear in either the routine order
    or the 'Unclassifiable items:' section — nothing silently dropped."""

    name = "Unclassifiable Items Reporting"
    threshold = 0.8
    score: float = 0.0
    reason: str | None = None

    def measure(self, test_case: Any) -> float:
        out = test_case.actual_output
        items = [i.strip().lower() for i in test_case.input.split(",") if i.strip()]
        if "Unclassifiable items:" not in out:
            self.score = 0.0
            self.reason = "Missing 'Unclassifiable items:' section"
            return self.score
        routine_part, unclass_part = out.lower().split("unclassifiable items:", 1)
        dropped = [i for i in items if i not in routine_part and i not in unclass_part]
        if dropped:
            self.score = 0.0
            self.reason = f"Silently dropped items: {dropped}"
        else:
            self.score = 1.0
            self.reason = "All input items accounted for"
        return self.score

    def is_successful(self) -> bool:
        return self.score >= self.threshold


def _unclassifiable_items() -> _UnclassifiableItemsMetric:
    return _UnclassifiableItemsMetric()


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


def _seasonal_spf() -> GEval:
    return GEval(
        name="Seasonal SPF Consistency",
        criteria=(
            "The response must recommend SPF 50+ regardless of season. "
            "It should clarify that UV radiation is present year-round, including winter."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.7,
        model=_JUDGE_MODEL,
    )


def _safe_pair() -> GEval:
    return GEval(
        name="Safe Pair Recognition",
        criteria=(
            "The verdict must be 'safe'. "
            "The reason must explain why the combination is not harmful, "
            "ideally addressing the common misconception about these two ingredients."
        ),
        evaluation_params=[_EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _exfoliation_stack() -> GEval:
    return GEval(
        name="Exfoliation Stack Warning",
        criteria=(
            "The verdict must be 'use-at-different-times'. "
            "The reason must mention the risk of over-exfoliation or skin barrier disruption."
        ),
        evaluation_params=[_EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _multi_serum_order() -> GEval:
    return GEval(
        name="Multi-Serum Ordering",
        criteria=(
            "When multiple serums are present, they must all be grouped in the serum step "
            "between cleanser and SPF. Their relative order within the serum step should match "
            "the order they appeared in the input."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _combination_skin() -> GEval:
    return GEval(
        name="Combination Skin Classification",
        criteria=(
            "Given symptoms that describe an oily T-zone and dry cheeks, "
            "the classified type must be 'combination'. "
            "The characteristics must mention both the oily T-zone and drier cheeks."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _acneic_skin() -> GEval:
    return GEval(
        name="Acneic Skin Classification",
        criteria=(
            "Given symptoms of acne, pimples, or clogged pores, "
            "the classified type must be 'acneic'. "
            "The characteristics must mention breakouts or clogged pores."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _single_active_schedule() -> GEval:
    return GEval(
        name="Single Active Schedule",
        criteria=(
            "The schedule must cover exactly the one active provided, "
            "with a 2-week introduction block. "
            "There must be no conflict warnings (no other active to conflict with). "
            "A plan-saved confirmation must be present."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _three_active_schedule() -> GEval:
    return GEval(
        name="Three-Active Phased Schedule",
        criteria=(
            "The schedule must introduce each of the three actives in a separate 2-week block. "
            "No two actives should be introduced in the same week block. "
            "The total schedule should span at least 6 weeks."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )


def _retinol_beginner() -> GEval:
    return GEval(
        name="Retinol Beginner Guidance",
        criteria=(
            "The response must: "
            "1) Recommend starting at a low concentration. "
            "2) Recommend low initial frequency (1–3 nights per week). "
            "3) Mention the need for SPF during retinol use. "
            "4) Not suggest jumping straight to daily use."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.7,
        model=_JUDGE_MODEL,
    )


def _sunscreen_types() -> GEval:
    return GEval(
        name="Sunscreen Types Distinction",
        criteria=(
            "The response must explain both physical (mineral) and chemical sunscreen types. "
            "It must describe the core mechanism difference: "
            "physical reflects UV, chemical absorbs/converts UV. "
            "Both must ultimately be recommended at SPF 50+ standard."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.7,
        model=_JUDGE_MODEL,
    )


# ── Test case configurations ──────────────────────────────────────────────────

_TESTS: list[dict[str, Any]] = [
    # ── SPF Recommender ────────────────────────────────────────────────────────
    {"id": "spf-01", "name": "test_spf_enforces_50_plus",
     "metrics": [_spf_standard, _answer_relevancy]},
    {"id": "spf-02", "name": "test_spf_redirects_low_spf",
     "metrics": [_spf_standard]},
    {"id": "spf-03", "name": "test_spf_seasonal_still_50_plus",
     "metrics": [_spf_standard, _seasonal_spf]},
    {"id": "spf-04", "name": "test_spf_15_indoors_redirected",
     "metrics": [_spf_standard]},

    # ── Conflict Checker ───────────────────────────────────────────────────────
    {"id": "conflict-01", "name": "test_conflict_known_pair_format",
     "metrics": [_conflict_format, _safety]},
    {"id": "conflict-02", "name": "test_conflict_unknown_ingredient",
     "metrics": [_unknown_ingredient]},
    {"id": "conflict-03", "name": "test_conflict_safe_pair_identified",
     "metrics": [_conflict_format, _safe_pair]},
    {"id": "conflict-04", "name": "test_conflict_exfoliation_stack",
     "metrics": [_conflict_format, _exfoliation_stack]},

    # ── Routine Sequencer ──────────────────────────────────────────────────────
    {"id": "routine-01", "name": "test_routine_correct_order",
     "metrics": [_routine_order]},
    {"id": "routine-02", "name": "test_routine_unclassifiable_reported",
     "metrics": [_unclassifiable_items]},
    {"id": "routine-03", "name": "test_routine_multi_serum_ordering",
     "metrics": [_routine_order, _multi_serum_order]},
    {"id": "routine-04", "name": "test_routine_reverse_input_resequenced",
     "metrics": [_routine_order]},

    # ── Skin Type Advisor ──────────────────────────────────────────────────────
    {"id": "skin-type-01", "name": "test_skin_type_oily_classification",
     "metrics": [_oily_skin]},
    {"id": "skin-type-02", "name": "test_skin_type_sensitive_classification",
     "metrics": [_sensitive_skin]},
    {"id": "skin-type-03", "name": "test_skin_type_combination_classification",
     "metrics": [_combination_skin]},
    {"id": "skin-type-04", "name": "test_skin_type_acneic_classification",
     "metrics": [_acneic_skin]},

    # ── Introduction Scheduler ─────────────────────────────────────────────────
    {"id": "intro-01", "name": "test_intro_phased_schedule",
     "metrics": [_phased_intro]},
    {"id": "intro-02", "name": "test_intro_conflict_warning",
     "metrics": [_conflict_warning_in_schedule, _phased_intro]},
    {"id": "intro-03", "name": "test_intro_single_active_no_warnings",
     "metrics": [_phased_intro, _single_active_schedule]},
    {"id": "intro-04", "name": "test_intro_three_actives_phased",
     "metrics": [_phased_intro, _three_active_schedule]},

    # ── KB Search — answer quality ─────────────────────────────────────────────
    {"id": "kb-01", "name": "test_kb_search_relevance_and_faithfulness",
     "metrics": [_answer_relevancy, _faithfulness]},
    {"id": "kb-02", "name": "test_kb_search_domain_scope",
     "metrics": [_domain_relevance, _faithfulness]},
    {"id": "kb-03", "name": "test_kb_retinol_beginner_guidance",
     "metrics": [_answer_relevancy, _faithfulness, _retinol_beginner]},
    {"id": "kb-04", "name": "test_kb_sunscreen_types_explained",
     "metrics": [_answer_relevancy, _domain_relevance, _sunscreen_types]},

    # ── KB Search — RAG pipeline quality (contextual metrics) ──────────────────
    {"id": "kb-01", "name": "test_kb_rag_retrieval_quality_niacinamide",
     "metrics": [_contextual_relevancy, _contextual_precision, _contextual_recall]},
    {"id": "kb-02", "name": "test_kb_rag_retrieval_quality_spf",
     "metrics": [_contextual_relevancy, _contextual_precision, _contextual_recall]},
    {"id": "kb-03", "name": "test_kb_rag_retrieval_quality_retinol",
     "metrics": [_contextual_relevancy, _contextual_recall]},
    {"id": "kb-04", "name": "test_kb_rag_retrieval_quality_sunscreen_types",
     "metrics": [_contextual_relevancy, _contextual_precision, _contextual_recall]},
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
        print(
            f"[eval] {cfg['name']} ({cfg['id']}) → {'PASS' if all_passed else 'FAIL'}",
            file=sys.stderr,
            flush=True,
        )

    print(json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
