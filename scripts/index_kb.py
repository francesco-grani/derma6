"""Indexing script for the Skincare Routine Builder knowledge base.

Loads all .md files from knowledge_base/ recursively, extracts metadata from
each file's first heading, embeds documents via OpenRouterEmbeddings, and
upserts them into a persistent ChromaDB collection named 'skincare_kb'.

Usage:
    uv run python scripts/index_kb.py
    uv run python scripts/index_kb.py --chroma-dir /tmp/mydb

The script is idempotent: running it multiple times will not create duplicates
because ChromaDB upsert uses the source_file relative path as the document ID.
"""

import argparse
import logging
import sys
from pathlib import Path

import chromadb
from langchain_core.documents import Document

# Ensure the project root is on sys.path so backend imports work when the
# script is executed directly (not as part of an installed package).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.config import settings  # noqa: E402  (after sys.path adjustment)
from backend.rag.embeddings import OpenRouterEmbeddings  # noqa: E402

logger = logging.getLogger(__name__)

KB_DIR = _REPO_ROOT / "knowledge_base"
COLLECTION_NAME = "skincare_kb"


def _extract_source_name(content: str) -> str:
    """Return the text of the first '# ' heading in *content*, or empty string."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _load_documents() -> list[Document]:
    """Discover all .md files under knowledge_base/ and return LangChain Documents."""
    docs: list[Document] = []
    for md_file in sorted(KB_DIR.rglob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        source_name = _extract_source_name(content)
        # topic_category is the immediate subdirectory name under knowledge_base/
        topic_category = md_file.parent.name
        # Use a path relative to the repo root for stable, OS-independent IDs
        relative_path = md_file.relative_to(_REPO_ROOT)
        logger.debug("Loaded: %s (category=%s, source=%r)", relative_path, topic_category, source_name)
        docs.append(
            Document(
                page_content=content,
                metadata={
                    "source_name": source_name,
                    "topic_category": topic_category,
                    "source_file": str(relative_path),
                },
            )
        )
    return docs


def main(chroma_dir: str | None = None) -> None:
    """Run the indexing pipeline.

    Args:
        chroma_dir: Override the ChromaDB persistence directory. When None,
            uses settings.chroma_persist_dir (from .env or environment).
    """
    target_dir = chroma_dir if chroma_dir is not None else settings.chroma_persist_dir

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    # Quieten noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)

    logger.info("Starting knowledge-base indexing")
    logger.info("ChromaDB directory: %s", target_dir)

    # 1. Load documents
    docs = _load_documents()
    if not docs:
        logger.error("No .md files found under %s — nothing to index.", KB_DIR)
        sys.exit(1)
    logger.info("Found %d documents to index", len(docs))

    # 2. Embed all documents in one batch
    embeddings = OpenRouterEmbeddings()
    logger.info("Embedding %d documents via OpenRouter (%s) …", len(docs), settings.embedding_model)
    vectors = embeddings.embed_documents([doc.page_content for doc in docs])
    logger.info("Embedding complete — received %d vectors", len(vectors))

    # 3. Upsert into ChromaDB
    client = chromadb.PersistentClient(path=target_dir)
    collection = client.get_or_create_collection(name=COLLECTION_NAME)

    ids = [doc.metadata["source_file"] for doc in docs]
    documents = [doc.page_content for doc in docs]
    metadatas = [doc.metadata for doc in docs]

    collection.upsert(
        ids=ids,
        embeddings=vectors,
        documents=documents,
        metadatas=metadatas,
    )

    final_count = collection.count()
    logger.info(
        "Indexed %d documents into ChromaDB collection %r (total in collection: %d)",
        len(docs),
        COLLECTION_NAME,
        final_count,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Index the skincare knowledge base into ChromaDB."
    )
    parser.add_argument(
        "--chroma-dir",
        default=None,
        help=(
            "Path to the ChromaDB persistence directory. "
            "Defaults to settings.chroma_persist_dir (CHROMA_PERSIST_DIR env var or ./data/chroma)."
        ),
    )
    args = parser.parse_args()
    main(chroma_dir=args.chroma_dir)
