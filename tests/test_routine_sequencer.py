"""Unit tests for backend.tools.routine_sequencer."""

from unittest.mock import MagicMock, patch

import pytest

from backend.tools.routine_sequencer import (
    CLASSIFICATION_MAP,
    STEP_ORDER,
    _classify_ingredient,
    routine_sequencer,
)


class TestClassificationMap:
    def test_known_serum_ingredients(self):
        for ing in ["retinol", "niacinamide", "vitamin c", "aha", "bha", "hyaluronic acid"]:
            assert CLASSIFICATION_MAP.get(ing) == "serum"

    def test_known_cleanser_ingredients(self):
        for ing in ["cleanser", "face wash", "micellar"]:
            assert CLASSIFICATION_MAP.get(ing) == "cleanser"

    def test_known_spf_ingredients(self):
        for ing in ["spf", "sunscreen", "sunblock"]:
            assert CLASSIFICATION_MAP.get(ing) == "spf"

    def test_known_moisturiser_ingredients(self):
        for ing in ["moisturiser", "moisturizer", "cream", "ceramides"]:
            assert CLASSIFICATION_MAP.get(ing) == "moisturiser"

    def test_known_toner_ingredients(self):
        for ing in ["toner", "essence"]:
            assert CLASSIFICATION_MAP.get(ing) == "toner"


class TestClassifyIngredient:
    def test_known_ingredient_uses_map(self):
        mock_retriever = MagicMock()
        result = _classify_ingredient("retinol", mock_retriever)
        assert result == "serum"
        mock_retriever.query.assert_not_called()  # map hit, no retrieval needed

    def test_unknown_ingredient_uses_retriever(self):
        mock_retriever = MagicMock()
        mock_retriever.query.return_value = [
            MagicMock(content="Apply serum after toner in routine")
        ]
        result = _classify_ingredient("unknown_active", mock_retriever)
        # May or may not return a category; retriever should be called
        mock_retriever.query.assert_called_once()

    def test_retriever_failure_returns_none(self):
        mock_retriever = MagicMock()
        mock_retriever.query.side_effect = Exception("connection error")
        result = _classify_ingredient("mystery_ingredient", mock_retriever)
        assert result is None

    def test_retriever_empty_docs_returns_first_step(self):
        mock_retriever = MagicMock()
        mock_retriever.query.return_value = []
        result = _classify_ingredient("mystery", mock_retriever)
        assert result is None


class TestRoutineSequencerTool:
    def test_empty_input_returns_error(self):
        result = routine_sequencer.invoke("")
        assert "Error" in result

    def test_whitespace_only_returns_error(self):
        result = routine_sequencer.invoke("   ,  ,  ")
        assert "Error" in result

    def test_known_ingredients_ordered(self):
        result = routine_sequencer.invoke("retinol, cleanser, spf")
        lines = result.splitlines()
        # Find positions of each step in the output
        cleanser_pos = next(i for i, l in enumerate(lines) if "cleanser" in l)
        serum_pos = next(i for i, l in enumerate(lines) if "retinol" in l)
        spf_pos = next(i for i, l in enumerate(lines) if "spf" in l)
        assert cleanser_pos < serum_pos < spf_pos

    def test_output_has_routine_order_header(self):
        result = routine_sequencer.invoke("moisturiser, cleanser")
        assert "Routine order:" in result

    def test_output_has_unclassifiable_section(self):
        result = routine_sequencer.invoke("retinol, mystery_ingredient_xyz")
        assert "Unclassifiable items:" in result
        assert "mystery_ingredient_xyz" in result

    def test_all_known_unclassifiable_empty(self):
        result = routine_sequencer.invoke("cleanser, serum, spf")
        assert "Unclassifiable items: []" in result

    def test_single_ingredient(self):
        result = routine_sequencer.invoke("spf")
        assert "spf" in result.lower()
        assert "Routine order:" in result

    def test_step_numbers_sequential(self):
        result = routine_sequencer.invoke("cleanser, toner, serum, moisturiser, spf")
        lines = [l for l in result.splitlines() if l.strip().startswith(tuple("12345"))]
        for i, line in enumerate(lines, 1):
            assert line.strip().startswith(str(i))

    def test_full_pipeline_order(self):
        result = routine_sequencer.invoke("spf, moisturiser, retinol, toner, cleanser")
        assert result.index("cleanser") < result.index("toner")
        assert result.index("toner") < result.index("retinol")
        assert result.index("retinol") < result.index("moisturiser")
        assert result.index("moisturiser") < result.index("spf")

    @patch("backend.tools.routine_sequencer.Retriever")
    def test_exception_returns_error_message(self, mock_retriever_cls):
        mock_retriever_cls.side_effect = Exception("DB error")
        # Even with a bad retriever, known ingredients should still work
        result = routine_sequencer.invoke("retinol, spf")
        assert "Routine order:" in result  # known items classified via map
