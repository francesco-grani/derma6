"""Unit tests for backend.rag.actives — the canonical actives matcher."""

import pytest

from backend.rag.actives import (
    CANONICAL_ACTIVES,
    extract_actives,
    parse_actives,
    serialize_actives,
)


class TestExtractActives:
    def test_empty_input(self):
        assert extract_actives("") == set()
        assert extract_actives(None) == set()

    def test_no_actives(self):
        assert extract_actives("A gentle cleanser for dry skin in winter.") == set()

    def test_canonical_name(self):
        assert extract_actives("Apply retinol at night.") == {"retinol"}

    def test_case_insensitive(self):
        assert extract_actives("RETINOL and Niacinamide") == {"retinol", "niacinamide"}

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("retinaldehyde is a retinoid", "retinol"),
            ("tretinoin cream", "retinol"),
            ("a vitamin A derivative", "retinol"),
            ("L-ascorbic acid serum", "vitamin c"),
            ("magnesium ascorbyl phosphate", "vitamin c"),
            ("nicotinamide (vitamin B3)", "niacinamide"),
            ("glycolic acid peel", "aha"),
            ("lactic acid toner", "aha"),
            ("salicylic acid cleanser", "bha"),
            ("BPO spot treatment", "benzoyl peroxide"),
            ("sodium hyaluronate", "hyaluronic acid"),
            ("zinc oxide sunscreen", "spf"),
        ],
    )
    def test_aliases_map_to_canonical(self, text, expected):
        assert extract_actives(text) == {expected}

    def test_multiple_actives(self):
        text = "Layer niacinamide before retinol, and use salicylic acid on off nights."
        assert extract_actives(text) == {"niacinamide", "retinol", "bha"}

    def test_word_boundary_avoids_substrings(self):
        # "aha" must not fire inside "Bahamas"; "spf" not inside a random token.
        assert extract_actives("A trip to the Bahamas.") == set()

    def test_all_canonical_names_are_self_matching(self):
        # Every canonical active should be extractable from its own name.
        for name in CANONICAL_ACTIVES:
            assert name in extract_actives(name), name


class TestSerialization:
    def test_round_trip(self):
        actives = {"retinol", "niacinamide", "bha"}
        assert parse_actives(serialize_actives(actives)) == actives

    def test_serialize_is_sorted_and_deterministic(self):
        assert serialize_actives({"retinol", "aha"}) == "aha,retinol"
        assert serialize_actives({"aha", "retinol"}) == "aha,retinol"

    def test_empty(self):
        assert serialize_actives(set()) == ""
        assert parse_actives("") == set()
        assert parse_actives(None) == set()
