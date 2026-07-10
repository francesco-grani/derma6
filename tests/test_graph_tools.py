"""Unit tests for the typed profile-writing tool closures in backend.agent.graph.

Covers:
- `save_routine_tool` retyped to `(name: str, steps: list[RoutineStepInput])`
  (capstone-round Task 5, Req 2.1-2.5): args-schema shape, ToolNode-level rejection
  of an invalid step before the closure body runs, and persistence-fidelity against
  the prior string-based mechanism's output shape.
- `skin_type_advisor_tool` retyped to `(skin_type: Literal[...])` and
  `update_skin_concerns_tool` retyped to `(concerns: list[str])` (capstone-round
  Task 6, Req 3.1-3.2, 3.4-3.5): args-schema shape, ToolNode-level rejection of an
  out-of-set skin_type before the closure body runs, and absence of manual
  comma-splitting/case-normalization/default-fallback workarounds.

No live LLM call is involved anywhere in this file.
"""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage
from langgraph.graph import MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from backend.agent.graph import _make_tools


def _get_tool(store, name: str, user_id: str = "alice"):
    tools = _make_tools(user_id, store)
    return next(t for t in tools if t.name == name)


def _get_save_routine_tool(store):
    return _get_tool(store, "save_routine_tool")


# ── args_schema shape (Req 2.1, 2.2) ────────────────────────────────────────────


class TestSaveRoutineToolArgsSchema:
    def test_reflects_typed_nested_shape(self):
        save_routine_tool = _get_save_routine_tool(MagicMock())
        schema = save_routine_tool.args_schema.model_json_schema()

        # Top-level: name + steps, no more string-based `suggestions` argument.
        assert set(schema["properties"].keys()) == {"name", "steps"}
        assert "suggestions" not in schema["properties"]
        assert schema["properties"]["steps"]["type"] == "array"

        # steps items reference the nested RoutineStepInput object schema.
        step_ref = schema["properties"]["steps"]["items"]["$ref"]
        step_def_name = step_ref.rsplit("/", 1)[-1]
        step_schema = schema["$defs"][step_def_name]

        assert step_schema["required"] == ["ingredient"]
        assert set(step_schema["properties"].keys()) == {
            "ingredient",
            "suggested_product",
            "budget_product",
        }

    def test_optional_step_fields_are_nullable_not_required(self):
        save_routine_tool = _get_save_routine_tool(MagicMock())
        schema = save_routine_tool.args_schema.model_json_schema()
        step_ref = schema["properties"]["steps"]["items"]["$ref"]
        step_def_name = step_ref.rsplit("/", 1)[-1]
        step_schema = schema["$defs"][step_def_name]

        assert "suggested_product" not in step_schema["required"]
        assert "budget_product" not in step_schema["required"]


# ── ToolNode-level rejection before the closure body runs (Req 2.4) ────────────


class TestSaveRoutineToolValidation:
    def test_step_missing_ingredient_rejected_before_closure_runs(self):
        mock_store = MagicMock()
        save_routine_tool = _get_save_routine_tool(mock_store)

        node = ToolNode([save_routine_tool])
        graph = StateGraph(MessagesState)
        graph.add_node("tools", node)
        graph.set_entry_point("tools")
        graph.set_finish_point("tools")
        compiled = graph.compile()

        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "tc1",
                    "name": "save_routine_tool",
                    "args": {
                        "name": "Morning Routine",
                        "steps": [{"suggested_product": "CeraVe Foaming"}],
                    },
                }
            ],
        )
        result = compiled.invoke({"messages": [ai_msg]})
        tool_message = result["messages"][-1]

        assert tool_message.status == "error"
        assert "ingredient" in tool_message.content
        # The closure body never ran — no store interaction of any kind.
        mock_store.get_routine.assert_not_called()
        mock_store.save_routine.assert_not_called()

    def test_valid_step_shape_accepted_by_args_schema(self):
        # A step with only the required field validates cleanly (no exception raised).
        save_routine_tool = _get_save_routine_tool(MagicMock())
        parsed = save_routine_tool.args_schema(
            name="Morning Routine", steps=[{"ingredient": "Cleanser"}]
        )
        assert parsed.steps[0].ingredient == "Cleanser"
        assert parsed.steps[0].suggested_product is None
        assert parsed.steps[0].budget_product is None


# ── Persistence fidelity vs. the prior string-based mechanism (Req 2.5) ────────


