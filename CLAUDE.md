# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Turing College AI Engineering Sprint 2. Goal: build a domain-specialized RAG chatbot in 2 weeks.

**Selected project:** Skincare Routine Builder — conversational assistant for diagnosing and optimizing skincare routines, targeting male skincare beginners.

## Tech Stack

- **Backend:** Python
- **Frontend:** Streamlit (first version; only explore a better Python-compatible framework if time allows and with explicit approval)
- **RAG framework:** LangChain + OpenRouter (OpenAI-compatible API)
- **Knowledge base:** keep scoped to 15–20 focused entries (skincare actives, conflict rules, routine sequencing) — fits the 2-week timeline

## Spec Workflow

Follow these phases in strict order. Do not proceed to the next phase without explicit user approval.

1. **Requirements** — EARS format, use `spec-requirements` agent → output to `.claude/specs/`
2. **Design** — architecture, data flow, components, use `spec-design` agent
3. **Tasks** — implementation breakdown with dependency graph, use `spec-tasks` agent
4. **Implementation** — execute tasks, use `spec-impl` agent

Agents live in `.claude/agents/kfc/`. Load `spec-system-prompt-loader` first if the workflow system prompt is not in context.

## Conventions

- Always propose a plan before writing any code.
- Knowledge bases must stay small and scoped (≤20 entries for this sprint).
- Default to Streamlit; only switch frameworks with explicit user approval and a clear justification.
- Keep spec phase gates strict — user sign-off is required before advancing.

## Available Skills

14 Matt Pocock Skills are pinned in `skills-lock.json` and available in `.agents/skills/`: caveman, diagnose, grill-me, grill-with-docs, handoff, improve-codebase-architecture, prototype, setup-matt-pocock-skills, tdd, to-issues, to-prd, triage, write-a-skill, zoom-out.
