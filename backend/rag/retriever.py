"""Retriever for ChromaDB-backed skincare knowledge base.

Provides the Retriever class, which queries the persistent ChromaDB collection
using embeddings from OpenRouterEmbeddings and returns scored RetrievedDoc objects.
"""

import logging
from dataclasses import dataclass

import chromadb

from backend.config import settings
from backend.rag.embeddings import OpenRouterEmbeddings

logger = logging.getLogger(__name__)


@dataclass
class RetrievedDoc:
    content: str
    source_name: str
    score: float


class EmptyCollectionError(Exception):
    """Raised when the ChromaDB collection contains no documents."""


class Retriever:
    def __init__(self, embeddings=None):
        """Initialise the retriever.

        Args:
            embeddings: LangChain Embeddings instance. Defaults to
                OpenRouterEmbeddings() when None.
        """
        self._embeddings = embeddings if embeddings is not None else OpenRouterEmbeddings()

        client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        self._collection = client.get_or_create_collection(name="skincare_kb")

    def query(self, text: str, k: int = None) -> list[RetrievedDoc]:
        """Query the knowledge base for the most relevant documents.

        Args:
            text: The query string.
            k: Number of results to retrieve. Defaults to settings.retrieval_top_k.

        Returns:
            List of RetrievedDoc objects that pass the minimum score threshold.

        Raises:
            EmptyCollectionError: If the collection contains no documents.
        """
        if k is None:
            k = settings.retrieval_top_k

        if self._collection.count() == 0:
            raise EmptyCollectionError(
                "The skincare knowledge base is empty. Run the ingestion script first."
            )

        query_embedding = self._embeddings.embed_query(text)

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )

        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]

        retrieved: list[RetrievedDoc] = []
        for doc, meta, distance in zip(documents, metadatas, distances):
            # ChromaDB defaults to L2 distance. For unit-normalized vectors,
            # cosine_sim = 1 - L2² / 2 (not 1 - L2).
            score = 1.0 - (distance * distance) / 2.0
            if score >= settings.retrieval_min_score:
                retrieved.append(
                    RetrievedDoc(
                        content=doc,
                        source_name=meta.get("source_name", ""),
                        score=score,
                    )
                )

        source_names = [r.source_name for r in retrieved]
        logger.debug(
            "Query: %r | retrieved %d docs above threshold | sources: %s",
            text,
            len(retrieved),
            source_names,
        )

        if not retrieved:
            logger.warning(
                "No documents passed the minimum score threshold (%.2f) for query: %r",
                settings.retrieval_min_score,
                text,
            )

        return retrieved


# Shared singleton — ChromaDB's PersistentClient must not be opened more than once
# per process, so every consumer that needs retrieval (the kb_search tool, the
# agentic RAG pipeline's retrieve node, and the profile-tool helpers) imports THIS
# instance rather than constructing its own. It lives here, in the RAG layer, so no
# lower layer has to reach up into `backend.tools` to get it.
retriever = Retriever()
