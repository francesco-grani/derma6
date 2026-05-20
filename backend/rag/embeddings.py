"""LangChain-compatible embedding client for OpenRouter API.

Calls qwen/qwen3-embedding-8b (or any configured embedding model) via
the OpenRouter /v1/embeddings endpoint using a synchronous httpx client.
"""

import httpx
from langchain_core.embeddings import Embeddings

from backend.config import settings


class OpenRouterEmbeddings(Embeddings):
    """Calls OpenRouter /v1/embeddings endpoint via httpx."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents. Returns list of float vectors."""
        url = f"{settings.openrouter_base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.embedding_model,
            "input": texts,
        }

        with httpx.Client() as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()

        data = response.json()["data"]
        return [item["embedding"] for item in data]

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        return self.embed_documents([text])[0]
