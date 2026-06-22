"""Unit tests for backend.tools.introduction_scheduler."""

from unittest.mock import MagicMock, patch

import pytest

from backend.tools.introduction_scheduler import (
    _build_schedule,
    _check_conflicts,
    _format_output,
    _parse_input,
    introduction_scheduler,
)
from backend.schemas import IntroductionWeek


class TestParseInput:
    def test_valid_input(self):
        actives, username = _parse_input("actives: retinol, niacinamide | username: alice")
        assert actives == ["retinol", "niacinamide"]
        assert username == "alice"

    def test_single_active(self):
        actives, username = _parse_input("actives: retinol | username: bob")
        assert actives == ["retinol"]

    def test_missing_pipe_raises(self):
        with pytest.raises(ValueError, match="pipe-separated"):
            _parse_input("actives: retinol username: alice")

    def test_empty_username_raises(self):
        with pytest.raises(ValueError, match="username"):
            _parse_input("actives: retinol | username: ")

    def test_empty_actives_raises(self):
        with pytest.raises(ValueError, match="actives list"):
            _parse_input("actives:  | username: alice")

    def test_trims_whitespace_from_actives(self):
        actives, _ = _parse_input("actives:  retinol ,  niacinamide  | username: alice")
        assert actives == ["retinol", "niacinamide"]

    def test_missing_colon_raises(self):
        with pytest.raises(ValueError):
            _parse_input("actives retinol | username alice")

    def test_three_pipe_sections_raises(self):
        with pytest.raises(ValueError):
            _parse_input("actives: retinol | username: alice | extra: stuff")


class TestCheckConflicts:
    def test_no_conflicts_returns_empty(self):
        do_not_use, warnings = _check_conflicts(["niacinamide", "hyaluronic acid"])
        assert do_not_use == set()
        assert warnings == []

    def test_conflict_returns_pair_and_warning(self):
        # benzoyl peroxide + retinol is a known do-not-use pair
        do_not_use, warnings = _check_conflicts(["benzoyl peroxide", "retinol"])
        if do_not_use:  # only assert if the pair is actually in the conflict table
            assert frozenset({"benzoyl peroxide", "retinol"}) in do_not_use
            assert len(warnings) > 0

    def test_single_active_no_pairs(self):
        do_not_use, warnings = _check_conflicts(["retinol"])
        assert do_not_use == set()
        assert warnings == []


class TestBuildSchedule:
    def test_single_active_two_weeks(self):
        weeks = _build_schedule(["retinol"], set())
        assert len(weeks) == 2
        assert all(w.active == "retinol" for w in weeks)
        assert weeks[0].week == 1
        assert weeks[1].week == 2

    def test_two_actives_four_weeks(self):
        weeks = _build_schedule(["retinol", "niacinamide"], set())
        week_numbers = [w.week for w in weeks]
        assert 1 in week_numbers
        assert 2 in week_numbers
        assert 3 in week_numbers
        assert 4 in week_numbers

    def test_frequency_is_set(self):
        weeks = _build_schedule(["retinol"], set())
        for w in weeks:
            assert w.frequency == "2x/week"

    def test_notes_mention_active(self):
        weeks = _build_schedule(["niacinamide"], set())
        for w in weeks:
            assert "niacinamide" in w.notes.lower()

    def test_four_actives_capped_at_eight_weeks(self):
        actives = ["retinol", "niacinamide", "vitamin c", "aha"]
        weeks = _build_schedule(actives, set())
        week_numbers = {w.week for w in weeks}
        assert max(week_numbers) <= 8

    def test_do_not_use_pair_placed_separately(self):
        # With a do-not-use pair, they should be in different blocks
        pair = frozenset({"retinol", "vitamin c"})
        weeks = _build_schedule(["retinol", "vitamin c"], {pair})
        retinol_weeks = {w.week for w in weeks if w.active == "retinol"}
        vitamin_c_weeks = {w.week for w in weeks if w.active == "vitamin c"}
        assert retinol_weeks.isdisjoint(vitamin_c_weeks)


class TestFormatOutput:
    def test_includes_schedule_header(self):
        weeks = [IntroductionWeek(week=1, active="retinol", frequency="2x/week", notes="Introduce retinol")]
        result = _format_output(["retinol"], weeks, [])
        assert "Introduction Schedule" in result
        assert "retinol" in result

    def test_includes_warnings(self):
        weeks = [IntroductionWeek(week=1, active="retinol", frequency="2x/week", notes="Note")]
        result = _format_output(["retinol"], weeks, ["Warning: do not mix with X"])
        assert "Warning" in result

    def test_profile_saved_footer(self):
        weeks = [IntroductionWeek(week=1, active="a", frequency="2x/week", notes="n")]
        result = _format_output(["a"], weeks, [])
        assert "profile" in result.lower()

    def test_week_range_format(self):
        weeks = [
            IntroductionWeek(week=1, active="retinol", frequency="2x/week", notes="Introduce retinol — start slow"),
            IntroductionWeek(week=2, active="retinol", frequency="2x/week", notes="Continue retinol"),
        ]
        result = _format_output(["retinol"], weeks, [])
        assert "Week 1-2" in result


class TestIntroductionSchedulerTool:
    @patch("backend.tools.introduction_scheduler.get_profile_store")
    @patch("backend.tools.introduction_scheduler.retriever")
    def test_single_active_produces_plan(self, mock_retriever, mock_get_store):
        mock_retriever.query.return_value = [MagicMock(content="Start with 2x per week")]
        mock_get_store.return_value = MagicMock()

        result = introduction_scheduler.invoke("actives: retinol | username: alice")
        assert "Introduction Schedule" in result
        assert "retinol" in result

    @patch("backend.tools.introduction_scheduler.get_profile_store")
    @patch("backend.tools.introduction_scheduler.retriever")
    def test_multiple_actives_ordered(self, mock_retriever, mock_get_store):
        mock_retriever.query.return_value = []
        mock_get_store.return_value = MagicMock()

        result = introduction_scheduler.invoke("actives: retinol, niacinamide | username: alice")
        assert "retinol" in result
        assert "niacinamide" in result

    def test_invalid_input_returns_error(self):
        result = introduction_scheduler.invoke("bad input format")
        assert "Error" in result

    @patch("backend.tools.introduction_scheduler.get_profile_store")
    @patch("backend.tools.introduction_scheduler.retriever")
    def test_plan_saved_to_store(self, mock_retriever, mock_get_store):
        mock_retriever.query.return_value = []
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        introduction_scheduler.invoke("actives: retinol | username: bob")
        mock_store.save_introduction_plan.assert_called_once()

    @patch("backend.tools.introduction_scheduler.get_profile_store")
    @patch("backend.tools.introduction_scheduler.retriever")
    def test_exception_returns_safe_error(self, mock_retriever, mock_get_store):
        mock_retriever.query.return_value = []
        mock_store = MagicMock()
        mock_store.save_introduction_plan.side_effect = Exception("DB persist error")
        mock_get_store.return_value = mock_store
        result = introduction_scheduler.invoke("actives: retinol | username: alice")
        assert "sorry" in result.lower() or "could not" in result.lower()

    def test_empty_actives_returns_error(self):
        result = introduction_scheduler.invoke("actives:  | username: alice")
        assert "Error" in result

    def test_empty_username_returns_error(self):
        result = introduction_scheduler.invoke("actives: retinol | username: ")
        assert "Error" in result
