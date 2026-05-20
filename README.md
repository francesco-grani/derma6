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
