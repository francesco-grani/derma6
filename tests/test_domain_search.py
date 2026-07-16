"""Tests for backend.tools.domain_search (product-source-agent, Task 3).

Mocks TavilySearchResults/DuckDuckGoSearchAPIWrapper at the boundary they're
imported from, following tests/test_api_products.py's TestLookupRetail
pattern for the equivalent v1 search primitive.
"""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from backend.config import settings
from backend.tools.domain_search import search_domain, search_domain_sync


def _tavily_tool(results: list[dict]) -> MagicMock:
    """A `TavilySearchResults(...)` stand-in whose `.invoke()` returns
    `results` (the shape `TavilySearchAPIWrapper.clean_results` produces:
    `title`/`url`/`content`)."""
    tool = MagicMock()
    tool.invoke.return_value = results
    return tool


class TestSearchDomainSync:
    def test_tavily_path_scopes_to_exactly_one_domain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "tavily_api_key", "test-key")
        tool = _tavily_tool(
            [{"title": "dm result", "url": "https://www.dm.de/item", "content": "text"}]
        )

        with patch(
            "langchain_community.tools.tavily_search.TavilySearchResults",
            return_value=tool,
        ) as mock_cls:
            results = search_domain_sync("skincare serum", "dm.de", 5)

        _, kwargs = mock_cls.call_args
        assert kwargs["include_domains"] == ["dm.de"]
        assert len(results) == 1
        assert results[0] == {
            "title": "dm result",
            "url": "https://www.dm.de/item",
            "snippet": "text",
        }
        tool.invoke.assert_called_once_with("skincare serum")

    def test_tavily_path_raises_on_non_list_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # LangChain's TavilySearchResults swallows API/HTTP errors (e.g. a `432`
        # quota response) into a plain string. That must surface as a failure
        # (so search_domain reports ok=False and it never gets cached), not be
        # silently discarded as an empty-but-successful result.
        monkeypatch.setattr(settings, "tavily_api_key", "test-key")
        tool = MagicMock()
        tool.invoke.return_value = "HTTPError('432 Client Error:  for url: ...')"

        with patch(
            "langchain_community.tools.tavily_search.TavilySearchResults",
            return_value=tool,
        ):
            with pytest.raises(RuntimeError, match="non-list result"):
                search_domain_sync("skincare serum", "dm.de", 5)

    def test_duckduckgo_fallback_appends_single_site_qualifier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "tavily_api_key", None)
        ddg = MagicMock()
        ddg.results.return_value = [
            {
                "title": "dm result",
                "link": "https://www.dm.de/item",
                "snippet": "text",
            }
        ]

        with (
            patch("langchain_community.tools.tavily_search.TavilySearchResults") as mock_tavily,
            patch(
                "langchain_community.utilities.DuckDuckGoSearchAPIWrapper",
                return_value=ddg,
            ) as mock_ddg_cls,
        ):
            results = search_domain_sync("skincare serum", "dm.de", 5)

        mock_tavily.assert_not_called()
        mock_ddg_cls.assert_called_once()
        (query_arg, max_results_arg), kwargs = ddg.results.call_args
        assert query_arg == "skincare serum site:dm.de"
        assert query_arg.count("site:") == 1
        assert max_results_arg == 5
        assert len(results) == 1
        assert results[0] == {
            "title": "dm result",
            "url": "https://www.dm.de/item",
            "snippet": "text",
        }

    def test_duckduckgo_path_ignores_non_dict_items(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "tavily_api_key", None)
        ddg = MagicMock()
        ddg.results.return_value = ["not a dict"]

        with patch(
            "langchain_community.utilities.DuckDuckGoSearchAPIWrapper",
            return_value=ddg,
        ):
            results = search_domain_sync("skincare serum", "dm.de", 5)

        assert results == []


class TestSearchDomain:
    async def test_success_returns_results_and_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "backend.tools.domain_search.search_domain_sync",
            MagicMock(return_value=[{"title": "t", "url": "u", "snippet": "s"}]),
        )

        results, ok = await search_domain("skincare serum", "dm.de", 5, timeout_seconds=1.0)

        assert ok is True
        assert results == [{"title": "t", "url": "u", "snippet": "s"}]

    async def test_raised_exception_returns_empty_and_false(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(
            "backend.tools.domain_search.search_domain_sync",
            MagicMock(side_effect=RuntimeError("boom")),
        )

        with caplog.at_level("ERROR"):
            results, ok = await search_domain("skincare serum", "dm.de", 5, timeout_seconds=1.0)

        assert results == []
        assert ok is False
        assert "dm.de" in caplog.text

    async def test_timeout_returns_empty_and_false(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def _slow_search(*args: object, **kwargs: object) -> list:
            time.sleep(0.5)
            return []

        monkeypatch.setattr(
            "backend.tools.domain_search.search_domain_sync",
            MagicMock(side_effect=_slow_search),
        )

        with caplog.at_level("ERROR"):
            results, ok = await search_domain(
                "skincare serum", "dm.de", 5, timeout_seconds=0.05
            )

        assert results == []
        assert ok is False
        assert "dm.de" in caplog.text
