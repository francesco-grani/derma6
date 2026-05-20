"""Unit tests for the conflict checker tool."""

import logging
import pytest
from unittest.mock import patch

import backend.tools.conflict_checker as cc_module
from backend.tools.conflict_checker import conflict_checker


class TestConflictCheckerBasic:
    """Test basic functionality of the conflict checker."""

    def test_known_safe_pair(self):
        """Test a known safe pair: niacinamide + vitamin c."""
        result = conflict_checker.invoke("niacinamide, vitamin c")
        assert "Verdict: safe" in result
        assert "Reason:" in result
        assert "Unknown ingredients: []" in result

    def test_known_use_at_different_times_pair(self):
        """Test a known use-at-different-times pair: retinol + vitamin c."""
        result = conflict_checker.invoke("retinol, vitamin c")
        assert "Verdict: use-at-different-times" in result
        assert "Reason:" in result
        assert "Unknown ingredients: []" in result

    def test_unknown_pair(self):
        """Test an unknown pair that has no conflict data."""
        result = conflict_checker.invoke("zinc, copper")
        assert "Verdict: unknown_ingredient" in result
        assert "No conflict data" in result
        assert "Consult a dermatologist" in result
        assert "Unknown ingredients: [zinc, copper]" in result

    def test_both_orderings_return_same_result(self):
        """Test that order of ingredients doesn't matter: retinol + aha vs aha + retinol."""
        result_1 = conflict_checker.invoke("retinol, aha")
        result_2 = conflict_checker.invoke("aha, retinol")
        assert result_1 == result_2

    def test_reverse_order_safe_pair(self):
        """Test reverse order for a safe pair: vitamin c + niacinamide vs niacinamide + vitamin c."""
        result_1 = conflict_checker.invoke("niacinamide, vitamin c")
        result_2 = conflict_checker.invoke("vitamin c, niacinamide")
        assert result_1 == result_2

    def test_reverse_order_use_at_different_times_pair(self):
        """Test reverse order for use-at-different-times: vitamin c + retinol vs retinol + vitamin c."""
        result_1 = conflict_checker.invoke("retinol, vitamin c")
        result_2 = conflict_checker.invoke("vitamin c, retinol")
        assert result_1 == result_2


class TestConflictCheckerValidation:
    """Test input validation."""

    def test_empty_first_ingredient(self):
        """Test empty first ingredient: ', vitamin c'."""
        result = conflict_checker.invoke(", vitamin c")
        assert "Error: Both ingredient names must be non-empty" in result

    def test_empty_both_ingredients(self):
        """Test both empty: ','."""
        result = conflict_checker.invoke(",")
        assert "Error: Both ingredient names must be non-empty" in result

    def test_whitespace_only_first_ingredient(self):
        """Test whitespace-only first ingredient."""
        result = conflict_checker.invoke("   , vitamin c")
        assert "Error: Both ingredient names must be non-empty" in result

    def test_whitespace_only_both_ingredients(self):
        """Test whitespace-only both ingredients."""
        result = conflict_checker.invoke("   ,   ")
        assert "Error: Both ingredient names must be non-empty" in result


class TestConflictCheckerEdgeCases:
    """Test edge cases and specific pairs from conflict_table.json."""

    def test_retinol_aha_conflict(self):
        """Test retinol + aha (use-at-different-times)."""
        result = conflict_checker.invoke("retinol, aha")
        assert "Verdict: use-at-different-times" in result

    def test_retinol_bha_conflict(self):
        """Test retinol + bha (use-at-different-times)."""
        result = conflict_checker.invoke("retinol, bha")
        assert "Verdict: use-at-different-times" in result

    def test_benzoyl_peroxide_retinol_conflict(self):
        """Test benzoyl peroxide + retinol (use-at-different-times)."""
        result = conflict_checker.invoke("benzoyl peroxide, retinol")
        assert "Verdict: use-at-different-times" in result

    def test_niacinamide_retinol_safe(self):
        """Test niacinamide + retinol (safe)."""
        result = conflict_checker.invoke("niacinamide, retinol")
        assert "Verdict: safe" in result

    def test_hyaluronic_acid_retinol_safe(self):
        """Test hyaluronic acid + retinol (safe)."""
        result = conflict_checker.invoke("hyaluronic acid, retinol")
        assert "Verdict: safe" in result

    def test_aha_bha_conflict(self):
        """Test aha + bha (use-at-different-times)."""
        result = conflict_checker.invoke("aha, bha")
        assert "Verdict: use-at-different-times" in result

    def test_case_insensitivity(self):
        """Test that ingredient matching is case-insensitive."""
        result_lower = conflict_checker.invoke("retinol, vitamin c")
        result_upper = conflict_checker.invoke("RETINOL, VITAMIN C")
        result_mixed = conflict_checker.invoke("RetinoL, ViTamin C")
        assert result_lower == result_upper == result_mixed

    def test_whitespace_normalization(self):
        """Test that extra whitespace is handled correctly."""
        result_clean = conflict_checker.invoke("retinol, vitamin c")
        result_spaces = conflict_checker.invoke("  retinol  ,  vitamin c  ")
        assert result_clean == result_spaces


class TestConflictCheckerLogging:
    """Test logging behavior."""

    def test_known_pair_logs_info(self, caplog):
        """Test that a known pair logs at INFO level."""
        caplog.set_level(logging.INFO)
        conflict_checker.invoke("retinol, vitamin c")
        # Verify that INFO log was produced with ingredient names
        assert len(caplog.records) > 0
        assert any(
            record.levelname == "INFO" and "retinol" in record.message and "vitamin c" in record.message
            for record in caplog.records
        )

    def test_unknown_pair_logs_warning(self, caplog):
        """Test that an unknown pair logs at WARNING level."""
        caplog.set_level(logging.WARNING)
        conflict_checker.invoke("unknown_a, unknown_b")
        # Verify that WARNING log was produced with ingredient names
        assert len(caplog.records) > 0
        assert any(
            record.levelname == "WARNING" and "unknown_a" in record.message and "unknown_b" in record.message
            for record in caplog.records
        )


class TestConflictCheckerVerdicts:
    """Test specific verdict types including do-not-use."""

    def test_do_not_use_verdict_via_mock(self):
        """Test the do-not-use verdict using a mocked conflict table."""
        synthetic_table = {
            frozenset({"retinol", "glycolic acid"}): {
                "verdict": "do-not-use",
                "reason": "Synthetic test: do not combine these."
            }
        }
        with patch.object(cc_module, "_CONFLICT_TABLE", synthetic_table):
            result = conflict_checker.invoke("retinol, glycolic acid")
        assert "Verdict: do-not-use" in result
        assert "Synthetic test: do not combine these." in result
        assert "Unknown ingredients: []" in result
