#!/usr/bin/env python3
"""Live output capture for the Derma6 eval golden dataset.

Calls each tool directly — no HTTP — patches the profile store with an
in-memory SQLite so nothing is written to the real database, and captures
fresh actual_output + retrieval_context for every case.

Usage:
    python eval/capture_outputs.py                       # dry-run: print to stdout
    python eval/capture_outputs.py --update-golden       # overwrite golden_dataset.json
    python eval/capture_outputs.py --ids spf-01,kb-01   # specific cases only
    python eval/capture_outputs.py --ids kb-01,kb-02,kb-03,kb-04 --update-golden

Run from the project root so backend imports resolve correctly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# ── Path / env setup (must happen before any backend import) ──────────────────

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
if not _key:
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
        load_dotenv(_ROOT / ".env")
        _key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    except ImportError:
        pass

if not _key:
    print("[capture] ERROR: OPENROUTER_API_KEY not found in environment or .env", file=sys.stderr)
    sys.exit(1)

os.environ.setdefault("OPENROUTER_API_KEY", _key)
os.environ.setdefault("OPENAI_API_KEY", _key)

# ── In-memory profile store patch (before tool modules are imported) ──────────

from backend.db.profile_store import ProfileStore  # noqa: E402

_eval_store = ProfileStore(db_url="sqlite:///:memory:")


def _get_eval_store() -> ProfileStore:
    return _eval_store


import backend.db.deps as _deps  # noqa: E402

_deps._profile_store = _eval_store
_deps.get_profile_store = _get_eval_store

# ── Tool imports (after patching) ─────────────────────────────────────────────

import backend.tools.skin_type_advisor as _sta  # noqa: E402
import backend.tools.introduction_scheduler as _intro  # noqa: E402

_sta.get_profile_store = _get_eval_store
_intro.get_profile_store = _get_eval_store

from backend.tools.spf_recommender import spf_recommender  # noqa: E402
from backend.tools.conflict_checker import conflict_checker  # noqa: E402
from backend.tools.routine_sequencer import routine_sequencer  # noqa: E402
from backend.tools.skin_type_advisor import skin_type_advisor  # noqa: E402
from backend.tools.introduction_scheduler import introduction_scheduler  # noqa: E402

# KB search needs the agentic RAG pipeline
from backend.tools.kb_search import _rag_pipeline  # noqa: E402
from backend.rag.pipeline.state import initial_state  # noqa: E402
from backend.config import settings  # noqa: E402

# ── Dataset ───────────────────────────────────────────────────────────────────

_DATASET_PATH = Path(__file__).parent / "golden_dataset.json"


def _load_dataset() -> list[dict[str, Any]]:
    with _DATASET_PATH.open() as f:
        return json.load(f)


# ── Sync tool callers ─────────────────────────────────────────────────────────

def _call_spf(case: dict) -> tuple[str, list[str]]:
    output = spf_recommender.invoke(case["input"])
    return output, []


def _call_conflict(case: dict) -> tuple[str, list[str]]:
    output = conflict_checker.invoke(case["input"])
    return output, []


def _call_routine(case: dict) -> tuple[str, list[str]]:
    output = routine_sequencer.invoke(case["input"])
    return output, []


def _call_skin_type(case: dict) -> tuple[str, list[str]]:
    _eval_store.get_or_create_user("testuser")
    output = skin_type_advisor.invoke(case["input"])
    return output, []


def _call_intro(case: dict) -> tuple[str, list[str]]:
    _eval_store.get_or_create_user("testuser")
    output = introduction_scheduler.invoke(case["input"])
    return output, []


# ── Async KB caller (captures retrieval context from pipeline state) ──────────

async def _call_kb_async(case: dict) -> tuple[str, list[str]]:
    """Run the agentic RAG pipeline and return (result_string, retrieved_chunks)."""
    query = case["input"]
    state = initial_state(query, fallback_strategy=settings.crag_fallback_strategy)
    final_state = await _rag_pipeline._graph.ainvoke(state)

    result_string: str = final_state.get("result_string", "")
    reranked_docs = final_state.get("reranked_docs", [])
    retrieval_context = [doc.content for doc in reranked_docs[:4] if doc.content.strip()]

    return result_string, retrieval_context


def _call_kb(case: dict) -> tuple[str, list[str]]:
    return asyncio.run(_call_kb_async(case))


# ── Tool dispatcher ───────────────────────────────────────────────────────────

_TOOL_CALLERS: dict[str, Any] = {
    "spf_recommender": _call_spf,
    "conflict_checker": _call_conflict,
    "routine_sequencer": _call_routine,
    "skin_type_advisor": _call_skin_type,
    "introduction_scheduler": _call_intro,
    "kb_search": _call_kb,
}


# ── Main capture loop ─────────────────────────────────────────────────────────

def capture(
    dataset: list[dict],
    target_ids: set[str] | None = None,
) -> list[dict]:
    """Return dataset with fresh actual_output and retrieval_context for each case."""
    results: list[dict] = []

    for case in dataset:
        case_id = case["id"]
        tool = case["tool"]

        if target_ids and case_id not in target_ids:
            results.append(case)
            continue

        caller = _TOOL_CALLERS.get(tool)
        if caller is None:
            print(f"[capture] SKIP {case_id}: no caller for tool '{tool}'", file=sys.stderr)
            results.append(case)
            continue

        print(f"[capture] {case_id} ({tool}) ...", end="  ", flush=True, file=sys.stderr)
        t0 = time.perf_counter()
        try:
            actual_output, retrieval_context = caller(case)
            elapsed = time.perf_counter() - t0
            print(f"OK ({elapsed:.1f}s)", file=sys.stderr)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"ERROR ({elapsed:.1f}s): {exc}", file=sys.stderr)
            results.append(case)
            continue

        updated = {**case}
        updated["actual_output"] = actual_output
        if retrieval_context:
            updated["retrieval_context"] = retrieval_context
        results.append(updated)

    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Capture live tool outputs for Derma6 eval.")
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="Overwrite golden_dataset.json with captured outputs.",
    )
    parser.add_argument(
        "--ids",
        type=str,
        default=None,
        help="Comma-separated list of case IDs to capture (default: all).",
    )
    args = parser.parse_args()

    target_ids: set[str] | None = None
    if args.ids:
        target_ids = {s.strip() for s in args.ids.split(",") if s.strip()}
        print(f"[capture] Targeting cases: {sorted(target_ids)}", file=sys.stderr)

    dataset = _load_dataset()
    print(f"[capture] Loaded {len(dataset)} cases from golden_dataset.json", file=sys.stderr)

    updated = capture(dataset, target_ids=target_ids)

    if args.update_golden:
        with _DATASET_PATH.open("w") as f:
            json.dump(updated, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"[capture] Wrote {len(updated)} cases to golden_dataset.json", file=sys.stderr)
    else:
        print(json.dumps(updated, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
