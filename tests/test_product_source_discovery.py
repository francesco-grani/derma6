"""Tests for backend.tools.product_source_discovery (product-source-agent,
Task 5 and Task 6): `_normalize_location`, `_is_germany`,
`_validate_domain_candidate`, `_verify_domain_relevance`,
`_discover_sources_llm` (Task 5), and the orchestration entry points
`_discover_sources`/`get_or_discover_sources` (Task 6).
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from backend.db.source_discovery_store import SourceDiscoveryStore
from backend.llm.structured import StructuredOutputError
from backend.schemas import DiscoveredSources, DiscoveredSourcesLLM
from backend.tools.product_source_discovery import (
    DiscoveryUnavailable,
    _discover_sources,
    _discover_sources_llm,
    _GERMANY_LOCATION_ALIASES,
    _GERMANY_SEED_RETAILER_DOMAINS,
    _GERMANY_SEED_VINTED_DOMAIN,
    _is_germany,
    _normalize_location,
    _validate_domain_candidate,
    _verify_domain_relevance,
    get_or_discover_sources,
)


class TestNormalizeLocation:
    @pytest.mark.parametrize("alias", sorted(_GERMANY_LOCATION_ALIASES))
    def test_known_aliases_pass_through_trimmed_lowercased(self, alias):
        assert _normalize_location(f"  {alias.upper()}  ") == alias

    def test_none_normalizes_to_empty_string(self):
        assert _normalize_location(None) == ""

    def test_blank_normalizes_to_empty_string(self):
        assert _normalize_location("") == ""

    def test_whitespace_only_normalizes_to_empty_string(self):
        assert _normalize_location("   ") == ""

    def test_trims_and_lowercases_arbitrary_location(self):
        assert _normalize_location("  Berlin, Germany  ") == "berlin, germany"


class TestIsGermany:
    @pytest.mark.parametrize("alias", sorted(_GERMANY_LOCATION_ALIASES))
    def test_each_known_alias_is_germany(self, alias):
        assert _is_germany(alias) is True

    def test_unrecognized_string_is_not_germany(self):
        assert _is_germany("france") is False

    def test_empty_string_is_not_germany(self):
        assert _is_germany("") is False


class TestValidateDomainCandidate:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("dm.de", "dm.de"),
            ("DM.DE", "dm.de"),
            ("  rossmann.de  ", "rossmann.de"),
            ("vinted.co.uk", "vinted.co.uk"),
            ("shop.example.com", "shop.example.com"),
        ],
    )
    def test_accepts_bare_domains(self, raw, expected):
        assert _validate_domain_candidate(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "https://dm.de/search",
            "http://www.dm.de",
            "google.com/url?q=https://dm.de",
            "dm dot de",
            "not a domain at all",
            "",
        ],
    )
    def test_rejects_urls_redirects_and_free_text(self, raw):
        assert _validate_domain_candidate(raw) is None

    def test_rejects_string_with_embedded_whitespace(self):
        assert _validate_domain_candidate("dm .de") is None

    def test_never_raises_on_non_string_input(self):
        assert _validate_domain_candidate(None) is None  # type: ignore[arg-type]


class TestVerifyDomainRelevance:
    async def test_returns_true_for_at_least_one_result(self, monkeypatch):
        monkeypatch.setattr(
            "backend.tools.product_source_discovery.search_domain",
            AsyncMock(return_value=([{"title": "t", "url": "u", "snippet": "s"}], True)),
        )
        assert await _verify_domain_relevance("dm.de") is True

    async def test_returns_false_for_zero_results(self, monkeypatch):
        monkeypatch.setattr(
            "backend.tools.product_source_discovery.search_domain",
            AsyncMock(return_value=([], True)),
        )
        assert await _verify_domain_relevance("dm.de") is False

    async def test_returns_false_when_search_reports_not_ok(self, monkeypatch):
        monkeypatch.setattr(
            "backend.tools.product_source_discovery.search_domain",
            AsyncMock(return_value=([], False)),
        )
        assert await _verify_domain_relevance("dm.de") is False

    async def test_returns_false_on_raised_exception(self, monkeypatch):
        monkeypatch.setattr(
            "backend.tools.product_source_discovery.search_domain",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        assert await _verify_domain_relevance("dm.de") is False


class TestDiscoverSourcesLlm:
    async def test_calls_structured_completion_with_correct_model_and_schema(self, monkeypatch):
        from backend.config import settings as live_settings

        monkeypatch.setattr(live_settings, "source_discovery_model", "openai/gpt-4o-mini")
        expected = DiscoveredSourcesLLM(
            location_recognized=True,
            retailer_domains=["dm.de"],
            vinted_locale_domain="vinted.de",
            secondhand_marketplace_domains=["kleiderkreisel.de"],
        )
        mock_completion = AsyncMock(return_value=(expected, False))

        with patch(
            "backend.tools.product_source_discovery.structured_completion", mock_completion
        ):
            result = await _discover_sources_llm("Germany")

        assert result == expected
        assert mock_completion.call_args.kwargs["model"] == "openai/gpt-4o-mini"
        assert mock_completion.call_args.kwargs["schema_model"] is DiscoveredSourcesLLM
        assert mock_completion.call_args.kwargs["user_content"] == "Germany"

    async def test_structured_output_error_reraised_as_discovery_unavailable(self, monkeypatch):
        with patch(
            "backend.tools.product_source_discovery.structured_completion",
            AsyncMock(side_effect=StructuredOutputError("could not parse")),
        ):
            with pytest.raises(DiscoveryUnavailable):
                await _discover_sources_llm("Germany")


class TestDiscoverSources:
    """Task 6: `_discover_sources()` — validation, verification, and capping
    of the raw `DiscoveredSourcesLLM` candidates into a `DiscoveredSources`,
    with `_discover_sources_llm` and `_verify_domain_relevance` mocked at
    their module-level boundary."""

    @staticmethod
    def _mock_llm(monkeypatch, result: DiscoveredSourcesLLM) -> AsyncMock:
        mock = AsyncMock(return_value=result)
        monkeypatch.setattr(
            "backend.tools.product_source_discovery._discover_sources_llm", mock
        )
        return mock

    @staticmethod
    def _mock_verify(monkeypatch, side_effect) -> AsyncMock:
        mock = AsyncMock(side_effect=side_effect)
        monkeypatch.setattr(
            "backend.tools.product_source_discovery._verify_domain_relevance", mock
        )
        return mock

    async def test_all_valid_candidates_within_cap(self, monkeypatch):
        self._mock_llm(
            monkeypatch,
            DiscoveredSourcesLLM(
                location_recognized=True,
                retailer_domains=["dm.de", "rossmann.de"],
                vinted_locale_domain="vinted.de",
                secondhand_marketplace_domains=["kleiderkreisel.de"],
            ),
        )
        self._mock_verify(monkeypatch, lambda domain: True)

        result = await _discover_sources("germany")

        assert result.retailer_domains == ("dm.de", "rossmann.de")
        assert result.vinted_domain == "vinted.de"
        assert result.secondhand_domains == ("kleiderkreisel.de",)

    async def test_more_than_cap_valid_candidates_capped_preserving_llm_order(
        self, monkeypatch
    ):
        domains = [f"shop{i}.de" for i in range(12)]
        self._mock_llm(
            monkeypatch,
            DiscoveredSourcesLLM(
                location_recognized=True,
                retailer_domains=domains,
                vinted_locale_domain=None,
                secondhand_marketplace_domains=[],
            ),
        )
        self._mock_verify(monkeypatch, lambda domain: True)

        result = await _discover_sources("germany")

        assert result.retailer_domains == tuple(domains[:10])

    async def test_mixed_syntax_and_verification_failures_leave_only_survivors(
        self, monkeypatch
    ):
        self._mock_llm(
            monkeypatch,
            DiscoveredSourcesLLM(
                location_recognized=True,
                retailer_domains=["dm.de", "not a domain", "rossmann.de", "https://bad.de/x"],
                vinted_locale_domain=None,
                secondhand_marketplace_domains=[],
            ),
        )
        self._mock_verify(monkeypatch, lambda domain: domain == "dm.de")

        result = await _discover_sources("germany")

        assert result.retailer_domains == ("dm.de",)

    async def test_location_not_recognized_raises_discovery_unavailable(self, monkeypatch):
        self._mock_llm(monkeypatch, DiscoveredSourcesLLM(location_recognized=False))

        with pytest.raises(DiscoveryUnavailable):
            await _discover_sources("atlantis")

    async def test_vinted_locale_in_allowlist_is_kept(self, monkeypatch):
        self._mock_llm(
            monkeypatch,
            DiscoveredSourcesLLM(
                location_recognized=True,
                retailer_domains=[],
                vinted_locale_domain="vinted.fr",
                secondhand_marketplace_domains=[],
            ),
        )

        result = await _discover_sources("france")

        assert result.vinted_domain == "vinted.fr"

    async def test_vinted_locale_absent_from_allowlist_is_discarded(self, monkeypatch):
        self._mock_llm(
            monkeypatch,
            DiscoveredSourcesLLM(
                location_recognized=True,
                retailer_domains=[],
                vinted_locale_domain="vinted.xx",
                secondhand_marketplace_domains=[],
            ),
        )

        result = await _discover_sources("nowhere")

        assert result.vinted_domain is None

    async def test_zero_valid_retailer_domains_with_valid_secondhand_domain_does_not_raise(
        self, monkeypatch
    ):
        self._mock_llm(
            monkeypatch,
            DiscoveredSourcesLLM(
                location_recognized=True,
                retailer_domains=["not a domain"],
                vinted_locale_domain=None,
                secondhand_marketplace_domains=["kleiderkreisel.de"],
            ),
        )
        self._mock_verify(monkeypatch, lambda domain: True)

        result = await _discover_sources("germany")

        assert result.retailer_domains == ()
        assert result.secondhand_domains == ("kleiderkreisel.de",)


class TestGetOrDiscoverSources:
    """Task 6: `get_or_discover_sources()` — the cache-or-run entry point
    `find_product()` calls. Uses a real `SourceDiscoveryStore` (per-test
    in-memory SQLite), mocking only `_discover_sources_llm`/
    `_verify_domain_relevance` at their module-level boundary, matching this
    file's existing house style."""

    @pytest.fixture
    def store(self, tmp_path) -> SourceDiscoveryStore:
        # A per-test tmp_path SQLite file, not ":memory:" — sqlite3 opens a
        # fresh, empty in-memory database on every new connection, so a
        # store that reconnects per call (as this one does) can never read
        # back what an earlier connection wrote. Matches
        # tests/test_source_discovery_store.py's existing fixture style.
        return SourceDiscoveryStore(db_path=str(tmp_path / "source_discovery.db"))

    @staticmethod
    def _mock_llm(monkeypatch, side_effect) -> AsyncMock:
        mock = AsyncMock(side_effect=side_effect)
        monkeypatch.setattr(
            "backend.tools.product_source_discovery._discover_sources_llm", mock
        )
        return mock

    async def test_none_location_makes_no_llm_call_and_is_not_cached(self, store, monkeypatch):
        mock_llm = self._mock_llm(monkeypatch, None)

        result = await get_or_discover_sources(None, store)

        assert result == DiscoveredSources()
        mock_llm.assert_not_called()
        assert store.get("") is None

    async def test_blank_location_makes_no_llm_call_and_is_not_cached(self, store, monkeypatch):
        mock_llm = self._mock_llm(monkeypatch, None)

        result = await get_or_discover_sources("   ", store)

        assert result == DiscoveredSources()
        mock_llm.assert_not_called()
        assert store.get("") is None

    async def test_cache_hit_makes_no_llm_call_and_returns_cached_result(
        self, store, monkeypatch
    ):
        cached = DiscoveredSources(
            retailer_domains=("dm.de",), vinted_domain="vinted.de", secondhand_domains=()
        )
        store.set("germany", "Germany", cached)
        mock_llm = self._mock_llm(monkeypatch, None)

        result = await get_or_discover_sources("Germany", store)

        assert result == cached
        mock_llm.assert_not_called()

    async def test_cache_miss_success_calls_llm_once_and_caches_result(
        self, store, monkeypatch
    ):
        llm_result = DiscoveredSourcesLLM(
            location_recognized=True,
            retailer_domains=["dm.de"],
            vinted_locale_domain="vinted.de",
            secondhand_marketplace_domains=[],
        )
        mock_llm = self._mock_llm(monkeypatch, lambda location: llm_result)
        monkeypatch.setattr(
            "backend.tools.product_source_discovery._verify_domain_relevance",
            AsyncMock(return_value=True),
        )

        result = await get_or_discover_sources("Germany", store)

        assert result.retailer_domains == ("dm.de",)
        assert result.vinted_domain == "vinted.de"
        mock_llm.assert_awaited_once()
        assert store.get("germany") == result

    async def test_cache_miss_non_germany_failure_returns_empty_not_cached_and_retries(
        self, store, monkeypatch
    ):
        mock_llm = self._mock_llm(monkeypatch, DiscoveryUnavailable("boom"))

        result = await get_or_discover_sources("France", store)

        assert result == DiscoveredSources()
        assert store.get("france") is None

        # A second call for the same (still-uncached) location retries
        # discovery rather than reusing anything (Req 7.2).
        await get_or_discover_sources("France", store)
        assert mock_llm.await_count == 2

    async def test_cache_miss_germany_failure_returns_seed_not_cached_and_retries_live(
        self, store, monkeypatch
    ):
        mock_llm = self._mock_llm(monkeypatch, DiscoveryUnavailable("boom"))

        result = await get_or_discover_sources("Germany", store)

        assert result.retailer_domains == _GERMANY_SEED_RETAILER_DOMAINS
        assert result.vinted_domain == _GERMANY_SEED_VINTED_DOMAIN
        assert result.secondhand_domains == ()
        assert store.get("germany") is None

        # A subsequent call retries live discovery rather than being locked
        # into the seed fallback (Req 8.4's "not cached" rationale).
        await get_or_discover_sources("Germany", store)
        assert mock_llm.await_count == 2

    async def test_cache_hit_never_invokes_on_stage(self, store, monkeypatch):
        cached = DiscoveredSources(
            retailer_domains=("dm.de",), vinted_domain="vinted.de", secondhand_domains=()
        )
        store.set("germany", "Germany", cached)
        self._mock_llm(monkeypatch, None)
        on_stage = Mock()

        result = await get_or_discover_sources("Germany", store, on_stage=on_stage)

        assert result == cached
        on_stage.assert_not_called()

    async def test_cache_miss_invokes_on_stage_once_before_discovery(self, store, monkeypatch):
        llm_result = DiscoveredSourcesLLM(
            location_recognized=True,
            retailer_domains=["dm.de"],
            vinted_locale_domain="vinted.de",
            secondhand_marketplace_domains=[],
        )

        on_stage = Mock()
        call_order: list[str] = []

        async def _llm(location: str) -> DiscoveredSourcesLLM:
            call_order.append("discover")
            return llm_result

        def _on_stage(stage: str, message: str) -> None:
            call_order.append("on_stage")
            on_stage(stage, message)

        self._mock_llm(monkeypatch, _llm)
        monkeypatch.setattr(
            "backend.tools.product_source_discovery._verify_domain_relevance",
            AsyncMock(return_value=True),
        )

        result = await get_or_discover_sources("Germany", store, on_stage=_on_stage)

        assert result.retailer_domains == ("dm.de",)
        on_stage.assert_called_once_with("discovery", "Assessing retailers for Germany")
        assert call_order == ["on_stage", "discover"]

    async def test_cache_miss_timeout_handled_identically_to_failure_non_germany(
        self, store, monkeypatch
    ):
        from backend.config import settings as live_settings

        monkeypatch.setattr(live_settings, "source_discovery_timeout_seconds", 0.05)

        async def _slow_llm(location: str) -> DiscoveredSourcesLLM:
            import asyncio as _asyncio

            await _asyncio.sleep(0.5)
            return DiscoveredSourcesLLM(location_recognized=True)

        monkeypatch.setattr(
            "backend.tools.product_source_discovery._discover_sources_llm",
            AsyncMock(side_effect=_slow_llm),
        )

        result = await get_or_discover_sources("France", store)

        assert result == DiscoveredSources()
        assert store.get("france") is None

    async def test_cache_miss_timeout_handled_identically_to_failure_germany(
        self, store, monkeypatch
    ):
        from backend.config import settings as live_settings

        monkeypatch.setattr(live_settings, "source_discovery_timeout_seconds", 0.05)

        async def _slow_llm(location: str) -> DiscoveredSourcesLLM:
            import asyncio as _asyncio

            await _asyncio.sleep(0.5)
            return DiscoveredSourcesLLM(location_recognized=True)

        monkeypatch.setattr(
            "backend.tools.product_source_discovery._discover_sources_llm",
            AsyncMock(side_effect=_slow_llm),
        )

        result = await get_or_discover_sources("Germany", store)

        assert result.retailer_domains == _GERMANY_SEED_RETAILER_DOMAINS
        assert result.vinted_domain == _GERMANY_SEED_VINTED_DOMAIN
        assert store.get("germany") is None
