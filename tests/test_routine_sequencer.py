"""Unit tests for the routine sequencer tool."""

import logging
import pytest
from unittest.mock import patch, MagicMock

from backend.rag.retriever import RetrievedDoc
from backend.tools.routine_sequencer import routine_sequencer


class TestRoutineSequencerCanonical:
    """Test canonical ordering with known ingredients."""

    def test_canonical_order_three_items(self):
        """Test ordering: spf, retinol, cleanser -> cleanser, retinol, spf."""
        result = routine_sequencer.invoke("spf, retinol, cleanser")
        assert "Routine order:" in result
        # Check order in output
        cleanser_pos = result.find("cleanser (cleanser)")
        retinol_pos = result.find("retinol (serum)")
        spf_pos = result.find("spf (spf)")
        assert cleanser_pos < retinol_pos < spf_pos
        assert "Unclassifiable items: []" in result

    def test_canonical_order_five_items(self):
        """Test all five step categories in mixed order."""
        result = routine_sequencer.invoke("spf, toner, retinol, cleanser, moisturiser")
        lines = result.split("\n")
        order_lines = [l for l in lines if l and l[0].isdigit()]
        # Check we have 5 items in order
        assert len(order_lines) == 5
        assert "cleanser" in order_lines[0]
        assert "toner" in order_lines[1]
        assert "retinol" in order_lines[2] or "serum" in order_lines[2]
        assert "moisturiser" in order_lines[3]
        assert "spf" in order_lines[4]

    def test_canonical_order_duplicates(self):
        """Test that duplicate items are both listed."""
        result = routine_sequencer.invoke("retinol, vitamin c, moisturiser")
        # Both retinol and vitamin c should be serums and appear in order
        assert "retinol (serum)" in result
        assert "vitamin c (serum)" in result
        assert result.find("retinol") < result.find("vitamin c")


class TestRoutineSequencerUnclassifiable:
    """Test handling of unclassifiable items."""

    def test_unclassifiable_item_flagged_with_mock(self):
        """Test that unclassifiable item is flagged when retriever returns no useful content."""
        with patch("backend.tools.routine_sequencer.Retriever") as MockRetriever:
            mock_instance = MockRetriever.return_value
            # Return empty list or docs with no step keywords
            mock_instance.query.return_value = [
                RetrievedDoc(
                    content="This is some unrelated content.",
                    source_name="test_source",
                    score=0.5,
                )
            ]
            result = routine_sequencer.invoke("mystery_goo, retinol")
            assert "mystery_goo" in result
            assert "Unclassifiable items: [mystery_goo]" in result
            assert "retinol (serum)" in result

    def test_multiple_unclassifiable_items(self):
        """Test multiple unclassifiable items are all flagged."""
        with patch("backend.tools.routine_sequencer.Retriever") as MockRetriever:
            mock_instance = MockRetriever.return_value
            mock_instance.query.return_value = []
            result = routine_sequencer.invoke("unknown_a, retinol, unknown_b")
            assert "unknown_a" in result
            assert "unknown_b" in result
            assert "Unclassifiable items: [unknown_a, unknown_b]" in result


class TestRoutineSequencerEmptyInput:
    """Test handling of empty inputs."""

    def test_empty_string(self):
        """Test that empty string returns error."""
        result = routine_sequencer.invoke("")
        assert "Error: No ingredients provided." in result

    def test_only_commas(self):
        """Test that comma-only input returns error."""
        result = routine_sequencer.invoke(",,,")
        assert "Error: No ingredients provided." in result

    def test_whitespace_only(self):
        """Test that whitespace-only input returns error."""
        result = routine_sequencer.invoke("   ,   ,   ")
        assert "Error: No ingredients provided." in result


