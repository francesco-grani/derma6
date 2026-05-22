"""save_routine tool — persists a sequenced routine to the user's ProfileStore."""

import logging

from langchain_core.tools import tool

from backend.db.profile_store import ProfileStore
from backend.schemas import RoutineSchema, RoutineStepSchema

logger = logging.getLogger(__name__)


@tool
def save_routine(input_str: str) -> str:
    """Save a skincare routine to the user's profile so it appears in Routine Viewer.

    Input format: 'steps: step1, step2, ... | username: <username>'

    Steps should be ingredient or product names in the correct application order,
    e.g. 'steps: cleanser, niacinamide serum, moisturiser, spf | username: John'

    Call this immediately after routine_sequencer produces an ordered routine.
    """
    try:
        # --- Parse input ---
        parts = [p.strip() for p in input_str.split("|")]
        if len(parts) != 2:
            return "Error: Input must be 'steps: ..., ... | username: <username>'"

        steps_raw = username_raw = ""
        for part in parts:
            if part.lower().startswith("steps:"):
                steps_raw = part[len("steps:"):].strip()
            elif part.lower().startswith("username:"):
                username_raw = part[len("username:"):].strip()

        if not steps_raw or not username_raw:
            return "Error: Both 'steps' and 'username' fields are required."

        steps = [s.strip() for s in steps_raw.split(",") if s.strip()]
        username = username_raw.strip()

        if not steps:
            return "Error: No steps provided."

        # --- Build RoutineSchema ---
        step_schemas = [
            RoutineStepSchema(position=i + 1, ingredient=step, product_name=None)
            for i, step in enumerate(steps)
        ]
        routine = RoutineSchema(name="My Routine", steps=step_schemas)

        # --- Persist ---
        store = ProfileStore()
        store.get_or_create_user(username)
        store.save_routine(username, routine)

        logger.info("Routine saved for %s: %d steps", username, len(steps))
        return (
            f"✅ Routine saved to your profile ({len(steps)} steps). "
            "You can view it in the Routine Viewer tab."
        )

    except Exception as e:
        logger.error("save_routine failed: %s", e)
        return "Sorry, I could not save the routine. Please try again."
