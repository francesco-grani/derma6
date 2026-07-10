"""Bundle 1 blocking verification spike (capstone-round Task 1).

Confirms — against the LIVE OpenRouter API, not mocks — two things this
capstone round's structured-output work (Requirements 1-3) depends on:

1. Schema-shape conformance: does `settings.vision_model`
   (google/gemini-2.5-flash) actually honor
   `response_format={"type": "json_schema", ..., "strict": True}` and return
   content that conforms to the schema, or does it silently degrade to plain
   text / ignore the constraint?
2. Nested tool-argument reliability: does `settings.llm_model`
   (anthropic/claude-haiku-4.5), via LangChain's `bind_tools()`, reliably
   populate a nested `list[RoutineStepInput]`-shaped tool argument (object
   fields inside a list), or only flat scalar args?

Provider-level *capability* (both models report `response_format`,
`structured_outputs`, `tools`, `tool_choice` in OpenRouter's
`/api/v1/models` `supported_parameters`) was already confirmed and is not
re-checked here — see design.md's "Model capability confirmed against the
models actually in use" note. This script checks *reliability for the
specific schema shapes this round needs*, which `supported_parameters`
does not guarantee.

Usage:
    uv run python scripts/verify_structured_output.py

Requires OPENROUTER_API_KEY (and the rest of backend/config.py's required
settings) to be set, e.g. via .env.

Re-run and re-record findings if `settings.llm_model` or
`settings.vision_model` is ever changed (see the code-comment findings this
script's output feeds into, at the top of backend/llm/structured.py once
Task 2 creates it, and at the save_routine_tool closure site in
backend/agent/graph.py).

FINDINGS (recorded 2026-07-09, live OpenRouter API, 3 consecutive runs):

1. Schema-shape conformance — CONFIRMED for google/gemini-2.5-flash
   (settings.vision_model). `response_format={"type": "json_schema",
   "json_schema": {..., "strict": True}}` is honored: the returned message
   content is valid JSON that fully conforms to the requested schema (all
   required keys present, `probability` correctly nullable) on all 3 runs —
   not silently ignored or degraded to unstructured plain text.

2. Nested tool-argument reliability — CONFIRMED for
   anthropic/claude-haiku-4.5 (settings.llm_model). Via LangChain's
   `bind_tools()`, the model reliably populated a `list[RoutineStepInput]`
   tool argument with correctly nested object fields (`ingredient`,
   `suggested_product`, `budget_product`, including a correctly-omitted
   optional field on one step) on all 3 runs.

CONCLUSION: the nested-object shape (`save_routine_tool(name: str,
steps: list[RoutineStepInput])`) is safe to implement directly in Task 5 —
the flattened-parallel-lists fallback described in design.md is NOT needed
for the currently-configured models.

See .claude/specs/capstone-round/task-1-findings.md for the short note
Task 2/5 should consult, and the mirrored comments this finding was copied
into (backend/agent/graph.py's save_routine_tool closure now; the top of
backend/llm/structured.py once Task 2 creates that module).
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

# Ensure the project root is on sys.path so backend imports work when the
# script is executed directly (not as part of an installed package).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from langchain_core.tools import tool as lc_tool  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from backend.config import settings  # noqa: E402


# ── Part 1: response_format schema-conformance check (settings.vision_model) ──


class _VerifyAlternative(BaseModel):
    condition: str
    probability: Optional[str] = None


class _VerifySkinAnalysis(BaseModel):
    condition: str
    confidence: float
    alternatives: list[_VerifyAlternative]
    reasoning: str


def _strict_schema_dict() -> dict:
    """Hand-rolled OpenAI strict-mode JSON schema mirroring the shape
    `to_strict_json_schema()` (Task 2, not yet implemented) will produce for
    `_VerifySkinAnalysis`: every object gets `additionalProperties: false`,
    every key is listed in `required` (including optional ones), and
    optionality is expressed via `anyOf: [<type>, {"type": "null"}]` rather
    than omission. Duplicated here by hand since backend/llm/structured.py
    does not exist yet — this script only needs to prove the *mechanism*
    works, not reuse the future helper.
    """
    return {
        "type": "object",
        "properties": {
            "condition": {"type": "string"},
            "confidence": {"type": "number"},
            "alternatives": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "condition": {"type": "string"},
                        "probability": {
                            "anyOf": [{"type": "string"}, {"type": "null"}]
                        },
                    },
                    "required": ["condition", "probability"],
                    "additionalProperties": False,
                },
            },
            "reasoning": {"type": "string"},
        },
        "required": ["condition", "confidence", "alternatives", "reasoning"],
        "additionalProperties": False,
    }


async def verify_response_format_schema_conformance() -> bool:
    """Call settings.vision_model with response_format=json_schema/strict and
    assert the returned content actually parses into the schema, proving the
    provider honors the constraint rather than silently ignoring it."""
    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )
    response = await client.chat.completions.create(
        model=settings.vision_model,
        messages=[
            {
                "role": "system",
                "content": "You are a JSON-only test responder for an automated schema-conformance check.",
            },
            {
                "role": "user",
                "content": (
                    "Fabricate a plausible example skin-analysis result for a mild case "
                    "of acne, including exactly two alternative conditions."
                ),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "skin_analysis_result",
                "schema": _strict_schema_dict(),
                "strict": True,
            },
        },
        max_tokens=512,
        temperature=0.1,
    )
    raw = (response.choices[0].message.content or "").strip()
    print(f"[vision_model={settings.vision_model}] raw content:\n{raw}\n")
    try:
        parsed = json.loads(raw)
        _VerifySkinAnalysis(**parsed)
    except Exception as exc:
        print(f"FAIL: response did not conform to the schema: {exc!r}")
        return False
    print("PASS: response_format honored — content conforms to the strict schema.")
    return True


# ── Part 2: nested list[RoutineStepInput] tool-arg reliability (settings.llm_model) ──


class _RoutineStepInput(BaseModel):
    """Mirrors the RoutineStepInput schema Task 5 will add to backend/schemas.py."""

    ingredient: str
    suggested_product: Optional[str] = None
    budget_product: Optional[str] = None


@lc_tool
def _save_routine_tool_probe(name: str, steps: list[_RoutineStepInput]) -> str:
    """Save a named skincare routine.
    name: descriptive routine name, e.g. 'Morning Routine'.
    steps: list of step objects in application order. Each step has an
    'ingredient' (required) and optional 'suggested_product'/'budget_product'."""
    return "ok"  # never actually invoked — bind_tools() only needs the call, not execution


async def verify_nested_tool_arg_reliability() -> bool:
    """Bind a throwaway tool with a list[RoutineStepInput]-typed parameter and
    confirm settings.llm_model populates nested object fields inside the list
    via bind_tools(), not just flat scalar args."""
    llm = ChatOpenAI(
        model=settings.llm_model,
        openai_api_key=settings.openrouter_api_key,
        openai_api_base=settings.openrouter_base_url,
        temperature=0.1,
    )
    bound = llm.bind_tools([_save_routine_tool_probe])
    prompt = (
        "Call the _save_routine_tool_probe tool now to save a routine named "
        "'Morning Routine' with exactly these three steps, in order, as structured "
        "step objects (not a string):\n"
        "1. ingredient='Gentle Cleanser', suggested_product='CeraVe Foaming Cleanser', "
        "budget_product='Neutrogena Oil-Free Wash'\n"
        "2. ingredient='Niacinamide Serum', suggested_product='The Ordinary Niacinamide 10%', "
        "budget_product omitted\n"
        "3. ingredient='Moisturiser', suggested_product='CeraVe Moisturising Lotion', "
        "budget_product='Cetaphil Moisturising Lotion'\n"
        "You MUST call the tool with all three steps in a single call."
    )
    response = await bound.ainvoke(prompt)
    tool_calls = getattr(response, "tool_calls", None) or []
    print(
        f"[llm_model={settings.llm_model}] tool_calls:\n"
        f"{json.dumps(tool_calls, indent=2, default=str)}\n"
    )
    if not tool_calls:
        print("FAIL: model did not call the tool at all.")
        return False

    args = tool_calls[0].get("args", {})
    try:
        steps_raw = args["steps"]
        routine_name = args["name"]
        steps = [_RoutineStepInput(**s) for s in steps_raw]
    except Exception as exc:
        print(f"FAIL: tool args did not match the expected nested shape: {exc!r}")
        return False

    if len(steps) != 3:
        print(f"FAIL: expected 3 steps, got {len(steps)}: {steps}")
        return False
    if not all(s.ingredient for s in steps):
        print(f"FAIL: one or more steps missing 'ingredient': {steps}")
        return False
    if steps[0].suggested_product is None or steps[0].budget_product is None:
        print(f"FAIL: nested product-suggestion fields not populated for step 1: {steps[0]}")
        return False

    print(
        "PASS: nested list[RoutineStepInput] tool argument populated reliably via "
        f"bind_tools(): name={routine_name!r}, steps={steps}"
    )
    return True


async def main() -> None:
    print("=" * 78)
    print("Bundle 1 blocking verification spike — capstone-round Task 1")
    print("=" * 78)
    schema_ok = await verify_response_format_schema_conformance()
    print()
    tool_ok = await verify_nested_tool_arg_reliability()
    print()
    print("=" * 78)
    print(
        f"RESULT: response_format schema conformance "
        f"({settings.vision_model}): {'PASS' if schema_ok else 'FAIL'}"
    )
    print(
        f"RESULT: nested list[RoutineStepInput] tool-arg reliability "
        f"({settings.llm_model}): {'PASS' if tool_ok else 'FAIL'}"
    )
    print("=" * 78)
    if not (schema_ok and tool_ok):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
