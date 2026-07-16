"""Chat history management for conversation context.

History is keyed by session_id (UUID), not username. Each chat session has its
own isolated message thread in LangChain's SQLChatMessageHistory / message_store.
"""

from datetime import datetime, timezone
from functools import lru_cache

from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory

from backend.db.models import engine


# Cached because SQLChatMessageHistory.__init__ issues a CREATE TABLE IF NOT
# EXISTS round trip every single time one is constructed, and we construct one
# twice per chat turn and once per session on export. Reuse is safe: the object
# holds no message state — .messages, add_*_message and clear all read/write the
# DB on each call — so a cached instance sees the same rows a fresh one would.
# maxsize bounds the memory a long-lived process can accrue across sessions; an
# eviction costs only the one-off round trip again.
@lru_cache(maxsize=512)
def _history_for(session_id: str) -> BaseChatMessageHistory:
    # Pass the shared Engine, never a URL string: given a string,
    # SQLChatMessageHistory builds its own engine — and its own connection pool
    # — per instance, which exhausts the Supabase pooler's connection cap
    # (export.py serialises every session of a user in one request).
    return SQLChatMessageHistory(
        session_id=session_id,
        connection=engine,
    )


def get_history(session_id: str) -> BaseChatMessageHistory:
    """Get or create chat history for a session_id.

    session_id can be a UUID (new sessions) or a legacy username string
    (migrated from the pre-session architecture).
    """
    return _history_for(session_id)


def clear(session_id: str) -> None:
    """Clear all messages for a session."""
    get_history(session_id).clear()


def serialise_history(session_id: str) -> list[dict]:
    """Return history as a list of dicts for JSON export or API responses."""
    history = get_history(session_id)
    now = datetime.now(timezone.utc).isoformat()
    result = []
    for msg in history.messages:
        role = "human" if msg.type == "human" else "ai"
        result.append({"role": role, "content": msg.content, "timestamp": now})
    return result
