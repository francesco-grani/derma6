"""Tests for backend.tools.relevance_filter (product-finder-streaming Task
4): `_classify_relevance` (Req 1.1, 1.2, 2.1-2.3) and `filter_category` (Req
1-4, 7.1, 7.2) — see design.md's "Process 2: Relevance filter + bounded
backfill" flowchart for every terminal path exercised below.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.llm.structured import StructuredOutputError
from backend.schemas import ListingRelevanceLLM, ProductListing
from backend.tools.relevance_filter import _classify_relevance, filter_category


def _listing(index: int, source: str = "example.com") -> ProductListing:
    return ProductListing(
        type="new",
        title=f"Listing {index}",
        source=source,
        listing_url=f"https://{source}/item-{index}",
    )


class TestClassifyRelevance:
    async def test_success_returns_genuine_subset(self, monkeypatch):
        candidates = [_listing(0), _listing(1), _listing(2)]
        mock_completion = AsyncMock(
            return_value=(ListingRelevanceLLM(genuine_indices=[0, 2]), False)
        )

        with patch("backend.tools.relevance_filter.structured_completion", mock_completion):
            result = await _classify_relevance("Balea Toner", None, candidates)

        assert result == [0, 2]
        assert mock_completion.call_args.kwargs["schema_model"] is ListingRelevanceLLM
        from backend.config import settings as live_settings

        assert (
            mock_completion.call_args.kwargs["model"]
            == live_settings.effective_relevance_classification_model
        )

    async def test_structured_output_error_returns_none(self):
        candidates = [_listing(0)]
        mock_completion = AsyncMock(side_effect=StructuredOutputError("boom"))

        with patch("backend.tools.relevance_filter.structured_completion", mock_completion):
            result = await _classify_relevance("Balea Toner", None, candidates)

        assert result is None

    async def test_timeout_returns_none(self, monkeypatch):
        from backend.config import settings as live_settings

        monkeypatch.setattr(live_settings, "relevance_classification_timeout_seconds", 0.01)

        async def _outlives_timeout(*args, **kwargs):
            await asyncio.sleep(1)
            return ListingRelevanceLLM(genuine_indices=[0]), False

        candidates = [_listing(0)]
        with patch(
            "backend.tools.relevance_filter.structured_completion",
            AsyncMock(side_effect=_outlives_timeout),
        ):
            result = await _classify_relevance("Balea Toner", None, candidates)

        assert result is None

    async def test_unexpected_exception_returns_none(self):
        candidates = [_listing(0)]
        mock_completion = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("backend.tools.relevance_filter.structured_completion", mock_completion):
            result = await _classify_relevance("Balea Toner", None, candidates)

        assert result is None

    async def test_out_of_range_and_negative_indices_are_ignored(self):
        candidates = [_listing(0), _listing(1)]
        mock_completion = AsyncMock(
            return_value=(ListingRelevanceLLM(genuine_indices=[-1, 0, 5, 1]), False)
        )

        with patch("backend.tools.relevance_filter.structured_completion", mock_completion):
            result = await _classify_relevance("Balea Toner", None, candidates)

        assert result == [0, 1]

    async def test_duplicate_indices_are_deduplicated(self):
        candidates = [_listing(0), _listing(1)]
        mock_completion = AsyncMock(
            return_value=(ListingRelevanceLLM(genuine_indices=[0, 0, 1, 0]), False)
        )

        with patch("backend.tools.relevance_filter.structured_completion", mock_completion):
            result = await _classify_relevance("Balea Toner", None, candidates)

        assert result == [0, 1]


class TestFilterCategory:
    async def test_empty_diversified_makes_no_call_and_no_stage_event(self):
        on_stage = AsyncMock()  # any callable spy; must never be invoked
        with patch(
            "backend.tools.relevance_filter._classify_relevance", AsyncMock()
        ) as mock_classify:
            result = await filter_category(
                "Balea Toner", None, [], [], max_per_category=8, on_stage=on_stage
            )

        assert result == []
        mock_classify.assert_not_called()
        on_stage.assert_not_called()

    async def test_nothing_rejected_single_call_no_backfill(self):
        diversified = [_listing(0), _listing(1)]
        raw_pool = list(diversified)
        stage_calls: list[tuple[str, str]] = []

        with patch(
            "backend.tools.relevance_filter._classify_relevance",
            AsyncMock(return_value=[0, 1]),
        ) as mock_classify:
            result = await filter_category(
                "Balea Toner",
                None,
                diversified,
                raw_pool,
                max_per_category=8,
                on_stage=lambda stage, message: stage_calls.append((stage, message)),
            )

        assert result == diversified
        mock_classify.assert_awaited_once()
        assert stage_calls == [("relevance_filter", "Checking listing relevance")]

    async def test_some_rejected_backfilled_to_cap_second_call_scoped_to_backfill(self):
        diversified = [_listing(0), _listing(1), _listing(2)]  # 2 will be rejected
        # raw_pool has extra candidates beyond `diversified`, available for backfill.
        extra = [_listing(10), _listing(11)]
        raw_pool = diversified + extra

        pass_results = {0: [0, 1], 1: [0]}  # pass1: accept 0,1 reject 2; pass2: accept extra[0]
        calls: list[list[ProductListing]] = []

        async def fake_classify(name, brand, candidates):
            calls.append(candidates)
            return pass_results[len(calls) - 1]

        with patch(
            "backend.tools.relevance_filter._classify_relevance", side_effect=fake_classify
        ) as mock_classify:
            result = await filter_category(
                "Balea Toner", None, diversified, raw_pool, max_per_category=3
            )

        assert mock_classify.call_count == 2
        # Pass 1 scoped to the full diversified set.
        assert calls[0] == diversified
        # Pass 2 scoped ONLY to the backfilled candidates (max_per_category - len(accepted) = 1).
        assert calls[1] == [extra[0]]
        # accepted (0,1) + accepted backfill (extra[0]) = 3 listings, cap reached.
        assert result == [diversified[0], diversified[1], extra[0]]

    async def test_backfill_partially_rejected_by_pass2_no_third_call(self):
        diversified = [_listing(0), _listing(1), _listing(2)]  # 2 rejected
        extra = [_listing(10), _listing(11)]
        raw_pool = diversified + extra

        calls: list[list[ProductListing]] = []

        async def fake_classify(name, brand, candidates):
            calls.append(candidates)
            if len(calls) == 1:
                return [0, 1]  # pass 1: reject index 2
            return []  # pass 2: reject every backfilled candidate

        with patch(
            "backend.tools.relevance_filter._classify_relevance", side_effect=fake_classify
        ) as mock_classify:
            result = await filter_category(
                "Balea Toner", None, diversified, raw_pool, max_per_category=3
            )

        assert mock_classify.call_count == 2
        # Only the originally-accepted listings survive; no rejected backfill candidate
        # is included, and no third classification call is ever made.
        assert result == [diversified[0], diversified[1]]

    async def test_raw_pool_has_no_spare_candidates_returns_below_cap_one_call(self):
        diversified = [_listing(0), _listing(1), _listing(2)]  # 2 rejected
        raw_pool = list(diversified)  # nothing beyond what's already in diversified

        with patch(
            "backend.tools.relevance_filter._classify_relevance",
            AsyncMock(return_value=[0, 1]),
        ) as mock_classify:
            result = await filter_category(
                "Balea Toner", None, diversified, raw_pool, max_per_category=8
            )

        mock_classify.assert_awaited_once()
        assert result == [diversified[0], diversified[1]]

    async def test_pass1_fails_unfiltered_passthrough_no_backfill(self):
        diversified = [_listing(0), _listing(1)]
        raw_pool = diversified + [_listing(10)]

        with patch(
            "backend.tools.relevance_filter._classify_relevance", AsyncMock(return_value=None)
        ) as mock_classify:
            result = await filter_category(
                "Balea Toner", None, diversified, raw_pool, max_per_category=8
            )

        mock_classify.assert_awaited_once()
        assert result == diversified

    async def test_pass2_fails_backfilled_candidates_included_unfiltered(self):
        diversified = [_listing(0), _listing(1), _listing(2)]  # 2 rejected
        extra = [_listing(10), _listing(11)]
        raw_pool = diversified + extra

        calls: list[list[ProductListing]] = []

        async def fake_classify(name, brand, candidates):
            calls.append(candidates)
            if len(calls) == 1:
                return [0, 1]  # pass 1 succeeds, rejects index 2
            return None  # pass 2 fails

        with patch(
            "backend.tools.relevance_filter._classify_relevance", side_effect=fake_classify
        ) as mock_classify:
            result = await filter_category(
                "Balea Toner", None, diversified, raw_pool, max_per_category=4
            )

        assert mock_classify.call_count == 2
        # max_per_category - len(accepted) = 4 - 2 = 2, so both extras are backfilled
        # and, since pass 2 failed, both are included unfiltered.
        assert result == [diversified[0], diversified[1], extra[0], extra[1]]

    async def test_at_cap_after_pass1_no_backfill(self):
        diversified = [_listing(0), _listing(1), _listing(2)]
        raw_pool = diversified + [_listing(10)]

        with patch(
            "backend.tools.relevance_filter._classify_relevance",
            AsyncMock(return_value=[0, 1]),  # rejects index 2, but cap is 2
        ) as mock_classify:
            result = await filter_category(
                "Balea Toner", None, diversified, raw_pool, max_per_category=2
            )

        mock_classify.assert_awaited_once()
        assert result == [diversified[0], diversified[1]]

    async def test_backfill_never_reintroduces_a_rejected_candidate(self):
        # diversified[2] is rejected by pass 1; it also happens to still be
        # present in raw_pool (e.g. it was one of the domain's raw results).
        # It must not be reintroduced as a backfill candidate.
        diversified = [_listing(0), _listing(1), _listing(2)]
        extra = [_listing(10)]
        raw_pool = diversified + extra  # includes the rejected diversified[2]

        calls: list[list[ProductListing]] = []

        async def fake_classify(name, brand, candidates):
            calls.append(candidates)
            if len(calls) == 1:
                return [0, 1]
            return [0]  # accept the sole backfilled candidate

        with patch("backend.tools.relevance_filter._classify_relevance", side_effect=fake_classify):
            result = await filter_category(
                "Balea Toner", None, diversified, raw_pool, max_per_category=3
            )

        # Pass 2 must be scoped only to `extra`, never diversified[2].
        assert calls[1] == extra
        assert diversified[2] not in result
