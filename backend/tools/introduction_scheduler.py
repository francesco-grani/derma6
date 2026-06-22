"""Introduction scheduler tool for phased skincare active introduction planning."""

import logging
from itertools import combinations

from langchain_core.tools import tool

from backend.db.deps import get_profile_store
from backend.schemas import IntroductionPlanSchema, IntroductionWeek
from backend.tools.conflict_checker import conflict_checker
from backend.tools.kb_search import retriever

logger = logging.getLogger(__name__)


def _parse_input(input_str: str) -> tuple[list[str], str]:
    """Parse pipe-separated input string into (actives list, username).

    Args:
        input_str: Format "actives: a1, a2, ... | username: <name>"

    Returns:
        Tuple of (actives list, username string).

    Raises:
        ValueError: If parsing fails or required fields are missing/empty.
    """
    parts = input_str.split("|")
    if len(parts) != 2:
        raise ValueError(
            "Input must contain exactly two pipe-separated sections: "
            "'actives: ...' and 'username: ...'"
        )

    actives_part, username_part = parts

    if ":" not in actives_part or ":" not in username_part:
        raise ValueError("Both 'actives:' and 'username:' keys are required.")

    actives_raw = actives_part.split(":", 1)[1].strip()
    username = username_part.split(":", 1)[1].strip()

    if not username:
        raise ValueError("username must be non-empty.")

    actives = [a.strip() for a in actives_raw.split(",") if a.strip()]
    if not actives:
        raise ValueError("actives list must be non-empty.")

    return actives, username


def _check_conflicts(actives: list[str]) -> tuple[set[frozenset], list[str]]:
    """Check all pairs for do-not-use conflicts.

    Args:
        actives: List of active ingredient names.

    Returns:
        Tuple of (do_not_use_pairs set, warnings list).
    """
    do_not_use_pairs: set[frozenset] = set()
    warnings: list[str] = []

    for a, b in combinations(actives, 2):
        result = conflict_checker.invoke(f"{a}, {b}")
        if "do-not-use" in result:
            pair = frozenset({a, b})
            do_not_use_pairs.add(pair)
            warnings.append(
                f"Warning: {a} and {b} should not be used together — "
                f"excluded from concurrent weeks."
            )
            logger.warning("do-not-use conflict detected: %s + %s", a, b)

    return do_not_use_pairs, warnings


def _get_active_note(active: str) -> str:
    """Fetch introduction-rate guidance from the knowledge base.

    Args:
        active: Ingredient name to query.

    Returns:
        A guidance string — either from KB or a generic fallback.
    """
    try:
        results = retriever.query(f"{active} introduction rate how to use")
        if results:
            # Use the first retrieved document content as guidance
            return results[0].content[:200].replace("\n", " ")
    except Exception as exc:
        logger.warning("Retriever query failed for %r: %s", active, exc)

    return f"Use 2x/week initially. Patch test on a small area first."


