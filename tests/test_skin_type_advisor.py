"""Unit tests for the skin type advisor tool."""

import logging
import pytest
from unittest.mock import patch, MagicMock, call

from backend.rag.retriever import RetrievedDoc
from backend.tools.skin_type_advisor import skin_type_advisor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _oily_docs():
    return [
        RetrievedDoc(
            content="Oily skin produces excess sebum and appears shiny throughout the day.",
            source_name="skin_type_classification",
            score=0.92,
        )
    ]


def _dry_docs():
    return [
        RetrievedDoc(
            content="Dry skin lacks sufficient oil and often feels tight or looks flaky.",
            source_name="skin_type_classification",
            score=0.88,
        )
    ]


def _sensitive_docs():
    return [
        RetrievedDoc(
            content="Sensitive skin reacts easily to products, causing redness and burning.",
            source_name="skin_type_classification",
            score=0.85,
        )
    ]


# ---------------------------------------------------------------------------
# 1. Classification returned and persisted
# ---------------------------------------------------------------------------

class TestClassificationAndPersistence:
    """Verify that a correct classification is returned and saved to ProfileStore."""

    def test_oily_classification_returned(self):
        """Result contains 'oily' when description and docs both indicate oily skin."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _oily_docs()
            MockProfileStore.return_value.update_skin_type.return_value = None

            result = skin_type_advisor.invoke(
                "description: my skin gets shiny by midday | username: testuser"
            )

        assert "oily" in result.lower()

    def test_oily_classification_persisted(self):
        """ProfileStore.update_skin_type is called with username='testuser' and skin_type='oily'."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _oily_docs()
            MockProfileStore.return_value.update_skin_type.return_value = None

            skin_type_advisor.invoke(
                "description: my skin gets shiny by midday | username: testuser"
            )

            MockProfileStore.return_value.update_skin_type.assert_called_once_with(
                "testuser", "oily"
            )

    def test_result_contains_profile_updated_message(self):
        """Result includes confirmation that the profile has been updated."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _oily_docs()
            MockProfileStore.return_value.update_skin_type.return_value = None

            result = skin_type_advisor.invoke(
                "description: shiny skin | username: testuser"
            )

        assert "profile has been updated" in result.lower()

    def test_result_contains_skin_type_label(self):
        """Result includes the 'Skin type:' label."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _oily_docs()
            MockProfileStore.return_value.update_skin_type.return_value = None

            result = skin_type_advisor.invoke(
                "description: shiny skin | username: testuser"
            )

        assert "Skin type:" in result

    def test_result_contains_characteristics_label(self):
        """Result includes the 'Characteristics:' label."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _oily_docs()
            MockProfileStore.return_value.update_skin_type.return_value = None

            result = skin_type_advisor.invoke(
                "description: shiny skin | username: testuser"
            )

        assert "Characteristics:" in result

    def test_dry_skin_classification(self):
        """Description with 'tight and flaky' results in 'dry' classification."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _dry_docs()
            MockProfileStore.return_value.update_skin_type.return_value = None

            result = skin_type_advisor.invoke(
                "description: my skin feels tight and flaky after washing | username: alice"
            )

        assert "dry" in result.lower()
        MockProfileStore.return_value.update_skin_type.assert_called_once_with("alice", "dry")

    def test_sensitive_skin_classification(self):
        """Description with 'red and burns' results in 'sensitive' classification."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _sensitive_docs()
            MockProfileStore.return_value.update_skin_type.return_value = None

            result = skin_type_advisor.invoke(
                "description: my skin turns red and burns after applying products | username: bob"
            )

        assert "sensitive" in result.lower()


# ---------------------------------------------------------------------------
# 2. Clarifying question when no docs retrieved
# ---------------------------------------------------------------------------

class TestClarifyingQuestionWhenNoDocs:
    """When Retriever returns an empty list, the tool must ask for more information."""

    def test_clarifying_question_returned(self):
        """Result contains a question mark when no docs are retrieved."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.update_skin_type.return_value = None

            result = skin_type_advisor.invoke(
                "description: my skin is weird | username: testuser"
            )

        assert "?" in result

    def test_no_skin_type_asserted_when_no_docs(self):
        """Result does not start with 'Skin type:' when no docs are retrieved."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.update_skin_type.return_value = None

            result = skin_type_advisor.invoke(
                "description: my skin is weird | username: testuser"
            )

        assert not result.startswith("Skin type:")

    def test_profile_not_updated_when_no_docs(self):
        """ProfileStore.update_skin_type is NOT called when no docs are retrieved."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.update_skin_type.return_value = None

            skin_type_advisor.invoke(
                "description: my skin is weird | username: testuser"
            )

            MockProfileStore.return_value.update_skin_type.assert_not_called()

    def test_clarifying_question_mentions_skin_detail(self):
        """Clarifying question guides the user to describe how skin feels after washing."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.update_skin_type.return_value = None

            result = skin_type_advisor.invoke(
                "description: not sure | username: testuser"
            )

        result_lower = result.lower()
        # The clarifying question should mention skin or washing or oily or tight
        assert any(word in result_lower for word in ["skin", "wash", "oily", "tight", "shine"])


# ---------------------------------------------------------------------------
# 3. ProfileStore called with correct arguments
# ---------------------------------------------------------------------------

class TestProfileStoreCalled:
    """Verify the exact arguments passed to ProfileStore.update_skin_type."""

    def test_update_skin_type_called_with_correct_username(self):
        """update_skin_type receives the exact username from the input string."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _oily_docs()
            MockProfileStore.return_value.update_skin_type.return_value = None

            skin_type_advisor.invoke(
                "description: shiny greasy skin | username: specificuser123"
            )

            args, kwargs = MockProfileStore.return_value.update_skin_type.call_args
            # Supports both positional and keyword call styles
            called_username = args[0] if args else kwargs.get("username")
            assert called_username == "specificuser123"

    def test_update_skin_type_called_with_valid_skin_type(self):
        """update_skin_type receives one of the six recognised skin type labels."""
        valid_types = {"oily", "dry", "combination", "sensitive", "dehydrated", "acneic"}

        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _oily_docs()
            MockProfileStore.return_value.update_skin_type.return_value = None

            skin_type_advisor.invoke(
                "description: shiny greasy skin | username: testuser"
            )

            args, kwargs = MockProfileStore.return_value.update_skin_type.call_args
            called_skin_type = args[1] if len(args) > 1 else kwargs.get("skin_type")
            assert called_skin_type in valid_types

    def test_update_skin_type_called_exactly_once(self):
        """update_skin_type is called exactly once per successful classification."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _oily_docs()
            MockProfileStore.return_value.update_skin_type.return_value = None

            skin_type_advisor.invoke(
                "description: shiny skin | username: testuser"
            )

            assert MockProfileStore.return_value.update_skin_type.call_count == 1


# ---------------------------------------------------------------------------
# 4. Empty description returns validation error
# ---------------------------------------------------------------------------

class TestEmptyDescriptionValidation:
    """Empty description must produce a validation error without calling ProfileStore."""

    def test_empty_description_returns_error(self):
        """Input with empty description field returns an error string."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            result = skin_type_advisor.invoke(
                "description:  | username: testuser"
            )

        assert "error" in result.lower() or "required" in result.lower()

    def test_empty_description_does_not_call_profile_store(self):
        """ProfileStore is never instantiated when description is empty."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            skin_type_advisor.invoke("description:  | username: testuser")

            MockProfileStore.return_value.update_skin_type.assert_not_called()

    def test_missing_description_key_returns_error(self):
        """Input without 'description:' key returns an error string."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            result = skin_type_advisor.invoke("username: testuser")

        assert "error" in result.lower() or "required" in result.lower()


