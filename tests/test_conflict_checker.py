"""Unit tests for backend.tools.conflict_checker."""

import json
import pytest
from pathlib import Path
from unittest.mock import mock_open, patch

from backend.tools.conflict_checker import (
    _load_conflict_table,
    _normalize_ingredient,
    _CONFLICT_TABLE,
    conflict_checker,
)


class TestNormalizeIngredient:
    def test_lowercases(self):
        assert _normalize_ingredient("Retinol") == "retinol"

    def test_strips_whitespace(self):
        assert _normalize_ingredient("  vitamin c  ") == "vitamin c"

    def test_lowercases_and_strips(self):
        assert _normalize_ingredient("  AHA  ") == "aha"

    def test_empty_string(self):
        assert _normalize_ingredient("") == ""


class TestLoadConflictTable:
    def test_table_is_loaded(self):
        assert len(_CONFLICT_TABLE) > 0

    def test_keys_are_frozensets(self):
        for key in _CONFLICT_TABLE:
            assert isinstance(key, frozenset)

    def test_values_have_verdict_and_reason(self):
        for val in _CONFLICT_TABLE.values():
            assert "verdict" in val
            assert "reason" in val

    def test_known_pair_retinol_vitamin_c(self):
        key = frozenset({"retinol", "vitamin c"})
        assert key in _CONFLICT_TABLE
        assert _CONFLICT_TABLE[key]["verdict"] != ""


class TestConflictCheckerTool:
    def test_known_conflict_returns_verdict(self):
        result = conflict_checker.invoke("retinol, vitamin c")
        assert "Verdict:" in result
        assert "Reason:" in result

    def test_known_conflict_order_independent(self):
        result_ab = conflict_checker.invoke("retinol, vitamin c")
        result_ba = conflict_checker.invoke("vitamin c, retinol")
        # Both should produce the same verdict (frozenset key)
        assert result_ab == result_ba

    def test_known_conflict_benzoyl_peroxide_retinol(self):
        result = conflict_checker.invoke("benzoyl peroxide, retinol")
        assert "Verdict:" in result
        assert "do-not-use" in result.lower() or "different" in result.lower()

    def test_unknown_pair_returns_unknown_verdict(self):
        result = conflict_checker.invoke("unknown_ingredient_xyz, retinol")
        assert "unknown_ingredient" in result
        assert "Unknown ingredients:" in result

    def test_wrong_number_of_parts_returns_error(self):
        result = conflict_checker.invoke("retinol")
        assert "Error" in result

    def test_three_ingredients_returns_error(self):
        result = conflict_checker.invoke("retinol, vitamin c, niacinamide")
        assert "Error" in result

    def test_empty_ingredient_a_returns_error(self):
        result = conflict_checker.invoke(", vitamin c")
        assert "Error" in result

    def test_empty_ingredient_b_returns_error(self):
        result = conflict_checker.invoke("retinol, ")
        assert "Error" in result

    def test_whitespace_only_ingredients_error(self):
        result = conflict_checker.invoke("  ,   ")
        assert "Error" in result

    def test_case_insensitive_lookup(self):
        result_lower = conflict_checker.invoke("retinol, aha")
        result_upper = conflict_checker.invoke("RETINOL, AHA")
        assert result_lower == result_upper

    def test_result_contains_unknown_ingredients_list(self):
        result = conflict_checker.invoke("mystery_a, mystery_b")
        assert "Unknown ingredients:" in result
        assert "mystery_a" in result
        assert "mystery_b" in result

    def test_known_pair_unknown_ingredients_empty(self):
        # retinol + aha is in the conflict table, so Unknown ingredients should be []
        result = conflict_checker.invoke("retinol, aha")
        assert "Unknown ingredients: []" in result
