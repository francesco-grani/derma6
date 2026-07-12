"""Tests for backend.api.export (capstone-round Bundle 8, Task 74, Req 26.3).

Route-level tests exercised through FastAPI's `TestClient` against a minimal
app that mounts only `backend.api.export.router` (mirroring
`tests/test_api_profile.py`'s and `tests/test_api_admin.py`'s approach).
`get_current_user` is overridden to return a fixed `user_id` string directly,
and `get_profile_store`/`get_session_store` are overridden to point at the
`profile_store`/`session_store` fixtures (both backed by the same per-test
temporary SQLite file, per `tests/conftest.py`), so these exercise the real
`export()` route and the real username lookup rather than mocks.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.export import _content_disposition, router as export_router
from backend.auth import get_current_user
from backend.db.deps import get_profile_store, get_session_store

# A username with characters well outside the Latin-1 range: CJK plus an
# emoji, so a naive `filename="{username}..."` interpolation would raise
# UnicodeEncodeError when Starlette encodes the header as latin-1.
_NON_LATIN1_USERNAME = "田中さくら🌸"


def _make_client(profile_store, session_store, user_id: str = "uid-alice") -> TestClient:
    app = FastAPI()
    app.include_router(export_router)
    app.dependency_overrides[get_profile_store] = lambda: profile_store
    app.dependency_overrides[get_session_store] = lambda: session_store
    app.dependency_overrides[get_current_user] = lambda: user_id
    return TestClient(app)


class TestExportContentDispositionEncoding:
    """Req 26.3: a non-Latin-1 username must not raise UnicodeEncodeError, and
    the resulting header must be well-formed."""

    def test_html_export_with_non_latin1_username_succeeds(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id(
            "uid-alice", "alice@example.com", _NON_LATIN1_USERNAME
        )
        client = _make_client(profile_store, session_store, user_id="uid-alice")

        response = client.get("/api/me/export", params={"format": "html"})

        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert "filename=" in disposition
        assert "filename*=UTF-8''" in disposition

    def test_pdf_export_with_non_latin1_username_succeeds(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id(
            "uid-bob", "bob@example.com", _NON_LATIN1_USERNAME
        )
        client = _make_client(profile_store, session_store, user_id="uid-bob")

        response = client.get("/api/me/export", params={"format": "pdf"})

        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert "filename=" in disposition
        assert "filename*=UTF-8''" in disposition

    def test_ascii_username_still_produces_readable_filename(self, profile_store, session_store):
        profile_store.get_or_create_user_by_id("uid-carol", "carol@example.com", "carol")
        client = _make_client(profile_store, session_store, user_id="uid-carol")

        response = client.get("/api/me/export", params={"format": "html"})

        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        assert 'filename="carol_skincare_plan.html"' in disposition


class TestContentDispositionHelper:
    """Unit-level coverage of `_content_disposition()` itself, independent of
    the route, for the sanitisation/fallback edge cases."""

    def test_ascii_username_round_trips_in_filename(self):
        header = _content_disposition("carol", "html")
        assert header == "attachment; filename=\"carol_skincare_plan.html\"; filename*=UTF-8''carol_skincare_plan.html"

    def test_accented_username_is_transliterated_in_ascii_fallback(self):
        header = _content_disposition("café", "html")
        assert 'filename="cafe_skincare_plan.html"' in header
        assert "filename*=UTF-8''caf%C3%A9_skincare_plan.html" in header

    def test_purely_non_ascii_username_drops_to_readable_ascii_suffix(self):
        # The username itself contributes nothing ASCII-safe, but the
        # "_skincare_plan.pdf" suffix still does, so the fallback stays a
        # readable filename rather than an empty/mangled one — the full
        # username is still recoverable via filename*.
        header = _content_disposition("田中さくら", "pdf")
        assert 'filename="_skincare_plan.pdf"' in header
        assert "filename*=UTF-8''" in header

    def test_fallback_filename_is_always_latin1_encodable(self):
        # Whatever ends up in the ASCII `filename=` fallback (transliterated,
        # dropped-to-empty, or the generic name), it must be safe to encode
        # as a header value — this is the actual property Req 26.3 cares
        # about, regardless of which branch of the helper produced it.
        for username, ext in [
            ("田中さくら🌸", "html"),
            ("田中", "拡張子"),
            ("café", "pdf"),
            ("", "html"),
        ]:
            header = _content_disposition(username, ext)
            fallback = header.split("filename=\"")[1].split("\"; filename*=")[0]
            fallback.encode("latin-1")  # raises UnicodeEncodeError if not safe

    def test_no_quote_or_backslash_leaks_into_quoted_string(self):
        header = _content_disposition('evil"name\\', "html")
        assert '"' not in header.split("filename*=")[0].split('filename="')[1].rstrip('"; ')