# ---------------------------------------------------------------------------
# 5. Empty username returns validation error
# ---------------------------------------------------------------------------

class TestEmptyUsernameValidation:
    """Empty username must produce a validation error without calling ProfileStore."""

    def test_empty_username_returns_error(self):
        """Input with empty username field returns an error string."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            result = skin_type_advisor.invoke(
                "description: shiny skin | username: "
            )

        assert "error" in result.lower() or "required" in result.lower()

    def test_empty_username_does_not_call_profile_store(self):
        """ProfileStore is never instantiated when username is empty."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            skin_type_advisor.invoke("description: shiny skin | username: ")

            MockProfileStore.return_value.update_skin_type.assert_not_called()

    def test_missing_username_key_returns_error(self):
        """Input without 'username:' key returns an error string."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            result = skin_type_advisor.invoke("description: shiny skin")

        assert "error" in result.lower() or "required" in result.lower()


# ---------------------------------------------------------------------------
# 6. Retriever query string
# ---------------------------------------------------------------------------

class TestRetrieverQueryString:
    """Verify that the Retriever is called with the correct query."""

    def test_retriever_called_with_skin_type_prefix(self):
        """Retriever.query is called with 'skin type classification <description>'."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _oily_docs()
            MockProfileStore.return_value.update_skin_type.return_value = None

            skin_type_advisor.invoke(
                "description: shiny oily face | username: testuser"
            )

            call_args = MockRetriever.return_value.query.call_args[0][0]
            assert call_args.startswith("skin type classification")
            assert "shiny oily face" in call_args


