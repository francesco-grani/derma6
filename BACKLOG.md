<!-- markdownlint-disable MD036 MD055 MD056 MD058 MD060 -->
# Skincare Routine Builder — Implementation Backlog

> Status: `⬜ pending` · `🔄 in progress` · `✅ done` · `❌ blocked`
> Rule: a task is only ✅ when its tests pass.

---

## Wave 1

| Status | Task | Depends on |
|--------|------|------------|
| ✅ | **T1** · Project structure + config | — |

---

## Wave 2 — parallel after T1

| Status | Task | Depends on |
|--------|------|------------|
| ✅ | **T2** · Logging + Sentry | T1 |
| ✅ | **T3** · ORM models + DB init | T1 |
| ✅ | **T5** · Pydantic schemas | T1 |
| ✅ | **T7** · Rate Limiter | T1 |
| ✅ | **T8** · Retriever + embeddings | T1 |
| ✅ | **T9** · Knowledge Base first drafts | T1 |

---

## Wave 3 — parallel

| Status | Task | Depends on |
|--------|------|------------|
| ✅ | **T4** · Profile Store | T3 |
| ✅ | **T6** · Chat History | T3 |
| ✅ | **T10** · Conflict Table + indexing script | T8 + T9 |

---

## Wave 4 — parallel

| Status | Task | Depends on |
|--------|------|------------|
| ✅ | **T11** · Conflict Checker Tool | T4 + T10 |
| ✅ | **T12** · Routine Sequencer Tool | T8 |
| ✅ | **T13** · Skin Type Advisor Tool | T4 + T8 |
| ✅ | **T14** · SPF Recommender Tool | T8 |
| ✅ | **TA1** · `serialise_history` method | T6 |
| 🔄 | **TB1** · Golden eval dataset | T9 _(waiting on KB finalization)_ |

---

## Wave 5

| Status | Task | Depends on |
|--------|------|------------|
| ✅ | **T15** · Introduction Scheduler Tool | T4 + T8 + T11 |

---

## Wave 6

| Status | Task | Depends on |
|--------|------|------------|
| ✅ | **T16** · BackendService + SystemPromptBuilder | T5 + T6 + T7 + T11 + T12 + T13 + T14 + T15 |

---

## Wave 7 — parallel

| Status | Task | Depends on |
|--------|------|------------|
| ⬜ | **T17** · Input validation | T16 |
| ⬜ | **T19** · Streamlit frontend (3 pages) | T16 |

---

## Wave 8 — parallel

| Status | Task | Depends on |
|--------|------|------------|
| ⬜ | **T18** · Integration tests | T16 + T17 |
| ⬜ | **TA2** · Export download button | TA1 + T19 |
| ⬜ | **TB2** · RAGAs eval script | T16 + TB1 |

---

## Wave 9

| Status | Task | Depends on |
|--------|------|------------|
| ⬜ | **T20** · Medical Flag + domain e2e | T18 + T19 |

---

## Deferred

| Status | Task | Depends on |
|--------|------|------------|
| ⏸️ | **KB-REFINE** · Knowledge Base refinement _(user-led)_ | T20 |

---

_24 automated tasks · Updated in real time as tasks complete_
