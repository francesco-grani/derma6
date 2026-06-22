"""DeepEval LLM quality evaluation suite for Derma6 skincare assistant tools.

All test cases are loaded from eval/golden_dataset.json — no inputs or
outputs are hardcoded here. Add new cases to the JSON to extend coverage.

Run with:
    pytest --run-eval eval/test_deepeval_evaluations.py -v

The judge model uses OpenRouter (same API key as the app).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

# ── Judge model configuration ─────────────────────────────────────────────────
# DeepEval defaults to OpenAI. Redirect to OpenRouter so the same key works.
os.environ.setdefault("OPENAI_API_KEY", os.environ.get("OPENROUTER_API_KEY", ""))
os.environ.setdefault("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")

from deepeval import assert_test  # noqa: E402
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval  # noqa: E402
from deepeval.test_case import LLMTestCase  # noqa: E402

try:
    # deepeval >= 2.x
    from deepeval.test_case import SingleTurnParams as _EvalParams
except ImportError:  # pragma: no cover
    from deepeval.test_case import LLMTestCaseParams as _EvalParams  # type: ignore[no-redef]

pytestmark = pytest.mark.eval

_JUDGE_MODEL = "gpt-4o-mini"

# ── Load golden dataset ───────────────────────────────────────────────────────

_DATASET_PATH = Path(__file__).parent / "golden_dataset.json"

with _DATASET_PATH.open() as _f:
    _GOLDEN: list[dict[str, Any]] = json.load(_f)

_BY_ID: dict[str, dict] = {case["id"]: case for case in _GOLDEN}


def _case(case_id: str) -> LLMTestCase:
    """Build an LLMTestCase from the golden dataset entry with the given id."""
    row = _BY_ID[case_id]
    return LLMTestCase(
        input=row["input"],
        actual_output=row["actual_output"],
        expected_output=row.get("expected_output"),
        retrieval_context=row.get("retrieval_context") or None,
    )


# ── Shared metric factories ───────────────────────────────────────────────────


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
            "Steps must appear in this order: cleanser → toner → serum → moisturiser → SPF. "
            "Steps appearing earlier in the routine must have lower step numbers."
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


# ── SPF Recommender ───────────────────────────────────────────────────────────


def test_spf_enforces_50_plus():
    assert_test(_case("spf-01"), [_spf_standard(), _answer_relevancy()])


def test_spf_redirects_low_spf():
    assert_test(_case("spf-02"), [_spf_standard()])


# ── Conflict Checker ──────────────────────────────────────────────────────────


def test_conflict_known_pair_format():
    assert_test(_case("conflict-01"), [_conflict_format(), _safety()])


def test_conflict_unknown_ingredient():
    metric = GEval(
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
    assert_test(_case("conflict-02"), [metric])


# ── Routine Sequencer ─────────────────────────────────────────────────────────


def test_routine_correct_order():
    assert_test(_case("routine-01"), [_routine_order()])


def test_routine_unclassifiable_reported():
    metric = GEval(
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
    assert_test(_case("routine-02"), [metric])


# ── Skin Type Advisor ─────────────────────────────────────────────────────────


def test_skin_type_oily_classification():
    metric = GEval(
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
    assert_test(_case("skin-type-01"), [metric])


def test_skin_type_sensitive_classification():
    metric = GEval(
        name="Sensitive Skin Classification",
        criteria=(
            "Given reactive symptoms (redness, stinging), classified type must be 'sensitive'. "
            "Characteristics must mention reactivity or irritation."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )
    assert_test(_case("skin-type-02"), [metric])


# ── Introduction Scheduler ────────────────────────────────────────────────────


def test_intro_phased_schedule():
    assert_test(_case("intro-01"), [_phased_intro()])


def test_intro_conflict_warning():
    metric = GEval(
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
    assert_test(_case("intro-02"), [metric, _phased_intro()])


# ── KB Search ─────────────────────────────────────────────────────────────────


def test_kb_search_relevance_and_faithfulness():
    assert_test(_case("kb-01"), [_answer_relevancy(), _faithfulness()])


def test_kb_search_domain_scope():
    metric = GEval(
        name="Skincare Domain Relevance",
        criteria=(
            "The response must stay within the skincare domain (UV protection, skin health, etc.). "
            "It must not include off-topic information."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.9,
        model=_JUDGE_MODEL,
    )
    assert_test(_case("kb-02"), [metric, _faithfulness()])
