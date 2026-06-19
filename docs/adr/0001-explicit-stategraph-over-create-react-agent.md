# ADR-0001: Explicit StateGraph over create_react_agent

**Status:** Accepted  
**Date:** 2026-06-17

## Context

LangGraph provides two ways to build a ReAct agent: the prebuilt `create_react_agent` helper and a hand-wired `StateGraph`. The helper is faster to write but opaque — it is a black box around a fixed graph topology.

## Decision

Use an explicit `StateGraph` with named `llm_node` and `tool_node` nodes and a `tools_condition` edge.

## Rationale

The planned v2 extensions make the explicit graph necessary:

- **HITL interrupts** — `graph.interrupt_after=["llm_node"]` requires knowing node names
- **Conditional routing** — custom edges between nodes (e.g. skip tool_node for certain query types)
- **Multi-agent topology** — a parent graph that calls specialised sub-graphs as nodes

`create_react_agent` would need to be replaced at that point anyway. Choosing the explicit graph now avoids a disruptive refactor mid-sprint.

The cost is ~30 extra lines of boilerplate vs the helper. This is acceptable.

## Consequences

- Agent construction is more verbose but fully inspectable
- Any future graph change (new node, conditional branch) is straightforward
- The `build_agent(checkpointer=None)` signature is already prepared for `AsyncSqliteSaver` when HITL arrives
