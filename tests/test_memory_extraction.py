"""Unit tests for backend.agent.memory_extraction (capstone-round Bundle 3).

Task 34: `filter_denylisted_facts` / `is_near_duplicate` — pure functions, no
I/O, no live LLM/DB calls (Req 18.1).

Task 35: `extract_and_store_facts()` orchestration — covered here via mocked
`structured_completion`, embeddings, and `MemoryStore` (per the design's
stated preference for testing business logic over a blanket coverage omit;
the function itself carries a targeted `# pragma: no cover` since it's an
LLM/DB-calling wrapper, matching `structured_completion()`'s own precedent).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.memory_extraction import (
    extract_and_store_facts,
    filter_denylisted_facts,
    is_near_duplicate,
)
from backend.schemas import MemoryExtractionResult


class TestFilterDenylistedFacts:
    def test_keeps_genuinely_freeform_facts(self):
        facts = [
            "Uses well water at home",
            "Travels frequently for work, dry airplane cabins irritate skin",
        ]
        assert filter_denylisted_facts(facts) == facts

    def test_drops_facts_that_mostly_restate_skin_type(self):
        facts = ["Skin type is oily and dry in combination"]
        assert filter_denylisted_facts(facts) == []

    def test_drops_facts_that_mostly_restate_medical_flags(self):
        facts = ["Diagnosed with eczema, a medical condition"]
        assert filter_denylisted_facts(facts) == []

    def test_drops_facts_that_mostly_restate_location(self):
        facts = ["Location country region lives based"]
        assert filter_denylisted_facts(facts) == []

    def test_mixed_list_keeps_only_non_overlapping(self):
        facts = [
            "Prefers fragrance-free products",
            "Skin type oily dry combination",
        ]
        assert filter_denylisted_facts(facts) == ["Prefers fragrance-free products"]

    def test_empty_list_returns_empty(self):
        assert filter_denylisted_facts([]) == []

    def test_empty_string_fact_dropped(self):
        assert filter_denylisted_facts([""]) == []

    def test_partial_overlap_below_threshold_is_kept(self):
        # "acne" is denylisted but only 1 of 6 words — well under the 0.5 threshold.
        facts = ["Mentioned a history of acne during a stressful exam period recently"]
        assert filter_denylisted_facts(facts) == facts


class TestIsNearDuplicate:
    def test_identical_embedding_is_duplicate(self):
        # cosine_distance == 0.0 means similarity == 1.0
        assert is_near_duplicate(cosine_distance=0.0, similarity_threshold=0.92) is True

    def test_distant_embedding_is_not_duplicate(self):
        assert is_near_duplicate(cosine_distance=0.5, similarity_threshold=0.92) is False

    def test_exactly_at_threshold_is_duplicate(self):
        # similarity = 1 - 0.08 = 0.92, exactly at threshold — boundary is inclusive.
        assert is_near_duplicate(cosine_distance=0.08, similarity_threshold=0.92) is True

    def test_just_below_threshold_is_not_duplicate(self):
        # similarity = 1 - 0.081 = 0.919, just under threshold.
        assert is_near_duplicate(cosine_distance=0.081, similarity_threshold=0.92) is False

    @pytest.mark.parametrize("threshold", [0.5, 0.75, 0.99])
    def test_respects_configured_threshold(self, threshold):
        assert is_near_duplicate(cosine_distance=0.01, similarity_threshold=threshold) is True
        assert is_near_duplicate(cosine_distance=0.99, similarity_threshold=threshold) is False


# --- extract_and_store_facts() -----------------------------------------------


def _mock_structured_completion(facts: list[str]):
    return AsyncMock(return_value=(MemoryExtractionResult(facts=facts), False))


@pytest.fixture
def mock_embeddings():
    with patch("backend.agent.memory_extraction._embeddings") as m:
        m.embed_documents = MagicMock(side_effect=lambda texts: [[0.1] * 4096 for _ in texts])
        yield m


@pytest.fixture
def mock_store():
    with patch("backend.agent.memory_extraction.get_memory_store") as get_store:
        store = MagicMock()
        get_store.return_value = store
        yield store


class TestExtractAndStoreFactsNoFacts:
    @pytest.mark.asyncio
    async def test_no_facts_extracted_stores_nothing(self, mock_embeddings, mock_store):
        with patch(
            "backend.agent.memory_extraction.structured_completion",
            _mock_structured_completion([]),
        ):
            await extract_and_store_facts("user-1", "sess-1", "hello", "hi there")

        mock_store.add_fact.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_facts_denylisted_stores_nothing(self, mock_embeddings, mock_store):
        with patch(
            "backend.agent.memory_extraction.structured_completion",
            _mock_structured_completion(["Skin type is oily and dry"]),
        ):
            await extract_and_store_facts("user-1", "sess-1", "hello", "hi there")

        mock_store.add_fact.assert_not_called()


class TestExtractAndStoreFactsStoresNovelFact:
    @pytest.mark.asyncio
    async def test_fact_stored_after_passing_denylist_and_dedup(self, mock_embeddings, mock_store):
        mock_store.find_nearest.return_value = None  # no existing facts yet

        with patch(
            "backend.agent.memory_extraction.structured_completion",
            _mock_structured_completion(["Uses well water at home"]),
        ):
            await extract_and_store_facts("user-1", "sess-1", "hello", "hi there")

        mock_store.add_fact.assert_called_once_with(
            "user-1", "sess-1", "Uses well water at home", [0.1] * 4096
        )


class TestExtractAndStoreFactsSkipsNearDuplicate:
    @pytest.mark.asyncio
    async def test_near_duplicate_fact_is_not_stored(self, mock_embeddings, mock_store, monkeypatch):
        from backend.config import settings as live_settings
        monkeypatch.setattr(live_settings, "memory_similarity_threshold", 0.92)
        existing_fact = MagicMock()
        mock_store.find_nearest.return_value = (existing_fact, 0.01)  # similarity 0.99 >= 0.92

        with patch(
            "backend.agent.memory_extraction.structured_completion",
            _mock_structured_completion(["Uses well water at home"]),
        ):
            await extract_and_store_facts("user-1", "sess-1", "hello", "hi there")

        mock_store.add_fact.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_duplicate_fact_is_stored(self, mock_embeddings, mock_store, monkeypatch):
        from backend.config import settings as live_settings
        monkeypatch.setattr(live_settings, "memory_similarity_threshold", 0.92)
        existing_fact = MagicMock()
        mock_store.find_nearest.return_value = (existing_fact, 0.5)  # similarity 0.5 < 0.92

        with patch(
            "backend.agent.memory_extraction.structured_completion",
            _mock_structured_completion(["Uses well water at home"]),
        ):
            await extract_and_store_facts("user-1", "sess-1", "hello", "hi there")

        mock_store.add_fact.assert_called_once()


class TestExtractAndStoreFactsSwallowsExceptions:
    @pytest.mark.asyncio
    async def test_structured_completion_failure_is_swallowed(self, mock_embeddings, mock_store):
        with patch(
            "backend.agent.memory_extraction.structured_completion",
            AsyncMock(side_effect=RuntimeError("LLM unavailable")),
        ):
            await extract_and_store_facts("user-1", "sess-1", "hello", "hi there")  # must not raise

        mock_store.add_fact.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_failure_is_swallowed(self, mock_embeddings, mock_store):
        mock_store.find_nearest.return_value = None
        mock_store.add_fact.side_effect = RuntimeError("DB unavailable")

        with patch(
            "backend.agent.memory_extraction.structured_completion",
            _mock_structured_completion(["Uses well water at home"]),
        ):
            await extract_and_store_facts("user-1", "sess-1", "hello", "hi there")  # must not raise

    @pytest.mark.asyncio
    async def test_embeddings_failure_is_swallowed(self, mock_store):
        with patch("backend.agent.memory_extraction._embeddings") as m:
            m.embed_documents = MagicMock(side_effect=RuntimeError("embeddings unavailable"))
            with patch(
                "backend.agent.memory_extraction.structured_completion",
                _mock_structured_completion(["Uses well water at home"]),
            ):
                await extract_and_store_facts("user-1", "sess-1", "hello", "hi there")  # must not raise

        mock_store.add_fact.assert_not_called()


class TestExtractAndStoreFactsModelSelection:
    @pytest.mark.asyncio
    async def test_uses_explicit_override_when_configured(self, mock_embeddings, mock_store, monkeypatch):
        from backend.config import settings as live_settings
        monkeypatch.setattr(live_settings, "memory_extraction_model", "openai/gpt-4o-mini")
        monkeypatch.setattr(live_settings, "llm_model", "anthropic/claude-haiku-4.5")
        mock_store.find_nearest.return_value = None
        mock_completion = _mock_structured_completion([])

        with patch("backend.agent.memory_extraction.structured_completion", mock_completion):
            await extract_and_store_facts("user-1", "sess-1", "hello", "hi there")

        assert mock_completion.call_args.kwargs["model"] == "openai/gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_falls_back_to_llm_model_when_unset(self, mock_embeddings, mock_store, monkeypatch):
        from backend.config import settings as live_settings
        monkeypatch.setattr(live_settings, "memory_extraction_model", None)
        monkeypatch.setattr(live_settings, "llm_model", "anthropic/claude-haiku-4.5")
        mock_store.find_nearest.return_value = None
        mock_completion = _mock_structured_completion([])

        with patch("backend.agent.memory_extraction.structured_completion", mock_completion):
            await extract_and_store_facts("user-1", "sess-1", "hello", "hi there")

        assert mock_completion.call_args.kwargs["model"] == "anthropic/claude-haiku-4.5"