class TestSaveRoutineToolPersistenceFidelity:
    def test_typed_steps_persist_equivalent_routine_to_prior_string_mechanism(self):
        # Prior mechanism: steps="Cleanser,Niacinamide Serum,Moisturiser,SPF",
        # suggestions='{"cleanser": {"suggested": "CeraVe Foaming", "budget": "Neutrogena OFW"}}'
        # produced a RoutineSchema with 4 positionally-ordered steps, only the first
        # carrying product_name/budget_product. The typed shape must reproduce the
        # same content and fidelity.
        mock_store = MagicMock()
        mock_store.get_routine.return_value = None
        save_routine_tool = _get_save_routine_tool(mock_store)

        with patch(
            "backend.agent.graph.interrupt",
            return_value={"choice": "save_new", "note": ""},
        ):
            result = save_routine_tool.invoke(
                {
                    "name": "Morning Routine",
                    "steps": [
                        {
                            "ingredient": "Cleanser",
                            "suggested_product": "CeraVe Foaming",
                            "budget_product": "Neutrogena OFW",
                        },
                        {"ingredient": "Niacinamide Serum"},
                        {"ingredient": "Moisturiser"},
                        {"ingredient": "SPF"},
                    ],
                }
            )

        assert mock_store.save_routine.called
        saved_user_id, saved_routine = mock_store.save_routine.call_args[0]
        assert saved_user_id == "alice"
        assert saved_routine.name == "Morning Routine"

        assert [s.ingredient for s in saved_routine.steps] == [
            "Cleanser",
            "Niacinamide Serum",
            "Moisturiser",
            "SPF",
        ]
        assert [s.position for s in saved_routine.steps] == [1, 2, 3, 4]
        assert saved_routine.steps[0].product_name == "CeraVe Foaming"
        assert saved_routine.steps[0].budget_product == "Neutrogena OFW"
        assert saved_routine.steps[1].product_name is None
        assert saved_routine.steps[1].budget_product is None
        assert "saved" in result.lower()

    def test_cancel_choice_does_not_persist(self):
        mock_store = MagicMock()
        mock_store.get_routine.return_value = None
        save_routine_tool = _get_save_routine_tool(mock_store)

        with patch(
            "backend.agent.graph.interrupt", return_value={"choice": "cancel", "note": ""}
        ):
            result = save_routine_tool.invoke(
                {"name": "Morning Routine", "steps": [{"ingredient": "Cleanser"}]}
            )

        mock_store.save_routine.assert_not_called()
        assert "cancelled" in result.lower()

    def test_empty_steps_list_returns_error_without_interrupt(self):
        mock_store = MagicMock()
        save_routine_tool = _get_save_routine_tool(mock_store)

        with patch("backend.agent.graph.interrupt") as mock_interrupt:
            result = save_routine_tool.invoke({"name": "Morning Routine", "steps": []})

        mock_interrupt.assert_not_called()
        mock_store.save_routine.assert_not_called()
        assert "no steps" in result.lower()


# ── skin_type_advisor_tool: Literal-typed skin_type (Req 3.1, 3.4, 3.5) ─────────


class TestSkinTypeAdvisorToolArgsSchema:
    def test_args_schema_constrains_skin_type_to_enum(self):
        skin_type_advisor_tool = _get_tool(MagicMock(), "skin_type_advisor_tool")
        schema = skin_type_advisor_tool.args_schema.model_json_schema()

        assert set(schema["properties"].keys()) == {"skin_type"}
        # A Literal[...] field is rendered as an enum constraint in the JSON schema.
        skin_type_prop = schema["properties"]["skin_type"]
        allowed = skin_type_prop.get("enum")
        assert allowed is not None
        assert set(allowed) == {
            "oily",
            "dry",
            "combination",
            "sensitive",
            "dehydrated",
            "acneic",
        }


class TestSkinTypeAdvisorToolValidation:
    def test_out_of_set_skin_type_rejected_before_closure_runs(self):
        mock_store = MagicMock()
        skin_type_advisor_tool = _get_tool(mock_store, "skin_type_advisor_tool")

        node = ToolNode([skin_type_advisor_tool])
        graph = StateGraph(MessagesState)
        graph.add_node("tools", node)
        graph.set_entry_point("tools")
        graph.set_finish_point("tools")
        compiled = graph.compile()

        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "tc1",
                    "name": "skin_type_advisor_tool",
                    "args": {"skin_type": "greasy"},
                }
            ],
        )
        result = compiled.invoke({"messages": [ai_msg]})
        tool_message = result["messages"][-1]

        assert tool_message.status == "error"
        # The closure body never ran — no fallback-to-"combination" store write.
        mock_store.update_skin_type.assert_not_called()

    def test_valid_skin_type_persists_without_normalization_or_fallback(self):
        mock_store = MagicMock()
        skin_type_advisor_tool = _get_tool(mock_store, "skin_type_advisor_tool")

        result = skin_type_advisor_tool.invoke({"skin_type": "dehydrated"})

        mock_store.update_skin_type.assert_called_once_with("alice", "dehydrated")
        assert "dehydrated" in result.lower()

    def test_no_strip_lower_or_default_fallback_remains_in_source(self):
        # Req 3.5: no manual `.strip().lower()` normalization or implicit
        # "combination" default-on-invalid fallback in the retyped closure.
        import inspect

        import backend.agent.graph as graph_module

        source = inspect.getsource(graph_module._make_tools)
        skin_type_section = source.split("def skin_type_advisor_tool")[1].split(
            "def save_routine_tool"
        )[0]
        assert ".strip().lower()" not in skin_type_section
        assert 'skin_type = "combination"' not in skin_type_section


