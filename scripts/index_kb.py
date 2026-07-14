"""Indexing script for the Derma6 knowledge base.

Loads all .md files from knowledge_base/ recursively, splits them into
overlapping chunks, embeds each chunk via OpenRouterEmbeddings, and upserts
them into a persistent ChromaDB collection named 'skincare_kb'.

Chunking ensures that only the relevant portion of a document is returned
per query, keeping retrieved context tight and reducing LLM hallucination.

Usage:
    uv run python scripts/index_kb.py
    uv run python scripts/index_kb.py --chroma-dir /tmp/mydb
    uv run python scripts/index_kb.py --reset   # drop + rebuild collection

The script is idempotent without --reset: upsert uses
"{source_file}::chunk_{i}" as the document ID, so re-running only refreshes
existing chunks and adds new ones. Use --reset when migrating from a
whole-document index to avoid stale entries.
"""

import argparse
import logging
import sys
from pathlib import Path

import chromadb
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Ensure the project root is on sys.path so backend imports work when the
# script is executed directly (not as part of an installed package).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.config import settings  # noqa: E402  (after sys.path adjustment)
from backend.rag.actives import extract_actives, serialize_actives  # noqa: E402
from backend.rag.embeddings import OpenRouterEmbeddings  # noqa: E402

logger = logging.getLogger(__name__)

KB_DIR = _REPO_ROOT / "knowledge_base"
COLLECTION_NAME = "skincare_kb"

# ~125 tokens at ~4 chars/token. Tighter chunks keep retrieved context on-topic
# (a 1000-char chunk drags in tangential detail that tanks contextual relevancy);
# the overlap retains cross-boundary context.
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80


def _extract_source_name(content: str) -> str:
    """Return the text of the first '# ' heading in *content*, or empty string."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _load_documents() -> list[Document]:
    """Discover all .md files under knowledge_base/ and return chunked LangChain Documents.

    Each file is split into overlapping chunks using markdown-aware separators.
    Every chunk carries the parent document's source_name, topic_category, and
    source_file, plus a zero-based chunk_index for stable ChromaDB IDs.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n## ", "\n### ", "\n\n", "\n", " "],
    )

    docs: list[Document] = []
    for md_file in sorted(KB_DIR.rglob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        source_name = _extract_source_name(content)
        topic_category = md_file.parent.name
        relative_path = md_file.relative_to(_REPO_ROOT)

        chunks = splitter.split_text(content)
        logger.debug(
            "Chunked: %s → %d chunks (category=%s, source=%r)",
            relative_path, len(chunks), topic_category, source_name,
        )
        for i, chunk in enumerate(chunks):
            # Tag each chunk with the canonical actives it mentions so retrieval
            # can softly boost chunks whose actives overlap the query's. Stored
            # as a comma-joined scalar because ChromaDB metadata cannot hold lists.
            actives = serialize_actives(extract_actives(chunk))
            docs.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "source_name": source_name,
                        "topic_category": topic_category,
                        "source_file": str(relative_path),
                        "chunk_index": i,
                        "actives": actives,
                    },
                )
            )
    return docs


def main(chroma_dir: str | None = None, reset: bool = False) -> None:
    """Run the indexing pipeline.

    Args:
        chroma_dir: Override the ChromaDB persistence directory. When None,
            uses settings.chroma_persist_dir (from .env or environment).
        reset: When True, drop and recreate the collection before indexing.
            Required when migrating from a whole-document index to avoid
            stale entries with the old per-file IDs.
    """
    target_dir = chroma_dir if chroma_dir is not None else settings.chroma_persist_dir

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)

    logger.info("Starting knowledge-base indexing (chunked)")
    logger.info("ChromaDB directory: %s", target_dir)

    # 1. Load and chunk documents
    docs = _load_documents()
    if not docs:
        logger.error("No .md files found under %s — nothing to index.", KB_DIR)
        sys.exit(1)
    logger.info("Prepared %d chunks from %d source files", len(docs), len({d.metadata["source_file"] for d in docs}))

    # 2. Embed all chunks in one batch
    embeddings = OpenRouterEmbeddings()
    logger.info("Embedding %d chunks via OpenRouter (%s) …", len(docs), settings.embedding_model)
    vectors = embeddings.embed_documents([doc.page_content for doc in docs])
    logger.info("Embedding complete — received %d vectors", len(vectors))

    # 3. Upsert into ChromaDB
    client = chromadb.PersistentClient(path=target_dir)

    if reset:
        logger.info("--reset: deleting existing collection %r", COLLECTION_NAME)
        client.delete_collection(name=COLLECTION_NAME)

    collection = client.get_or_create_collection(name=COLLECTION_NAME)

    # IDs are chunk-scoped to prevent collisions and enable idempotent upserts
    ids = [
        f"{doc.metadata['source_file']}::chunk_{doc.metadata['chunk_index']}"
        for doc in docs
    ]
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
        "Indexed %d chunks into ChromaDB collection %r (total in collection: %d)",
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
    parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help=(
            "Drop and recreate the ChromaDB collection before indexing. "
            "Use this when migrating from a whole-document index to avoid stale entries."
        ),
    )
    args = parser.parse_args()
    main(chroma_dir=args.chroma_dir, reset=args.reset)
