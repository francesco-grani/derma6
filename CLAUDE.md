# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Turing College AI Engineering Sprint 2. Goal: build a domain-specialized RAG chatbot in 2 weeks.

**Selected project:** Derma6 — conversational assistant for diagnosing and optimizing skincare routines, targeting male skincare beginners.

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

Use the `Skill` tool to invoke any of these. Sources: project-local (`.agents/skills/`), global plugin cache (`superpowers`, `frontend-design`), and Matt Pocock set (global cache via `skills-lock.json`).

### Always-on workflow
| Skill | When to invoke |
| ----- | -------------- |
| `superpowers:using-superpowers` | Session start — establishes skill discovery rules |
| `superpowers:brainstorming` | Before any feature, component, or behaviour change |
| `superpowers:writing-plans` | Before multi-step implementation — turns spec into a plan |
| `superpowers:test-driven-development` | Implementing any feature or bugfix |
| `superpowers:verification-before-completion` | Before claiming work is done or creating a PR |
| `superpowers:requesting-code-review` | After completing a feature or before merging |

### Debugging & architecture
| Skill | When to invoke |
| ----- | -------------- |
| `superpowers:systematic-debugging` | Any bug, test failure, or unexpected behaviour |
| `diagnose` | Hard bugs — full reproduce → minimise → fix loop |
| `improve-codebase-architecture` | Architecture review, refactor opportunities, testability |
| `grill-with-docs` | Stress-test a plan against `CONTEXT.md` and ADRs |

### Planning & design
| Skill | When to invoke |
| ----- | -------------- |
| `grill-me` | Stress-test your own design through relentless questioning |
| `prototype` | Throwaway prototype to validate a design or data model |
| `triage` | Create or triage GitHub issues |
| `to-prd` | Turn conversation context into a PRD |
| `to-issues` | Break a plan into independently-grabbable GitHub issues |

### Execution
| Skill | When to invoke |
| ----- | -------------- |
| `superpowers:executing-plans` | Execute a written plan in a new session with review checkpoints |
| `superpowers:subagent-driven-development` | Execute plans with independent tasks in the current session |
| `superpowers:dispatching-parallel-agents` | 2+ independent tasks with no shared state |
| `superpowers:using-git-worktrees` | Feature work that needs isolation from the current workspace |
| `tdd` | Red-green-refactor TDD loop |

### Frontend & UI
| Skill | When to invoke |
| ----- | -------------- |
| `developing-with-streamlit` | **All** Streamlit work — components, styling, theming, session state, caching, custom HTML/CSS/JS |
| `frontend-design:frontend-design` | Non-Streamlit web components, pages, or apps |

### Handoff & integration
| Skill | When to invoke |
| ----- | -------------- |
| `superpowers:finishing-a-development-branch` | Implementation complete, tests pass — decide how to integrate |
| `superpowers:receiving-code-review` | Receiving code review feedback before implementing suggestions |
| `handoff` | Compact the conversation for another agent to pick up |

### Utilities
| Skill | When to invoke |
| ----- | -------------- |
| `caveman` | Reduce token usage — ultra-compressed communication mode |
| `zoom-out` | Step back and check alignment with the bigger picture |
| `superpowers:writing-skills` | Create or edit skills |
| `write-a-skill` | Alternative skill-authoring workflow |
