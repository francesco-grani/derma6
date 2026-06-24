"""DeepEval LLM quality evaluation suite for Derma6 skincare assistant tools.

All test cases are loaded from eval/golden_dataset.json — no inputs or
outputs are hardcoded here. Add new cases to the JSON to extend coverage.

Run with:
    pytest --run-eval eval/test_deepeval_evaluations.py -v

The judge model uses OpenRouter (same API key as the app).

Live capture (recommended before a full eval run):
    python eval/capture_outputs.py --update-golden
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

# ── Judge model configuration ─────────────────────────────────────────────────
os.environ.setdefault("OPENAI_API_KEY", os.environ.get("OPENROUTER_API_KEY", ""))
os.environ.setdefault("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")

from deepeval import assert_test  # noqa: E402
from deepeval.metrics import (  # noqa: E402
    AnswerRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    ContextualRelevancyMetric,
    FaithfulnessMetric,
    GEval,
)
from deepeval.test_case import LLMTestCase  # noqa: E402

try:
    from deepeval.test_case import SingleTurnParams as _EvalParams
except ImportError:
    from deepeval.test_case import LLMTestCaseParams as _EvalParams  # type: ignore[no-redef]

pytestmark = pytest.mark.eval

_JUDGE_MODEL = "gpt-4o-mini"

# ── Load golden dataset ───────────────────────────────────────────────────────

_DATASET_PATH = Path(__file__).parent / "golden_dataset.json"

with _DATASET_PATH.open() as _f:
    _GOLDEN: list[dict[str, Any]] = json.load(_f)

_BY_ID: dict[str, dict] = {case["id"]: case for case in _GOLDEN}


def _case(case_id: str) -> LLMTestCase:
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


def _routine_order() -> _RoutineOrderMetric:
    return _RoutineOrderMetric()


class _MultiSerumOrderMetric:
    """Programmatic check: multiple serums must appear in the same relative order
    they were listed in the input.

    Uses string-position comparison for the same reason as _RoutineOrderMetric:
    gpt-4o-mini consistently hallucinated wrong facts about serum ordering.
    """

    name = "Multi-Serum Ordering"
    threshold = 0.8
    score: float = 0.0
    reason: str | None = None

    def measure(self, test_case: Any) -> float:
        import re
        out = test_case.actual_output.lower()
        inp = test_case.input.lower()

        input_items = [i.strip() for i in inp.split(",") if i.strip()]
        serum_entries = re.findall(r"serum:\s*(\S+)", out)

        if len(serum_entries) <= 1:
            self.score = 1.0
            self.reason = "Single or no serums — relative order trivially correct"
            return self.score

        input_serums_in_order = [i for i in input_items if i in serum_entries]

        if serum_entries == input_serums_in_order:
            self.score = 1.0
            self.reason = f"Input order preserved: {' → '.join(serum_entries)}"
        else:
            self.score = 0.0
            self.reason = (
                f"Serum order mismatch — output: {serum_entries}, "
                f"expected by input: {input_serums_in_order}"
            )
        return self.score

    def is_successful(self) -> bool:
        return self.score >= self.threshold


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


# ── SPF Recommender ───────────────────────────────────────────────────────────


def test_spf_enforces_50_plus():
    assert_test(_case("spf-01"), [_spf_standard(), _answer_relevancy()])


def test_spf_redirects_low_spf():
    assert_test(_case("spf-02"), [_spf_standard()])


def test_spf_seasonal_still_50_plus():
    """Winter query must still recommend SPF 50+ and mention year-round UV."""
    metric = GEval(
        name="Seasonal SPF Consistency",
        criteria=(
            "The response must recommend SPF 50+ regardless of season. "
            "It should clarify that UV radiation is present year-round, including winter."
        ),
        evaluation_params=[_EvalParams.INPUT, _EvalParams.ACTUAL_OUTPUT],
        threshold=0.7,
        model=_JUDGE_MODEL,
    )
    assert_test(_case("spf-03"), [_spf_standard(), metric])


def test_spf_15_indoors_redirected():
    """Indoor worker requesting SPF 15 must be redirected to SPF 50+."""
    assert_test(_case("spf-04"), [_spf_standard()])


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


def test_conflict_safe_pair_identified():
    """Niacinamide + vitamin C must return a 'safe' verdict with explanation."""
    metric = GEval(
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
    assert_test(_case("conflict-03"), [_conflict_format(), metric])


def test_conflict_exfoliation_stack():
    """AHA + BHA must be flagged as use-at-different-times to avoid over-exfoliation."""
    metric = GEval(
        name="Exfoliation Stack Warning",
        criteria=(
            "The verdict must be 'use-at-different-times'. "
            "The reason must mention the risk of over-exfoliation or skin barrier disruption."
        ),
        evaluation_params=[_EvalParams.ACTUAL_OUTPUT],
        threshold=0.8,
        model=_JUDGE_MODEL,
    )
    assert_test(_case("conflict-04"), [_conflict_format(), metric])


# ── Routine Sequencer ─────────────────────────────────────────────────────────


def test_routine_correct_order():
    assert_test(_case("routine-01"), [_routine_order()])


def test_routine_unclassifiable_reported():
    assert_test(_case("routine-02"), [_UnclassifiableItemsMetric()])


def test_routine_multi_serum_ordering():
    """Multiple serums must appear in input order between cleanser and SPF."""
    assert_test(_case("routine-03"), [_routine_order(), _MultiSerumOrderMetric()])


def test_routine_reverse_input_resequenced():
    """Products given in reverse order must still be output in canonical sequence."""
    assert_test(_case("routine-04"), [_routine_order()])


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


def test_skin_type_combination_classification():
    """T-zone oily + dry cheeks must be classified as combination."""
    metric = GEval(
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
    assert_test(_case("skin-type-03"), [metric])


def test_skin_type_acneic_classification():
    """Acne and clogged pore symptoms must be classified as acneic."""
    metric = GEval(
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
    assert_test(_case("skin-type-04"), [metric])


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


def test_intro_single_active_no_warnings():
    """A single active must produce a clean 2-week schedule with no conflict warnings."""
    metric = GEval(
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
    assert_test(_case("intro-03"), [_phased_intro(), metric])


def test_intro_three_actives_phased():
    """Three actives must each get their own 2-week block — 6 weeks total."""
    metric = GEval(
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
    assert_test(_case("intro-04"), [_phased_intro(), metric])


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


def test_kb_rag_retrieval_quality_niacinamide():
    """Retrieved chunks for the niacinamide query must be relevant and faithfully used."""
    assert_test(
        _case("kb-01"),
        [_contextual_relevancy(), _contextual_precision(), _contextual_recall()],
    )


def test_kb_rag_retrieval_quality_spf():
    """Retrieved chunks for the SPF protection query must be relevant and faithfully used."""
    assert_test(
        _case("kb-02"),
        [_contextual_relevancy(), _contextual_precision(), _contextual_recall()],
    )


def test_kb_retinol_beginner_guidance():
    """Retinol beginner query must return safe, structured introduction advice."""
    metric = GEval(
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
    assert_test(_case("kb-03"), [_answer_relevancy(), _faithfulness(), metric])


def test_kb_rag_retrieval_quality_retinol():
    """Retrieved chunks for the retinol beginner query must be relevant to the question."""
    assert_test(
        _case("kb-03"),
        [_contextual_relevancy(), _contextual_recall()],
    )


def test_kb_sunscreen_types_explained():
    """Physical vs chemical sunscreen query must clearly distinguish the two types."""
    metric = GEval(
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
    assert_test(_case("kb-04"), [_answer_relevancy(), _domain_relevance(), metric])


def test_kb_rag_retrieval_quality_sunscreen_types():
    """Retrieved chunks for the sunscreen types query must support the answer."""
    assert_test(
        _case("kb-04"),
        [_contextual_relevancy(), _contextual_precision(), _contextual_recall()],
    )
