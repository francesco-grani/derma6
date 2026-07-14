# Knowledge Base Maintenance

**TL;DR** — the KB is 20 markdown documents in `knowledge_base/`, re-embedded into ChromaDB by `uv run python scripts/index_kb.py` after any edit. There's no separate source-fetching script any more (`enrich_kb.py` was removed) — new/updated documents are written directly. Evaluation of KB retrieval quality now runs through the deepeval suite (`eval/golden_dataset.json`), not the old RAGAs pipeline — see [Evaluation](Evaluation.md).

The Derma6 knowledge base (KB) consists of 20 markdown documents covering skincare actives, ingredient science, and routine principles. They live in `knowledge_base/` and are embedded into ChromaDB.

---

## Directory layout

```
knowledge_base/
├── *.md                # 20 ingredient/topic documents
└── conflict_table.json # deterministic conflict matrix (not embedded)
```

`data/chroma/` — ChromaDB persistence directory (not committed to git, regenerate with `index_kb.py`).

---

## Rebuilding the index

Run after adding or editing any document in `knowledge_base/`:

```bash
uv run python scripts/index_kb.py
```

This drops and rebuilds the ChromaDB collection from scratch. It uses the OpenRouter embeddings model configured in `.env` (`EMBEDDING_MODEL`, default: `qwen/qwen3-embedding-8b`). Each chunk is also tagged with the canonical actives it mentions (`backend/rag/actives.py`) and that list is stored in the chunk's metadata, so the RAG pipeline can boost ingredient-specific matches at rerank time — see [Agentic RAG](Agentic-RAG.md#rerank). Re-run this script after editing the actives vocabulary so existing chunks pick up the new tags.

---

## Adding a new ingredient document

1. Create a markdown file in `knowledge_base/`, e.g. `niacinamide.md`.
2. Structure: `# Title`, then sections for mechanism, skin types, interactions, evidence. Keep under 4000 chars to avoid overly large chunks.
3. Run `uv run python scripts/index_kb.py` to re-embed.
4. Optionally add a `kb-*` case to `eval/golden_dataset.json` covering the new ingredient — see [Adding new test cases](Evaluation.md#adding-new-test-cases) in the Evaluation wiki page.

---

## Updating the conflict table

`knowledge_base/conflict_table.json` is a manually curated JSON object. Keys are canonical ingredient names; values list incompatible ingredients and the reason.

```json
{
  "retinol": {
    "conflicts": ["salicylic_acid", "vitamin_c"],
    "reason": "Combined use increases irritation risk and reduces retinol stability"
  }
}
```

The `conflict_checker` tool loads this file at startup (via `settings.conflict_table_path`). After editing, restart the backend — no re-embedding needed.

---

## Evaluating retrieval quality

The old standalone RAGAs pipeline (`scripts/eval_rag.py`, `eval/eval_dataset.json`) is gone — retrieval quality is now covered by the deepeval suite's "KB — RAG Pipeline" category (8 of the 28 test cases: `ContextualRelevancyMetric`, `ContextualPrecisionMetric`, `ContextualRecallMetric`), which exercises the real agentic RAG pipeline end-to-end rather than a bare retriever. See [Evaluation](Evaluation.md) for how to run it and add cases.

---

## Retrieval tuning

These two variables size the candidate pool going into `hybrid_retrieve` — the first stage of the agentic RAG pipeline, not the whole retrieval story any more (rerank and CRAG narrow it further downstream; see [Agentic RAG](Agentic-RAG.md) for the full pipeline reference and its own config vars).

| Variable | Default | Effect |
|---|---|---|
| `RETRIEVAL_TOP_K` | 4 | Number of chunks returned per query (per dense/sparse branch, before RRF merge) |
| `RETRIEVAL_MIN_SCORE` | 0.3 | Minimum cosine similarity to include a chunk |

Raise `MIN_SCORE` to reduce noise; lower it to catch harder queries. Re-run `capture_outputs.py --ids kb-01,kb-02,kb-03,kb-04 --update-golden` and the KB deepeval cases after any change to verify the trade-off.