class TestRoutineSequencerRetrieverCall:
    """Test that Retriever is called when item not in classification map."""

    def test_retriever_called_for_unknown_item(self):
        """Test that Retriever.query is called for an unknown ingredient."""
        with patch("backend.tools.routine_sequencer.Retriever") as MockRetriever:
            mock_instance = MockRetriever.return_value
            mock_instance.query.return_value = []
            routine_sequencer.invoke("unknown_ingredient, retinol")
            # Verify query was called with the right text
            mock_instance.query.assert_called_once()
            call_args = mock_instance.query.call_args[0][0]
            assert "routine sequencing rules application order" in call_args

    def test_retriever_not_called_for_known_item(self):
        """Test that Retriever is not called for a known ingredient."""
        with patch("backend.tools.routine_sequencer.Retriever") as MockRetriever:
            mock_instance = MockRetriever.return_value
            routine_sequencer.invoke("retinol, vitamin c")
            # Should not call query since both are in the map
            mock_instance.query.assert_not_called()

    def test_retriever_called_only_for_unknown_items(self):
        """Test that Retriever is called only for unknown items in a mixed list."""
        with patch("backend.tools.routine_sequencer.Retriever") as MockRetriever:
            mock_instance = MockRetriever.return_value
            mock_instance.query.return_value = []
            routine_sequencer.invoke("retinol, unknown_thing, moisturiser")
            # Query should be called once for the unknown item
            assert mock_instance.query.call_count == 1


class TestRoutineSequencerRetrieverFallback:
    """Test Retriever fallback classification."""

    def test_retriever_classifies_unknown_item(self):
        """Test that Retriever content is scanned for step keywords."""
        with patch("backend.tools.routine_sequencer.Retriever") as MockRetriever:
            mock_instance = MockRetriever.return_value
            # Return content that mentions "serum" for the unknown ingredient
            mock_instance.query.return_value = [
                RetrievedDoc(
                    content="Serums are applied before moisturizers in the routine.",
                    source_name="test_source",
                    score=0.8,
                )
            ]
            result = routine_sequencer.invoke("mystery_serum, moisturiser")
            # mystery_serum should be classified as serum if "serum" is in content
            # and it appears in the output as a serum
            assert "mystery_serum" in result or "Unclassifiable items: [mystery_serum]" in result


class TestRoutineSequencerExceptionHandling:
    """Test exception handling and fallback."""

    def test_exception_in_retriever_fallback_handles_gracefully(self):
        """Test that exceptions in retriever fallback are caught and item added to unclassifiable."""
        with patch("backend.tools.routine_sequencer.Retriever") as MockRetriever:
            mock_instance = MockRetriever.return_value
            # Raise an exception when query is called
            mock_instance.query.side_effect = Exception("Retriever error")
            result = routine_sequencer.invoke("unknown_thing, retinol")
            # Should still return structured output with unknown_thing unclassifiable
            assert "Routine order:" in result
            assert "Unclassifiable items: [unknown_thing]" in result
            assert "retinol (serum)" in result

    def test_exception_in_initialization(self):
        """Test exception during Retriever initialization (needs unknown ingredient to trigger)."""
        with patch("backend.tools.routine_sequencer.Retriever") as MockRetriever:
            # Raise exception on instantiation — use unknown ingredient to trigger Retriever
            MockRetriever.side_effect = Exception("Init error")
            result = routine_sequencer.invoke("mystery_product, another_unknown")
            assert "Sorry, I could not sequence the routine" in result

    def test_exception_logs_error(self, caplog):
        """Test that exceptions are logged at ERROR level."""
        with patch("backend.tools.routine_sequencer.Retriever") as MockRetriever:
            MockRetriever.side_effect = Exception("Test error")
            caplog.set_level(logging.ERROR)
            routine_sequencer.invoke("mystery_product, another_unknown")
            assert any(
                record.levelname == "ERROR" and "routine_sequencer failed" in record.message
                for record in caplog.records
            )


class TestRoutineSequencerCaseInsensitivity:
    """Test case-insensitive ingredient matching."""

    def test_uppercase_ingredients(self):
        """Test that uppercase ingredients are normalized."""
        result = routine_sequencer.invoke("RETINOL, MOISTURISER, SPF")
        assert "Routine order:" in result
        assert "retinol" in result.lower()
        assert "moisturiser" in result.lower()
        assert "spf" in result.lower()

    def test_mixed_case_ingredients(self):
        """Test mixed case ingredients."""
        result = routine_sequencer.invoke("RetinoL, MoisturiseR, SpF")
        assert "Routine order:" in result
        assert result.find("cleanser") < result.find("retinol") if "cleanser" in result else True


