"""Regression tests for the vinted-api-wrapper schema-drift shim.

Guards the production incident where Vinted's live `/catalog/items` API stopped
returning the `icon_badges` key on item objects. The pinned wrapper (0.3.9)
declares `Item.icon_badges` as required, so `dacite.from_dict` raised on every
*non-empty* search response; the wrapper swallowed it into a `{"error": ...}`
dict, and `_search_vinted_sync` then read `.items` (the `dict.items` method) and
crashed with `'builtin_function_or_method' object is not subscriptable`. Net
effect: zero Vinted listings whenever there were actually results.

`backend.tools._vinted_patch.apply()` relaxes the wrapper's response dataclasses
so a missing key degrades to `None` instead of raising. These tests assert both
the low-level parse (via `dacite.from_dict`) and the `_search_vinted_sync`
hardening survive a payload with `icon_badges` absent.
"""

from unittest.mock import MagicMock, patch

import pytest
from dacite import from_dict

from backend.tools import _vinted_patch
from backend.tools.product_finder import _search_vinted_sync

# The shim is applied on import of product_finder, but call it explicitly so
# this module passes even if run in isolation. apply() is idempotent.
_vinted_patch.apply()


def _item_payload(item_id: int, *, icon_badges: bool) -> dict:
    """A minimal-but-realistic Vinted catalog item. When `icon_badges=False`
    the key is omitted entirely — the exact drift observed in production."""
    item = {
        "id": item_id,
        "title": "Paula's Choice 2% BHA Liquid Exfoliant",
        "price": {"amount": "20.0", "currency_code": "EUR"},
        "is_visible": True,
        "discount": None,
        "brand_title": "Paula's Choice",
        "user": {
            "id": 1,
            "login": "seller",
            "profile_url": "https://www.vinted.de/member/1",
            "photo": None,
            "business": False,
        },
        "url": f"https://www.vinted.de/items/{item_id}",
        "promoted": False,
        "photo": {
            "id": 9,
            "image_no": 1,
            "width": 800,
            "height": 800,
            "dominant_color": None,
            "dominant_color_opaque": None,
            "url": f"https://images.vinted.net/{item_id}.jpg",
            "is_main": True,
            "thumbnails": [],
            "high_resolution": {"id": "x", "timestamp": 0, "orientation": None},
            "is_suspicious": False,
            "full_size_url": None,
            "is_hidden": False,
            "extra": None,
        },
        "favourite_count": 0,
        "is_favourite": False,
        "badge": None,
        "conversion": None,
        "service_fee": None,
        "total_item_price": None,
        "view_count": 0,
        "size_title": None,
        "content_source": None,
        "status": "New with tags",
        # icon_badges intentionally added/omitted per the flag
        "item_box": None,
        "search_tracking_params": None,
    }
    if icon_badges:
        item["icon_badges"] = []
    return item


def _search_response_payload(items: list[dict]) -> dict:
    # `search_tracking_params` (a required, non-Optional field on SearchResponse)
    # is omitted, not null: the shim fills a missing key with None without
    # type-checking it. This mirrors the real drift — a *dropped* key — which is
    # exactly what the shim exists to absorb.
    return {
        "code": 0,
        "pagination": None,
        "dominant_brand": None,
        "items": items,
    }


class TestVintedPatchParsing:
    def test_from_dict_parses_item_missing_icon_badges(self) -> None:
        # The core regression: the exact drift that crashed the pinned wrapper.
        from vinted.models.search import SearchResponse

        payload = _search_response_payload([_item_payload(1, icon_badges=False)])
        response = from_dict(SearchResponse, payload)

        assert len(response.items) == 1
        item = response.items[0]
        assert item.title == "Paula's Choice 2% BHA Liquid Exfoliant"
        assert item.price.amount == "20.0"
        # The missing field is filled with None rather than raising.
        assert item.icon_badges is None

    def test_from_dict_still_parses_item_with_icon_badges(self) -> None:
        # Present keys are unaffected by the relaxation.
        from vinted.models.search import SearchResponse

        payload = _search_response_payload([_item_payload(2, icon_badges=True)])
        response = from_dict(SearchResponse, payload)

        assert response.items[0].icon_badges == []

    def test_apply_is_idempotent(self) -> None:
        _vinted_patch.apply()
        _vinted_patch.apply()
        from vinted.models.search import SearchResponse

        payload = _search_response_payload([_item_payload(3, icon_badges=False)])
        assert len(from_dict(SearchResponse, payload).items) == 1


class TestSearchVintedSyncHardening:
    def test_returns_items_list_on_success(self) -> None:
        client = MagicMock()
        response = MagicMock()
        response.items = ["a", "b"]
        client.search.return_value = response

        with patch("backend.tools.product_finder.Vinted", return_value=client):
            assert _search_vinted_sync("query", "de") == ["a", "b"]

    def test_raises_on_error_dict_fallback(self) -> None:
        # The wrapper's parse-failure fallback: a bare dict whose `.items` is the
        # dict method, not a list. This must raise a clear error rather than the
        # opaque 'builtin_function_or_method' object is not subscriptable.
        client = MagicMock()
        client.search.return_value = {"error": "HTTP 200"}

        with patch("backend.tools.product_finder.Vinted", return_value=client):
            with pytest.raises(RuntimeError, match="unparseable response"):
                _search_vinted_sync("query", "de")
