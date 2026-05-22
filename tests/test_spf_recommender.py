"""Unit tests for the SPF recommender tool."""

import logging
import pytest
from unittest.mock import patch, MagicMock

from backend.rag.retriever import RetrievedDoc
from backend.tools.spf_recommender import spf_recommender


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spf_docs():
    """Return mock SPF-related documents."""
    return [
        RetrievedDoc(
            content="Use SPF 50+ for optimal UV protection. Reapply every 2 hours.",
            source_name="UV_Protection_Guide",
            score=0.95,
        ),
        RetrievedDoc(
            content="PA+++ offers broad-spectrum UVA protection alongside SPF.",
            source_name="Sunscreen_Standards",
            score=0.92,
        ),
    ]


# ---------------------------------------------------------------------------
# 1. SPF 50+ enforcement in normal query
# ---------------------------------------------------------------------------

class TestSPF50Enforcement:
    """Verify that SPF 50+ standard is enforced in recommendations."""

    def test_normal_query_contains_spf_50_plus(self):
        """Normal query returns recommendation containing 'SPF 50+'."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = _spf_docs()

            result = spf_recommender.invoke("What sunscreen should I use?")

            assert "SPF 50+" in result

    def test_normal_query_mentions_standard(self):
        """Result mentions the SPF 50+ / PA+++ standard."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = _spf_docs()

            result = spf_recommender.invoke("I need sunscreen recommendations")

            assert "SPF 50+" in result or "PA+++" in result

    def test_calls_retriever_with_fixed_query(self):
        """Retriever is called with the fixed query 'SPF sunscreen UV protection'."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = _spf_docs()

            spf_recommender.invoke("What's the best sunscreen?")

            MockRetriever.return_value.query.assert_called_once_with(
                "SPF sunscreen UV protection"
            )

    def test_different_user_queries_use_same_retriever_query(self):
        """Different user queries all use the same retriever query."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = _spf_docs()

            queries = [
                "What sunscreen?",
                "Best SPF?",
                "UV protection advice",
            ]

            for query in queries:
                spf_recommender.invoke(query)

            # All calls should be with the fixed query
            calls = MockRetriever.return_value.query.call_args_list
            assert len(calls) == len(queries)
            for call_obj in calls:
                assert call_obj[0][0] == "SPF sunscreen UV protection"


# ---------------------------------------------------------------------------
# 2. Low-SPF refusal path
# ---------------------------------------------------------------------------

class TestLowSPFRefusal:
    """Verify that low-SPF requests (SPF 30, SPF 15, etc.) trigger refusal."""

    def test_spf_30_request_triggers_refusal(self):
        """Query with 'SPF 30' returns refusal text."""
        result = spf_recommender.invoke("Can I use SPF 30?")

        assert "SPF Standard:" in result
        assert "SPF 30" in result
        assert "SPF 50+" in result

    def test_spf_30_request_recommends_higher(self):
        """SPF 30 refusal recommends SPF 50+ instead."""
        result = spf_recommender.invoke("Is SPF 30 okay?")

        assert "SPF 50+" in result
        assert "lightweight SPF 50+" in result

    def test_spf_15_request_triggers_refusal(self):
        """Query with 'SPF 15' returns refusal text."""
        result = spf_recommender.invoke("What about SPF 15?")

        assert "SPF Standard:" in result

    def test_spf_20_request_triggers_refusal(self):
        """Query with 'SPF 20' returns refusal text."""
        result = spf_recommender.invoke("Is SPF 20 suitable?")

        assert "SPF Standard:" in result

    def test_spf_50_plus_request_does_not_trigger_refusal(self):
        """Query with 'SPF 50+' does not trigger refusal."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = _spf_docs()

            result = spf_recommender.invoke("Can you recommend SPF 50+?")

            # Should not contain the refusal message
            assert "SPF Standard: The recommended minimum is SPF 50+ with PA+++" not in result

    def test_case_insensitive_spf_30_detection(self):
        """SPF 30 detection is case-insensitive."""
        result_lower = spf_recommender.invoke("spf 30")
        result_upper = spf_recommender.invoke("SPF 30")
        result_mixed = spf_recommender.invoke("SpF 30")

        assert "SPF Standard:" in result_lower
        assert "SPF Standard:" in result_upper
        assert "SPF Standard:" in result_mixed

    def test_spf_300_not_detected_as_low_spf(self):
        """SPF 300 is not mistaken for SPF 30."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = _spf_docs()

            result = spf_recommender.invoke("Is SPF 300 available?")

            # Should not trigger refusal (SPF 300 is not a low SPF)
            assert "SPF Standard: The recommended minimum" not in result


# ---------------------------------------------------------------------------
# 3. Citations included in output
# ---------------------------------------------------------------------------