# ---------------------------------------------------------------------------
# 7. Exception handling
# ---------------------------------------------------------------------------

class TestExceptionHandling:
    """Verify that unexpected exceptions produce a graceful fallback response."""

    def test_retriever_exception_returns_graceful_message(self):
        """When Retriever raises an exception, a user-friendly message is returned."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.side_effect = RuntimeError("connection failed")

            result = skin_type_advisor.invoke(
                "description: shiny skin | username: testuser"
            )

        assert "sorry" in result.lower() or "error" in result.lower()

    def test_retriever_exception_does_not_call_profile_store(self):
        """ProfileStore is not called when Retriever raises an exception."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.side_effect = RuntimeError("connection failed")

            skin_type_advisor.invoke(
                "description: shiny skin | username: testuser"
            )

            MockProfileStore.return_value.update_skin_type.assert_not_called()

    def test_exception_logs_error(self, caplog):
        """An exception during execution is logged at ERROR level."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.side_effect = RuntimeError("boom")
            caplog.set_level(logging.ERROR)

            skin_type_advisor.invoke(
                "description: shiny skin | username: testuser"
            )

        assert any(
            record.levelname == "ERROR" and "skin_type_advisor" in record.message
            for record in caplog.records
        )

    def test_profile_store_exception_returns_graceful_message(self):
        """When ProfileStore raises an exception, a user-friendly message is returned."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _oily_docs()
            MockProfileStore.return_value.update_skin_type.side_effect = Exception("db error")

            result = skin_type_advisor.invoke(
                "description: shiny skin | username: testuser"
            )

        assert "sorry" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# 8. Doc-based classification fallback
# ---------------------------------------------------------------------------

class TestDocBasedClassification:
    """When the description has no keyword match, fall back to doc content counts."""

    def test_doc_mention_drives_classification(self):
        """Classification falls back to the most-mentioned type in retrieved docs."""
        acneic_docs = [
            RetrievedDoc(
                content="Acneic skin is prone to breakouts. Acneic conditions involve clogged pores.",
                source_name="skin_type_classification",
                score=0.87,
            )
        ]
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = acneic_docs
            MockProfileStore.return_value.update_skin_type.return_value = None

            # Description has no specific keyword match
            result = skin_type_advisor.invoke(
                "description: I have skin issues | username: testuser"
            )

        assert "acneic" in result.lower()


# ---------------------------------------------------------------------------
# 9. Whitespace / formatting edge cases
# ---------------------------------------------------------------------------

class TestInputFormatEdgeCases:
    """Verify parser robustness to whitespace and ordering variations."""

    def test_extra_whitespace_in_parts(self):
        """Extra whitespace around description and username values is stripped."""
        with patch("backend.tools.skin_type_advisor.Retriever") as MockRetriever, \
             patch("backend.tools.skin_type_advisor.ProfileStore") as MockProfileStore:
            MockRetriever.return_value.query.return_value = _oily_docs()
            MockProfileStore.return_value.update_skin_type.return_value = None

            result = skin_type_advisor.invoke(
                "description:   shiny skin   |   username:   testuser   "
            )

        assert "Skin type:" in result
        MockProfileStore.return_value.update_skin_type.assert_called_once_with(
            "testuser", "oily"
        )
