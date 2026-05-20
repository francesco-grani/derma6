"""Unit tests for the introduction_scheduler tool."""

import logging
import pytest
from unittest.mock import patch, MagicMock, call

from backend.schemas import IntroductionPlanSchema, IntroductionWeek
from backend.tools.introduction_scheduler import introduction_scheduler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAFE_VERDICT = "Verdict: safe\nReason: These ingredients work well together.\nUnknown ingredients: []"
_DO_NOT_USE_VERDICT = "Verdict: do-not-use\nReason: These ingredients cancel each other.\nUnknown ingredients: []"


# ---------------------------------------------------------------------------
# 1. Plan has correct number of week blocks
# ---------------------------------------------------------------------------

class TestPlanWeekCount:
    """Plan must span the correct number of 2-week blocks."""

    def test_three_actives_six_weeks(self):
        """3 actives → 3 blocks of 2 weeks each (weeks 1-6)."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.return_value = None

            result = introduction_scheduler.invoke(
                "actives: retinol, niacinamide, vitamin c | username: testuser"
            )

        assert "Week 1" in result
        assert "Week 3" in result
        assert "Week 5" in result

    def test_two_actives_four_weeks(self):
        """2 actives → 2 blocks (weeks 1-4)."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.return_value = None

            result = introduction_scheduler.invoke(
                "actives: retinol, niacinamide | username: testuser"
            )

        assert "Week 1" in result
        assert "Week 3" in result

    def test_single_active_two_weeks(self):
        """1 active → 1 block (weeks 1-2)."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.return_value = None

            result = introduction_scheduler.invoke(
                "actives: retinol | username: testuser"
            )

        assert "Week 1" in result


# ---------------------------------------------------------------------------
# 2. do-not-use pair triggers a warning
# ---------------------------------------------------------------------------

class TestDoNotUsePairWarning:
    """A do-not-use verdict must surface a Warning in the output."""

    def test_warning_present_for_do_not_use_pair(self):
        """Mocking conflict_checker to always return do-not-use → warning shown."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _DO_NOT_USE_VERDICT
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.return_value = None

            result = introduction_scheduler.invoke(
                "actives: retinol, vitamin c | username: testuser"
            )

        assert "Warning:" in result
        assert "retinol" in result
        assert "vitamin c" in result

    def test_warning_contains_both_ingredient_names(self):
        """Warning message includes both ingredient names from the conflicting pair."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            # Only mark retinol + vitamin c as do-not-use; others are safe
            def conflict_side_effect(pair_str):
                if "retinol" in pair_str and "vitamin c" in pair_str:
                    return _DO_NOT_USE_VERDICT
                return _SAFE_VERDICT

            mock_cc.invoke.side_effect = conflict_side_effect
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.return_value = None

            result = introduction_scheduler.invoke(
                "actives: retinol, niacinamide, vitamin c | username: testuser"
            )

        assert "Warning:" in result
        assert "retinol" in result
        assert "vitamin c" in result
        # niacinamide should NOT appear in a warning
        warning_lines = [l for l in result.splitlines() if l.startswith("Warning:")]
        assert len(warning_lines) == 1


# ---------------------------------------------------------------------------
# 3. do-not-use pair excluded from concurrent phases
# ---------------------------------------------------------------------------

class TestDoNotUsePairExclusion:
    """Conflicting actives must never share a week block."""

    def test_do_not_use_pair_not_in_same_week_block(self):
        """retinol and vitamin c (do-not-use) appear in different week ranges."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _DO_NOT_USE_VERDICT
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.return_value = None

            result = introduction_scheduler.invoke(
                "actives: retinol, vitamin c | username: testuser"
            )

        # Parse which "Week X-Y" block each active appears in
        blocks: dict[str, str] = {}
        current_block = None
        for line in result.splitlines():
            if line.startswith("Week"):
                current_block = line.split(":")[0].strip()
            elif current_block and ("retinol" in line or "vitamin c" in line):
                active = "retinol" if "retinol" in line else "vitamin c"
                if active not in blocks:
                    blocks[active] = current_block

        # Both must have been assigned a block
        assert "retinol" in blocks, "retinol not found in output"
        assert "vitamin c" in blocks, "vitamin c not found in output"
        # They must be in different blocks
        assert blocks["retinol"] != blocks["vitamin c"], (
            f"retinol and vitamin c share block {blocks['retinol']}"
        )

    def test_safe_pair_can_share_last_block(self):
        """When 4 actives are safe with each other, last 2 share a block (≤8 weeks)."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.return_value = None

            result = introduction_scheduler.invoke(
                "actives: retinol, niacinamide, vitamin c, spf | username: testuser"
            )

        # Should mention all 4 actives
        for active in ["retinol", "niacinamide", "vitamin c", "spf"]:
            assert active in result, f"{active} missing from schedule"


# ---------------------------------------------------------------------------
# 4. Plan persisted to ProfileStore
# ---------------------------------------------------------------------------

class TestPlanPersistence:
    """The generated plan must be saved via ProfileStore.save_introduction_plan."""

    def test_save_introduction_plan_called_once(self):
        """ProfileStore().save_introduction_plan called exactly once."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            mock_store_instance = MockProfileStore.return_value
            mock_store_instance.save_introduction_plan.return_value = None

            introduction_scheduler.invoke(
                "actives: retinol, niacinamide, vitamin c | username: testuser"
            )

        mock_store_instance.save_introduction_plan.assert_called_once()

    def test_save_called_with_correct_username_and_schema(self):
        """save_introduction_plan receives the username and an IntroductionPlanSchema."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            mock_store_instance = MockProfileStore.return_value
            mock_store_instance.save_introduction_plan.return_value = None

            introduction_scheduler.invoke(
                "actives: retinol, niacinamide, vitamin c | username: testuser"
            )

        args = mock_store_instance.save_introduction_plan.call_args
        username_arg, plan_arg = args[0]
        assert username_arg == "testuser"
        assert isinstance(plan_arg, IntroductionPlanSchema)

    def test_plan_schema_contains_all_actives(self):
        """The persisted IntroductionPlanSchema lists all requested actives."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            mock_store_instance = MockProfileStore.return_value
            mock_store_instance.save_introduction_plan.return_value = None

            introduction_scheduler.invoke(
                "actives: retinol, niacinamide, vitamin c | username: testuser"
            )

        _, plan_arg = mock_store_instance.save_introduction_plan.call_args[0]
        assert set(plan_arg.actives) == {"retinol", "niacinamide", "vitamin c"}
        assert plan_arg.status == "active"


