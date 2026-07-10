# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Derma6 — AI skincare assistant for male beginners.

## Spec Workflow

Follow these phases in strict order. Do not proceed to the next phase without explicit user approval.

1. **Requirements** — EARS format, use `spec-requirements` agent → output to `.claude/specs/`
2. **Design** — architecture, data flow, components, use `spec-design` agent
3. **Tasks** — implementation breakdown with dependency graph, use `spec-tasks` agent
4. **Implementation** — execute tasks, use `spec-impl` agent

Agents live in `.claude/agents/kfc/`. Load `spec-system-prompt-loader` first if the workflow system prompt is not in context.

## Conventions

- Always propose a plan before writing any code.
- Keep spec phase gates strict — user sign-off is required before advancing.

## Available Skills

Use the `Skill` tool to invoke any of these. Sources: project-local (`.claude/skills/`), global plugin cache (`superpowers`, `frontend-design`), and Matt Pocock set (global cache via `skills-lock.json`). This is a deliberately small core set — other skills exist in the global caches and can still be invoked ad hoc via the `Skill` tool if a genuine need arises, they just aren't standing entries here.

| Skill | When to invoke |
| ----- | -------------- |
| `superpowers:test-driven-development` | Implementing any feature or bugfix |
| `superpowers:systematic-debugging` | Any bug, test failure, or unexpected behaviour |
| `superpowers:verification-before-completion` | Before claiming work is done or creating a PR |
| `superpowers:requesting-code-review` | After completing a feature or before merging |
| `superpowers:receiving-code-review` | Receiving code review feedback before implementing suggestions |
| `superpowers:using-git-worktrees` | Feature work that needs isolation from the current workspace |
| `handoff` | Compact the conversation for another agent to pick up |
