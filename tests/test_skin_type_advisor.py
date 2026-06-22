"""Unit tests for backend.tools.skin_type_advisor."""

from unittest.mock import MagicMock, patch

import pytest

from backend.tools.skin_type_advisor import (
    SKIN_TYPES,
    _classify_from_description,
    _classify_from_docs,
    _extract_characteristic,
    _CHARACTERISTICS,
    skin_type_advisor,
)
from backend.rag.retriever import RetrievedDoc


class TestClassifyFromDescription:
    @pytest.mark.parametrize("desc,expected", [
        ("my skin is really shiny and greasy by noon", "oily"),
        ("my face feels tight and looks flaky", "dry"),
        ("oily t-zone but dry cheeks", "combination"),
        ("skin burns and tingles with new products", "sensitive"),
        ("skin lacks water, feels thirsty and dehydrated all day", "dehydrated"),
        ("lots of breakouts and acne blemishes", "acneic"),
    ])
    def test_keyword_classification(self, desc, expected):
        result = _classify_from_description(desc)
        assert result == expected

    def test_no_keywords_returns_none(self):
        result = _classify_from_description("neutral normal skin")
        assert result is None

    def test_highest_score_wins(self):
        # Multiple oily keywords should beat one dry keyword
        desc = "shiny greasy oily sebum, slightly tight"
        result = _classify_from_description(desc)
        assert result == "oily"

    def test_case_insensitive(self):
        assert _classify_from_description("SHINY GREASY FACE") == "oily"


class TestClassifyFromDocs:
    def test_most_mentioned_skin_type(self):
        docs = [
            RetrievedDoc(content="oily skin oily skin oily skin dry skin", source_name="src", score=0.9),
        ]
        result = _classify_from_docs(docs)
        assert result == "oily"

    def test_no_skin_type_mentioned(self):
        docs = [RetrievedDoc(content="apply moisturiser every morning", source_name="src", score=0.9)]
        result = _classify_from_docs(docs)
        assert result is None

    def test_empty_docs_list(self):
        # Should handle empty list gracefully
        result = _classify_from_docs([])
        assert result is None


class TestExtractCharacteristic:
    def test_returns_matching_sentence_from_docs(self):
        docs = [
            RetrievedDoc(
                content="Oily skin produces excess sebum. Use gentle cleanser.",
                source_name="src",
                score=0.9,
            )
        ]
        result = _extract_characteristic("oily", docs)
        assert "oily" in result.lower()
        assert result.endswith(".")

    def test_falls_back_to_hardcoded_characteristic(self):
        result = _extract_characteristic("oily", [])
        assert result == _CHARACTERISTICS["oily"]

    def test_unknown_skin_type_empty_string(self):
        result = _extract_characteristic("unknown_type", [])
        assert result == ""


class TestSkinTypeAdvisorTool:
    @patch("backend.tools.skin_type_advisor.ProfileStore")
    @patch("backend.tools.skin_type_advisor.Retriever")
    def test_classifies_oily_and_saves(self, mock_retriever_cls, mock_store_cls):
        mock_r = MagicMock()
        mock_r.query.return_value = [
            RetrievedDoc(content="oily skin oily skin", source_name="src", score=0.9)
        ]
        mock_retriever_cls.return_value = mock_r
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store

        result = skin_type_advisor.invoke("description: my face is shiny and greasy | username: alice")
        assert "oily" in result.lower()
        mock_store.update_skin_type.assert_called_once_with("alice", "oily")

    @patch("backend.tools.skin_type_advisor.ProfileStore")
    @patch("backend.tools.skin_type_advisor.Retriever")
    def test_classifies_dry_skin(self, mock_retriever_cls, mock_store_cls):
        mock_r = MagicMock()
        mock_r.query.return_value = []
        mock_retriever_cls.return_value = mock_r
        mock_store_cls.return_value = MagicMock()

        result = skin_type_advisor.invoke("description: my skin is tight and flaky | username: bob")
        assert "dry" in result.lower()

    def test_missing_description_returns_error(self):
        result = skin_type_advisor.invoke("username: alice")
        assert "Error" in result
        assert "description" in result

    def test_missing_username_returns_error(self):
        result = skin_type_advisor.invoke("description: shiny skin")
        assert "Error" in result
        assert "username" in result

    def test_empty_description_returns_error(self):
        result = skin_type_advisor.invoke("description: | username: alice")
        assert "Error" in result

    @patch("backend.tools.skin_type_advisor.ProfileStore")
    @patch("backend.tools.skin_type_advisor.Retriever")
    def test_no_match_no_docs_asks_for_detail(self, mock_retriever_cls, mock_store_cls):
        mock_r = MagicMock()
        mock_r.query.return_value = []
        mock_retriever_cls.return_value = mock_r

        result = skin_type_advisor.invoke("description: fine | username: carol")
        assert "detail" in result.lower() or "describe" in result.lower()

    @patch("backend.tools.skin_type_advisor.ProfileStore")
    @patch("backend.tools.skin_type_advisor.Retriever")
    def test_result_includes_profile_updated(self, mock_retriever_cls, mock_store_cls):
        mock_r = MagicMock()
        mock_r.query.return_value = []
        mock_retriever_cls.return_value = mock_r
        mock_store_cls.return_value = MagicMock()

        result = skin_type_advisor.invoke("description: shiny oily face | username: dave")
        assert "profile" in result.lower()

    @patch("backend.tools.skin_type_advisor.ProfileStore")
    @patch("backend.tools.skin_type_advisor.Retriever")
    def test_exception_returns_error_message(self, mock_retriever_cls, mock_store_cls):
        mock_retriever_cls.side_effect = Exception("network error")
        result = skin_type_advisor.invoke("description: oily skin | username: dave")
        assert "sorry" in result.lower() or "could not" in result.lower()

    @patch("backend.tools.skin_type_advisor.ProfileStore")
    @patch("backend.tools.skin_type_advisor.Retriever")
    def test_doc_fallback_classifies_when_no_keyword_match(self, mock_retriever_cls, mock_store_cls):
        mock_r = MagicMock()
        mock_r.query.return_value = [
            RetrievedDoc(content="sensitive sensitive sensitive skin type", source_name="src", score=0.9)
        ]
        mock_retriever_cls.return_value = mock_r
        mock_store_cls.return_value = MagicMock()

        result = skin_type_advisor.invoke("description: unusual skin | username: eve")
        assert "sensitive" in result.lower()