class TestCitations:
    """Verify that source names from retrieved docs are included as citations."""

    def test_source_names_included_in_output(self):
        """Output includes source names from retrieved documents."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            docs = [
                RetrievedDoc(
                    content="SPF 50+ recommended.",
                    source_name="UV_Guide",
                    score=0.9,
                ),
                RetrievedDoc(
                    content="PA+++ for UVA protection.",
                    source_name="Broad_Spectrum_Standards",
                    score=0.88,
                ),
            ]
            MockRetriever.return_value.query.return_value = docs

            result = spf_recommender.invoke("Best sunscreen?")

            assert "UV_Guide" in result
            assert "Broad_Spectrum_Standards" in result

    def test_single_source_cited(self):
        """Single source name is cited correctly."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            docs = [
                RetrievedDoc(
                    content="Use SPF 50+.",
                    source_name="Source_A",
                    score=0.95,
                ),
            ]
            MockRetriever.return_value.query.return_value = docs

            result = spf_recommender.invoke("Sunscreen advice?")

            assert "Sources: Source_A" in result

    def test_multiple_sources_comma_separated(self):
        """Multiple source names are comma-separated."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            docs = [
                RetrievedDoc(
                    content="SPF 50+.",
                    source_name="SourceA",
                    score=0.95,
                ),
                RetrievedDoc(
                    content="PA+++.",
                    source_name="SourceB",
                    score=0.90,
                ),
            ]
            MockRetriever.return_value.query.return_value = docs

            result = spf_recommender.invoke("Sunscreen?")

            assert "Sources: SourceA, SourceB" in result

    def test_duplicate_sources_not_repeated(self):
        """Duplicate source names appear only once."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            docs = [
                RetrievedDoc(
                    content="Content 1",
                    source_name="SharedSource",
                    score=0.95,
                ),
                RetrievedDoc(
                    content="Content 2",
                    source_name="SharedSource",
                    score=0.90,
                ),
            ]
            MockRetriever.return_value.query.return_value = docs

            result = spf_recommender.invoke("Sunscreen?")

            # Count occurrences of "SharedSource" in the sources line
            assert result.count("SharedSource") == 1


# ---------------------------------------------------------------------------
# 4. No docs returns generic recommendation
# ---------------------------------------------------------------------------

class TestNoDocsRetrieved:
    """Verify fallback behavior when no documents are retrieved."""

    def test_no_docs_returns_generic_recommendation(self):
        """When retriever returns [], still return valid recommendation."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = []

            result = spf_recommender.invoke("Sunscreen advice?")

            assert "SPF 50+" in result
            assert "broad-spectrum" in result.lower()

    def test_no_docs_recommendation_mentions_morning_routine(self):
        """Generic recommendation mentions morning routine."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = []

            result = spf_recommender.invoke("Best sunscreen?")

            assert "morning routine" in result.lower()

    def test_no_docs_recommendation_mentions_application_timing(self):
        """Generic recommendation mentions 15 minutes before exposure."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            MockRetriever.return_value.query.return_value = []

            result = spf_recommender.invoke("Sunscreen tips?")

            assert "15 minutes" in result


# ---------------------------------------------------------------------------
# 5. Exception handling returns graceful fallback
# ---------------------------------------------------------------------------

class TestExceptionHandling:
    """Verify graceful error handling."""

    def test_retriever_exception_returns_fallback(self):
        """If Retriever raises an exception, return graceful fallback."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            MockRetriever.return_value.query.side_effect = Exception("Connection error")

            result = spf_recommender.invoke("Sunscreen?")

            assert "Sorry, I could not generate an SPF recommendation" in result

    def test_fallback_suggests_retry(self):
        """Fallback message suggests trying again."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            MockRetriever.return_value.query.side_effect = RuntimeError("API failure")

            result = spf_recommender.invoke("Best sunscreen?")

            assert "Please try again" in result

    def test_exception_logged(self, caplog):
        """Exceptions are logged."""
        caplog.set_level(logging.ERROR)

        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            MockRetriever.return_value.query.side_effect = ValueError("Bad input")

            spf_recommender.invoke("Sunscreen?")

            assert len(caplog.records) > 0
            assert any(
                record.levelname == "ERROR" and "spf_recommender failed" in record.message
                for record in caplog.records
            )


# ---------------------------------------------------------------------------
# 6. Integration-like tests with various scenarios
# ---------------------------------------------------------------------------

class TestIntegration:
    """Integration-like tests combining multiple aspects."""

    def test_full_workflow_with_docs(self):
        """Full workflow: query with docs retrieved and cited."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            docs = [
                RetrievedDoc(
                    content="SPF 50+ is the gold standard for sun protection.",
                    source_name="Dermatology_Guide",
                    score=0.97,
                ),
            ]
            MockRetriever.return_value.query.return_value = docs

            result = spf_recommender.invoke("What SPF level should I use?")

            assert "SPF Recommendation (SPF 50+ / PA+++ standard)" in result
            assert "SPF 50+ is the gold standard" in result
            assert "Dermatology_Guide" in result

    def test_low_spf_refusal_does_not_call_retriever(self):
        """Low-SPF request returns immediately without calling Retriever."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            result = spf_recommender.invoke("Can I use SPF 30?")

            # Retriever should not be called for low-SPF requests
            MockRetriever.assert_not_called()
            assert "SPF 30" in result

    def test_recommendation_format_with_multiple_sources(self):
        """Recommendation has proper format with header and sources."""
        with patch("backend.tools.spf_recommender.Retriever") as MockRetriever:
            docs = [
                RetrievedDoc(
                    content="Content A",
                    source_name="Source1",
                    score=0.95,
                ),
                RetrievedDoc(
                    content="Content B",
                    source_name="Source2",
                    score=0.90,
                ),
            ]
            MockRetriever.return_value.query.return_value = docs

            result = spf_recommender.invoke("Sunscreen?")

            lines = result.split("\n")
            assert "SPF Recommendation (SPF 50+ / PA+++ standard):" in lines[0]
            assert any("Sources:" in line for line in lines)