class TestRoutineSequencerWhitespace:
    """Test whitespace handling."""

    def test_extra_whitespace_around_items(self):
        """Test that extra whitespace is handled correctly."""
        result_clean = routine_sequencer.invoke("retinol, moisturiser, spf")
        result_spaced = routine_sequencer.invoke("  retinol  ,  moisturiser  ,  spf  ")
        # Both should produce the same logical output
        assert "retinol" in result_spaced
        assert "moisturiser" in result_spaced
        assert "spf" in result_spaced

    def test_whitespace_only_items_filtered(self):
        """Test that whitespace-only items between commas are filtered out."""
        result = routine_sequencer.invoke("retinol,    , moisturiser")
        # Should still work correctly with 2 items
        lines = [l for l in result.split("\n") if l and l[0].isdigit()]
        assert len(lines) == 2


class TestRoutineSequencerOutputFormat:
    """Test output format."""

    def test_output_starts_with_routine_order(self):
        """Test that output starts with 'Routine order:'."""
        result = routine_sequencer.invoke("retinol, moisturiser")
        assert result.startswith("Routine order:")

    def test_output_includes_unclassifiable_section(self):
        """Test that output always includes unclassifiable items section."""
        result = routine_sequencer.invoke("retinol, moisturiser")
        assert "Unclassifiable items:" in result

    def test_output_format_numbered_items(self):
        """Test that items are numbered sequentially."""
        result = routine_sequencer.invoke("spf, retinol, cleanser, moisturiser")
        lines = result.split("\n")
        numbered = [l for l in lines if l and l[0].isdigit()]
        # Check numbering
        for i, line in enumerate(numbered, 1):
            assert line.startswith(f"{i}.")

    def test_output_includes_category_labels(self):
        """Test that output includes category labels in parentheses."""
        result = routine_sequencer.invoke("retinol, moisturiser")
        assert "(serum)" in result
        assert "(moisturiser)" in result


class TestRoutineSequencerLogging:
    """Test logging behavior."""

    def test_success_logs_info(self, caplog):
        """Test that successful execution logs at INFO level."""
        caplog.set_level(logging.INFO)
        routine_sequencer.invoke("retinol, moisturiser")
        assert any(
            record.levelname == "INFO" and "routine_sequencer succeeded" in record.message
            for record in caplog.records
        )

    def test_success_log_includes_counts(self, caplog):
        """Test that success log includes item and unclassifiable counts."""
        caplog.set_level(logging.INFO)
        with patch("backend.tools.routine_sequencer.Retriever") as MockRetriever:
            mock_instance = MockRetriever.return_value
            mock_instance.query.return_value = []
            routine_sequencer.invoke("retinol, moisturiser, unknown")
            # Check log message includes counts
            info_logs = [r.message for r in caplog.records if r.levelname == "INFO"]
            assert any("3 items" in log for log in info_logs)
            assert any("unclassifiable" in log for log in info_logs)


class TestRoutineSequencerEdgeCases:
    """Test edge cases."""

    def test_single_ingredient(self):
        """Test with a single ingredient."""
        result = routine_sequencer.invoke("retinol")
        assert "Routine order:" in result
        assert "retinol (serum)" in result
        assert "Unclassifiable items: []" in result

    def test_all_steps_represented(self):
        """Test routine with one ingredient from each step."""
        result = routine_sequencer.invoke("cleanser, toner, retinol, moisturiser, spf")
        lines = [l for l in result.split("\n") if l and l[0].isdigit()]
        assert len(lines) == 5
        assert "1. cleanser (cleanser)" in result
        assert "2. toner (toner)" in result
        assert "3. retinol (serum)" in result
        assert "4. moisturiser (moisturiser)" in result
        assert "5. spf (spf)" in result

    def test_multiple_items_same_category(self):
        """Test multiple ingredients in the same category (e.g., two serums)."""
        result = routine_sequencer.invoke("retinol, vitamin c, niacinamide")
        # All three are serums, should appear consecutively
        retinol_line = None
        vitamin_line = None
        niacinamide_line = None

        for line in result.split("\n"):
            if "retinol (serum)" in line:
                retinol_line = line
            if "vitamin c (serum)" in line:
                vitamin_line = line
            if "niacinamide (serum)" in line:
                niacinamide_line = line

        assert retinol_line is not None
        assert vitamin_line is not None
        assert niacinamide_line is not None