def _build_schedule(
    actives: list[str], do_not_use_pairs: set[frozenset]
) -> list[IntroductionWeek]:
    """Build a phased introduction schedule.

    Each active gets a 2-week block. If 4+ actives would exceed 8 weeks,
    the last block can accommodate two actives that are not in a do-not-use pair.

    Args:
        actives: Ordered list of actives to schedule.
        do_not_use_pairs: Set of frozensets identifying forbidden concurrent pairs.

    Returns:
        List of IntroductionWeek objects.
    """
    weeks: list[IntroductionWeek] = []

    # Fetch notes for every active up front
    active_notes: dict[str, str] = {a: _get_active_note(a) for a in actives}

    # Assign actives to 2-week blocks
    # Each block occupies week numbers (block_index * 2 + 1) and (block_index * 2 + 2)
    blocks: list[list[str]] = []  # list of [active, ...] per block

    remaining = list(actives)

    while remaining:
        active = remaining.pop(0)
        placed = False

        # If we already have 3 blocks (6 weeks) and there are still actives left,
        # try to fit the current active into the last block (cap at 8 weeks = 4 blocks).
        if len(blocks) >= 3 and remaining is not None:
            last_block = blocks[-1]
            # Check that this active doesn't conflict with anything in the last block
            can_share = all(
                frozenset({active, existing}) not in do_not_use_pairs
                for existing in last_block
            )
            if can_share and len(last_block) < 2:
                last_block.append(active)
                placed = True

        if not placed:
            blocks.append([active])

    # Convert blocks to IntroductionWeek objects (two weeks per block)
    for block_idx, block_actives in enumerate(blocks):
        start_week = block_idx * 2 + 1
        end_week = start_week + 1

        for active in block_actives:
            note = active_notes[active]
            # Week N entry
            weeks.append(
                IntroductionWeek(
                    week=start_week,
                    active=active,
                    frequency="2x/week",
                    notes=f"Introduce {active} — {note}",
                )
            )
            # Week N+1 entry (continuation)
            weeks.append(
                IntroductionWeek(
                    week=end_week,
                    active=active,
                    frequency="2x/week",
                    notes=f"Continue {active} — monitor for irritation before adding next active.",
                )
            )

    return weeks


def _format_output(
    actives: list[str],
    weeks: list[IntroductionWeek],
    warnings: list[str],
) -> str:
    """Format the week-by-week plan into a human-readable string.

    Args:
        actives: Full list of actives in the plan.
        weeks: Ordered IntroductionWeek objects.
        warnings: Any conflict warnings to surface.

    Returns:
        Formatted string ready for the user.
    """
    lines: list[str] = []
    lines.append(f"Introduction Schedule for: {', '.join(actives)}")
    lines.append("")

    if warnings:
        for w in warnings:
            lines.append(w)
        lines.append("")

    # Group by week number to print neatly
    week_map: dict[int, list[IntroductionWeek]] = {}
    for week in weeks:
        week_map.setdefault(week.week, []).append(week)

    # Pair consecutive weeks (1-2, 3-4, …) into blocks
    all_week_numbers = sorted(week_map.keys())
    printed_weeks: set[int] = set()

    for wn in all_week_numbers:
        if wn in printed_weeks:
            continue
        next_wn = wn + 1
        block_entries = week_map.get(wn, [])
        next_entries = week_map.get(next_wn, [])

        # Print the first week of each 2-week block
        for entry in block_entries:
            lines.append(f"Week {wn}-{next_wn}: Introduce {entry.active}")
            lines.append(f"  → {entry.notes}")
            lines.append("")

        printed_weeks.add(wn)
        printed_weeks.add(next_wn)

    lines.append("Your introduction plan has been saved to your profile.")
    return "\n".join(lines)


@tool
def introduction_scheduler(input_str: str) -> str:
    """Generate a phased introduction schedule for new skincare actives.

    Input format: 'actives: active1, active2, ... | username: <username>'

    Returns:
        A formatted week-by-week introduction plan with any conflict warnings.
    """
    try:
        # 1. Parse input
        actives, username = _parse_input(input_str)

        # 2. Check all pairs for do-not-use conflicts
        do_not_use_pairs, warnings = _check_conflicts(actives)

        # 3. Build the phased schedule
        weeks = _build_schedule(actives, do_not_use_pairs)

        # 4. Construct the schema object
        plan = IntroductionPlanSchema(
            actives=actives,
            weeks=weeks,
            status="active",
        )

        # 5. Persist to ProfileStore
        get_profile_store().save_introduction_plan(username, plan)

        # 6. Format and return
        result = _format_output(actives, weeks, warnings)
        logger.info(
            "introduction_scheduler succeeded for user %r: %d actives, %d weeks",
            username,
            len(actives),
            len(weeks),
        )
        return result

    except ValueError as exc:
        logger.error("introduction_scheduler validation error: %s", exc)
        return f"Error: {exc}"
    except Exception as exc:
        logger.error("introduction_scheduler failed: %s", exc)
        return (
            "Sorry, I could not generate your introduction schedule. "
            "Please try again or contact support."
        )
