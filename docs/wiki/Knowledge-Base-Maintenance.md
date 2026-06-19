# Knowledge Base Maintenance

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

This drops and rebuilds the ChromaDB collection from scratch. It uses the OpenRouter embeddings model configured in `.env` (`EMBEDDING_MODEL`, default: `qwen/qwen3-embedding-8b`).

---

## Adding a new ingredient document

1. Create a markdown file in `knowledge_base/`, e.g. `niacinamide.md`.
2. Structure: `# Title`, then sections for mechanism, skin types, interactions, evidence. Keep under 4000 chars to avoid overly large chunks.
3. Run `uv run python scripts/index_kb.py` to re-embed.
4. Optionally add Q&A pairs to `eval/eval_dataset.json` to cover the new ingredient in RAGAs eval.

---

## Refreshing sources

Raw fetch data is stored in `data/raw/` (not committed). To regenerate from live sources:

```bash
uv run python scripts/enrich_kb.py   # fetches + normalises sources via LLM
uv run python scripts/index_kb.py    # re-embeds
```

`enrich_kb.py` calls each configured source URL, merges results with an LLM normalisation pass, and writes the final markdown to `knowledge_base/`. API calls are batched; expect ~5–10 min for a full refresh.

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

## Running RAGAs evaluation

```bash
uv run python scripts/eval_rag.py              # agent mode (full e2e)
uv run python scripts/eval_rag.py --retriever  # retriever mode (pipeline only)
```

The golden dataset is `eval/eval_dataset.json` — 15 Q&A pairs covering the KB. Metrics reported: faithfulness, answer relevancy, context precision, context recall.

Add new Q&A pairs to the dataset whenever the KB grows significantly.

---

## Retrieval tuning

| Variable | Default | Effect |
|---|---|---|
| `RETRIEVAL_TOP_K` | 4 | Number of chunks returned per query |
| `RETRIEVAL_MIN_SCORE` | 0.3 | Minimum cosine similarity to include a chunk |

Raise `MIN_SCORE` to reduce noise; lower it to catch harder queries. Run RAGAs eval after any change to verify the trade-off.
