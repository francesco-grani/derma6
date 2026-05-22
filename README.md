# Skincare Routine Builder

Conversational RAG chatbot for male skincare beginners. Diagnoses skin type, builds routines, checks ingredient conflicts, and schedules active introductions — all through a natural chat interface.

## Tech Stack

- **Backend:** Python 3.11+, LangChain, ChromaDB, SQLite
- **Frontend:** Streamlit (3-page app)
- **LLM:** OpenRouter (`openai/gpt-4o-mini`)
- **Embeddings:** OpenRouter (`qwen/qwen3-embedding-8b`)
- **Package manager:** uv

## Setup

### Option A — uv (recommended, fastest)

```bash
# Install uv if not already installed
pip install uv

# Install all dependencies (including dev/test)
uv sync --all-extras

# Copy and fill in your API key
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY=<your key>

# Index the knowledge base (first run only)
uv run python scripts/index_kb.py

# Start the app
uv run streamlit run frontend/app.py
```

### Option B — plain pip

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
pip install -e .                 # installs backend/frontend packages

cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY=<your key>

python scripts/index_kb.py
streamlit run frontend/app.py
```

> **macOS Intel (x86_64) note:** `requirements.txt` already pins `chromadb<1.0`, `onnxruntime<=1.23.2`, and `pandas<3.0` to avoid broken native extensions on that platform. No extra steps needed.

## Running Tests

```bash
# uv
uv run pytest

# plain pip (after installing requirements-dev.txt)
pip install -r requirements-dev.txt
pytest
```

---

## Knowledge Base

The KB lives in `knowledge_base/` (20 markdown documents, capped at 20 per project spec). Each document is embedded whole into ChromaDB — no chunking. Sources for each ingredient are fetched from Paula's Choice, INCI Decoder, PubMed, and Reddit r/SkincareAddiction, then merged into the document by an LLM normalization pass.

Raw fetched data is stored in `data/raw/` (not committed — regenerate any time with `uv run scripts/enrich_kb.py`).

See the [Knowledge Base Maintenance](https://github.com/TuringCollegeSubmissions/fgrani-AE.2.5/wiki/Knowledge-Base-Maintenance) wiki page for how to refresh sources, add new ingredients, and run the pipeline in batch.
