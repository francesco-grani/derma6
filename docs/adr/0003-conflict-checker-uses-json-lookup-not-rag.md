# ADR-0003: Conflict checker uses a JSON lookup table, not vector search

**Status:** Accepted (ported from v1)  
**Date:** 2026-06-17

## Context

Ingredient conflicts (e.g. Retinol + Salicylic Acid) could theoretically be answered via `kb_search`. The conflict corpus is small and well-defined.

## Decision

The `conflict_checker` tool queries `knowledge_base/conflict_table.json` directly — a hand-curated key→value map. No embeddings are involved.

## Rationale

- **Conflicts are a finite enumerable set** — there is no open-ended retrieval problem; all pairs are known
- **Deterministic** — vector similarity can return a different "most similar" chunk on borderline queries; a conflict check must be binary and reproducible
- **Synonym safety** — vector search can miss a conflict because "retinol" and "vitamin A" are semantically close but not identical in all embeddings; the JSON table maps canonical names, sidestepping this entirely
- **Chunk boundary effects** — a conflict explanation split across two chunks may score below `MIN_SCORE` and be dropped; the lookup table never loses data

The KB documents still explain *why* conflicts exist (mechanism, irritation pathway); `kb_search` handles those explanatory queries. The conflict_checker only answers "do these two ingredients conflict: yes/no/reason".

## Consequences

- New conflicts must be added to `conflict_table.json` manually (not auto-discovered from KB text)
- The table is small (~30 pairs) and easy to maintain
- No re-embedding needed when the conflict table changes — just restart the backend