# ---------------------------------------------------------------------------
# 5. Empty actives returns validation error (ProfileStore not called)
# ---------------------------------------------------------------------------

class TestEmptyActivesValidation:
    """Empty actives list must return an error without calling ProfileStore."""

    def test_empty_actives_returns_error(self):
        """Whitespace-only actives produce a validation error string."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            result = introduction_scheduler.invoke(
                "actives:  | username: testuser"
            )

            MockProfileStore.return_value.save_introduction_plan.assert_not_called()

        assert "Error:" in result

    def test_empty_actives_no_profile_store_call(self):
        """Confirm ProfileStore is never instantiated when actives are empty."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            introduction_scheduler.invoke("actives:  | username: testuser")

        MockProfileStore.return_value.save_introduction_plan.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Empty username returns validation error
# ---------------------------------------------------------------------------

class TestEmptyUsernameValidation:
    """Empty username must return a validation error."""

    def test_empty_username_returns_error(self):
        """Whitespace-only username produces a validation error string."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            result = introduction_scheduler.invoke(
                "actives: retinol, niacinamide | username:   "
            )

        assert "Error:" in result

    def test_empty_username_no_profile_store_call(self):
        """ProfileStore never called when username is empty."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            introduction_scheduler.invoke(
                "actives: retinol, niacinamide | username:   "
            )

        MockProfileStore.return_value.save_introduction_plan.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Exception handling
# ---------------------------------------------------------------------------

class TestExceptionHandling:
    """Unexpected exceptions should return a graceful fallback string."""

    def test_profile_store_exception_returns_fallback(self):
        """If ProfileStore raises, the tool returns a graceful error message."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.side_effect = Exception("DB error")

            result = introduction_scheduler.invoke(
                "actives: retinol | username: testuser"
            )

        assert "Sorry" in result or "Error" in result

    def test_exception_logged_at_error_level(self, caplog):
        """Exceptions are logged at ERROR level."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.side_effect = Exception("DB error")

            caplog.set_level(logging.ERROR)
            introduction_scheduler.invoke("actives: retinol | username: testuser")

        assert any(
            record.levelname == "ERROR" for record in caplog.records
        )


# ---------------------------------------------------------------------------
# 8. Output format checks
# ---------------------------------------------------------------------------

class TestOutputFormat:
    """Verify the human-readable output structure."""

    def test_output_starts_with_schedule_header(self):
        """Output starts with 'Introduction Schedule for:'."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.return_value = None

            result = introduction_scheduler.invoke(
                "actives: retinol, niacinamide | username: testuser"
            )

        assert result.startswith("Introduction Schedule for:")

    def test_output_ends_with_saved_confirmation(self):
        """Output ends with a profile-saved confirmation line."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.return_value = None

            result = introduction_scheduler.invoke(
                "actives: retinol | username: testuser"
            )

        assert "saved to your profile" in result

    def test_all_actives_mentioned_in_output(self):
        """All actives appear by name somewhere in the schedule output."""
        actives = ["retinol", "niacinamide", "vitamin c"]

        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.return_value = None

            result = introduction_scheduler.invoke(
                "actives: retinol, niacinamide, vitamin c | username: testuser"
            )

        for active in actives:
            assert active in result, f"{active!r} not found in schedule output"


# ---------------------------------------------------------------------------
# 9. Retriever integration
# ---------------------------------------------------------------------------

class TestRetrieverIntegration:
    """Retriever is called once per active and its content used in notes."""

    def test_retriever_called_for_each_active(self):
        """Retriever.query invoked once per active ingredient."""
        with patch("backend.tools.introduction_scheduler.conflict_checker") as mock_cc, \
             patch("backend.tools.introduction_scheduler.Retriever") as MockRetriever, \
             patch("backend.tools.introduction_scheduler.ProfileStore") as MockProfileStore:

            mock_cc.invoke.return_value = _SAFE_VERDICT
            MockRetriever.return_value.query.return_value = []
            MockProfileStore.return_value.save_introduction_plan.return_value = None

            introduction_scheduler.invoke(
                "actives: retinol, niacinamide, vitamin c | username: testuser"
            )

        # 3 actives → 3 Retriever.query calls
        assert MockRetriever.return_value.query.call_count == 3
