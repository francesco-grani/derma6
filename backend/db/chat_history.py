"""Chat history management for conversation context.

History is keyed by session_id (UUID), not username. Each chat session has its
own isolated message thread in LangChain's SQLChatMessageHistory / message_store.
"""

from datetime import datetime, timezone

from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory

from backend.config import settings


def get_history(session_id: str) -> BaseChatMessageHistory:
    """Get or create chat history for a session_id.

    session_id can be a UUID (new sessions) or a legacy username string
    (migrated from the pre-session architecture).
    """
    return SQLChatMessageHistory(
        session_id=session_id,
        connection=settings.sqlalchemy_database_url,
    )


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
