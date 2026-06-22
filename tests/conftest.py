"""pytest configuration: environment stubs, chromadb mock, shared fixtures.

Must set env vars and stub chromadb BEFORE any project import so that:
  - backend.config.Settings can be instantiated (OPENROUTER_API_KEY required)
  - backend.tools.kb_search._retriever = Retriever() never opens a real ChromaDB
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

# ── Environment (before any project import) ──────────────────────────────────
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-unit-tests")
os.environ.setdefault("SQLITE_DB_PATH", "/tmp/test_derma6_unit.db")
os.environ.setdefault("CHROMA_PERSIST_DIR", "/tmp/test_chroma_unit")

# ── Stub chromadb so kb_search._retriever = Retriever() never opens a real DB ─
if "chromadb" not in sys.modules:
    _stub = MagicMock()
    _coll = MagicMock()
    _coll.count.return_value = 3  # non-zero → Retriever.query won't raise EmptyCollectionError
    _coll.query.return_value = {
        "documents": [["Retinol boosts cell turnover."]],
        "metadatas": [[{"source_name": "Test Source"}]],
        "distances": [[0.2]],
    }
    _stub.PersistentClient.return_value.get_or_create_collection.return_value = _coll
    sys.modules["chromadb"] = _stub

import pytest

from backend.rag.retriever import RetrievedDoc


# ── Shared sample data ────────────────────────────────────────────────────────

SAMPLE_DOCS = [
    RetrievedDoc(
        content="Retinol is a vitamin A derivative. Apply at night only. Start 2x/week.",
        source_name="Paula's Choice Ingredient Dictionary",
        score=0.88,
    ),
    RetrievedDoc(
        content="SPF 50+ provides broad-spectrum UVA/UVB protection. Apply as the last morning step.",
        source_name="WHO Sun Safety Guidelines",
        score=0.83,
    ),
    RetrievedDoc(
        content=(
            "Oily skin produces excess sebum and appears shiny, especially in the T-zone. "
            "Dry skin feels tight and may be flaky."
        ),
        source_name="American Academy of Dermatology",
        score=0.79,
    ),
]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_docs():
    return list(SAMPLE_DOCS)


@pytest.fixture
def mock_retriever(sample_docs):
    r = MagicMock()
    r.query.return_value = sample_docs
    return r


@pytest.fixture
def empty_retriever():
    r = MagicMock()
    r.query.return_value = []
    return r


@pytest.fixture
def profile_store(tmp_path):
    """ProfileStore backed by a per-test temporary SQLite file."""
    from backend.db.profile_store import ProfileStore

    db = tmp_path / "test.db"
    return ProfileStore(db_url=f"sqlite:///{db}")


# pytest_addoption and pytest_collection_modifyitems live in the root conftest.py
# so they are available when running pytest against any directory.
