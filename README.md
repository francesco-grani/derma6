# Skincare Routine Builder

Conversational RAG chatbot for male skincare beginners. Diagnoses skin type, builds routines, checks ingredient conflicts, and schedules active introductions — all through a natural chat interface.

## Tech Stack

- **Backend:** Python 3.11+, LangChain, ChromaDB, SQLite
- **Frontend:** Streamlit (3-page app)
- **LLM:** OpenRouter (`openai/gpt-4o-mini`)
- **Embeddings:** OpenRouter (`qwen/qwen3-embedding-8b`)
- **Package manager:** uv

## Setup

```bash
# Install dependencies
uv sync --all-extras

# Copy and fill in your API key
cp .env.example .env
# Edit .env: set OPENROUTER_API_KEY

# Index the knowledge base (first run only)
uv run python scripts/index_kb.py

# Start the app
uv run streamlit run frontend/app.py
```

## Running Tests

```bash
uv run pytest
```

---

## Knowledge Base

The KB lives in `knowledge_base/` (20 markdown documents, capped at 20 per project spec). Each document is embedded whole into ChromaDB — no chunking. Sources for each ingredient are fetched from Paula's Choice, INCI Decoder, PubMed, and Reddit r/SkincareAddiction, then merged into the document by an LLM normalization pass.

Raw fetched data is stored in `data/raw/` (not committed — regenerate with the pipeline below).

### Refresh existing ingredient sources

Re-fetch all sources and re-enrich all KB documents in one command:

```bash
uv run scripts/enrich_kb.py
```

Target a single ingredient to refresh only that document:

```bash
uv run scripts/enrich_kb.py --ingredient retinol
uv run scripts/enrich_kb.py --ingredient niacinamide
```

Available ingredient slugs: `retinol`, `niacinamide`, `vitamin_c`, `aha_guide`, `bha_guide`, `benzoyl_peroxide`, `hyaluronic_acid`, `ceramides`, `peptides`, `azelaic_acid`, `spf_actives`.

### Add a new ingredient

**Step 1 — Check the cap:**

```bash
find knowledge_base -name '*.md' | wc -l   # must be < 20 before adding
```

**Step 2 — Register the ingredient** in `scripts/kb_config.py` (the only file you need to edit):

```python
"adapalene": {
    "display_name": "Adapalene",
    "kb_file": "knowledge_base/ingredients/adapalene.md",
    "pc_url": "https://www.paulaschoice.com/ingredient-dictionary/ingredient-adapalene.html",
    "inci_slugs": ["adapalene"],           # slug(s) from incidecoder.com/ingredients/<slug>
    "pubmed_query": "adapalene topical acne retinoid",
},
```

Set `"pc_url": None` if Paula's Choice has no page for the ingredient.

**Step 3 — Create the KB document** (use any existing doc as a template):

```bash
cp knowledge_base/ingredients/retinol.md knowledge_base/ingredients/adapalene.md
# Edit the copy: update the title, overview, and any known facts
```

**Step 4 — Run the pipeline:**

```bash
uv run scripts/enrich_kb.py --ingredient adapalene
```

This fetches Paula's Choice, INCI Decoder, and PubMed for the new ingredient, enriches the KB document, and re-indexes ChromaDB — all in one step.

The `--new-ingredient` flag prints these steps with the exact config block filled in:

```bash
uv run scripts/enrich_kb.py --new-ingredient adapalene
```

### Batch operations

| Goal | Command |
| ---- | ------- |
| Refresh all sources + re-enrich + re-index | `uv run scripts/enrich_kb.py` |
| Refresh sources only, skip LLM + index | `uv run scripts/enrich_kb.py --fetch-only` |
| Re-enrich from existing raw data, skip re-index | `uv run scripts/enrich_kb.py --skip-index` |
| Re-index only (after manual KB edits) | `uv run python scripts/index_kb.py` |

### Pipeline internals

`enrich_kb.py` orchestrates five scripts in order:

```text
scrape_paulas_choice.py   →  data/raw/paulas_choice/<slug>.txt   (Playwright)
scrape_inci_decoder.py    →  data/raw/inci_decoder/<slug>.txt    (httpx + BeautifulSoup)
fetch_pubmed.py           →  data/raw/pubmed/<slug>.json         (NCBI E-utilities API)
fetch_reddit_wiki.py      →  data/raw/reddit/<sub>__<page>.txt   (Reddit JSON API, full run only)
normalize_kb.py           →  knowledge_base/ingredients/<slug>.md (OpenRouter LLM)
index_kb.py               →  data/chroma/                        (ChromaDB)
```

All ingredient URLs, INCI slugs, and PubMed queries are defined in one place: **`scripts/kb_config.py`**. Adding or changing an ingredient only requires editing that file.