# ── update_skin_concerns_tool: list[str]-typed concerns (Req 3.2, 3.5) ─────────


class TestUpdateSkinConcernsToolArgsSchema:
    def test_args_schema_reflects_typed_list_shape(self):
        update_skin_concerns_tool = _get_tool(MagicMock(), "update_skin_concerns_tool")
        schema = update_skin_concerns_tool.args_schema.model_json_schema()

        assert set(schema["properties"].keys()) == {"concerns"}
        assert schema["properties"]["concerns"]["type"] == "array"
        assert schema["properties"]["concerns"]["items"]["type"] == "string"


class TestUpdateSkinConcernsToolBehavior:
    def test_typed_list_persists_without_comma_splitting(self):
        mock_store = MagicMock()
        update_skin_concerns_tool = _get_tool(mock_store, "update_skin_concerns_tool")

        result = update_skin_concerns_tool.invoke(
            {"concerns": ["acne", "dark spots", "dryness"]}
        )

        mock_store.update_skin_concerns.assert_called_once_with(
            "alice", ["acne", "dark spots", "dryness"]
        )
        assert "acne" in result
        assert "dark spots" in result
        assert "dryness" in result

    def test_empty_list_returns_error_without_store_call(self):
        mock_store = MagicMock()
        update_skin_concerns_tool = _get_tool(mock_store, "update_skin_concerns_tool")

        result = update_skin_concerns_tool.invoke({"concerns": []})

        mock_store.update_skin_concerns.assert_not_called()
        assert "at least one concern" in result.lower()

    def test_no_comma_split_remains_in_source(self):
        # Req 3.5: no manual `concerns.split(",")` parsing in the retyped closure.
        import inspect

        import backend.agent.graph as graph_module

        source = inspect.getsource(graph_module._make_tools)
        concerns_section = source.split("def update_skin_concerns_tool")[1].split(
            "def update_beard_style_tool"
        )[0]
        assert ".split(\",\")" not in concerns_section


# ── introduction_scheduler_tool: list[str]-typed actives (Req 3.3, 3.5) ────────


class TestIntroductionSchedulerToolArgsSchema:
    def test_args_schema_reflects_typed_list_shape(self):
        introduction_scheduler_tool = _get_tool(MagicMock(), "introduction_scheduler_tool")
        schema = introduction_scheduler_tool.args_schema.model_json_schema()

        assert set(schema["properties"].keys()) == {"actives"}
        assert schema["properties"]["actives"]["type"] == "array"
        assert schema["properties"]["actives"]["items"]["type"] == "string"


class TestIntroductionSchedulerToolBehavior:
    def test_typed_list_builds_plan_and_persists_without_pipe_string_roundtrip(self):
        mock_store = MagicMock()
        introduction_scheduler_tool = _get_tool(mock_store, "introduction_scheduler_tool")

        fake_plan = MagicMock()
        with patch(
            "backend.agent.graph.build_introduction_plan",
            return_value=(fake_plan, "Introduction Schedule for: retinol"),
        ) as mock_build:
            result = introduction_scheduler_tool.invoke(
                {"actives": ["retinol", "niacinamide"]}
            )

        mock_build.assert_called_once_with(["retinol", "niacinamide"])
        mock_store.save_introduction_plan.assert_called_once_with("alice", fake_plan)
        assert "Introduction Schedule" in result

    def test_empty_actives_list_returns_error_without_build_or_persist(self):
        mock_store = MagicMock()
        introduction_scheduler_tool = _get_tool(mock_store, "introduction_scheduler_tool")

        with patch("backend.agent.graph.build_introduction_plan") as mock_build:
            result = introduction_scheduler_tool.invoke({"actives": []})

        mock_build.assert_not_called()
        mock_store.save_introduction_plan.assert_not_called()
        assert "error" in result.lower()

    def test_persistence_failure_returns_safe_error(self):
        mock_store = MagicMock()
        mock_store.save_introduction_plan.side_effect = Exception("DB persist error")
        introduction_scheduler_tool = _get_tool(mock_store, "introduction_scheduler_tool")

        with patch(
            "backend.agent.graph.build_introduction_plan",
            return_value=(MagicMock(), "formatted plan text"),
        ):
            result = introduction_scheduler_tool.invoke({"actives": ["retinol"]})

        assert "sorry" in result.lower() or "could not" in result.lower()

    def test_no_pipe_string_roundtrip_or_manual_parsing_remains_in_source(self):
        # Req 3.5: the live closure no longer round-trips through the pipe-string
        # `introduction_scheduler.invoke(...)` / `_parse_input()` path.
        import inspect

        import backend.agent.graph as graph_module

        source = inspect.getsource(graph_module._make_tools)
        scheduler_section = source.split("def introduction_scheduler_tool")[1].split(
            "def update_skin_concerns_tool"
        )[0]
        assert "actives: {actives} | username:" not in scheduler_section
        assert "introduction_scheduler.invoke" not in scheduler_section
