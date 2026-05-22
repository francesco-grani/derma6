"""Chat history management for conversation context.

Uses LangChain's SQLChatMessageHistory to persist conversation messages
keyed by session_id (username).
"""

from datetime import datetime, timezone

from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory

from backend.config import settings


def get_history(username: str) -> BaseChatMessageHistory:
    """Get or create chat history for a user.

    Args:
        username: The username to retrieve history for (used as session_id).

    Returns:
        A BaseChatMessageHistory object with .messages, .add_user_message(),
        .add_ai_message(), and .clear() methods.
    """
    return SQLChatMessageHistory(
        session_id=username,
        connection=settings.sqlite_url,
    )


def clear(username: str) -> None:
    """Clear all chat history for a user.

    Args:
        username: The username whose history should be cleared.
    """
    history = get_history(username)
    history.clear()


def serialise_history(username: str) -> list[dict]:
    """Return chat history as a list of dicts suitable for JSON export.

    Each message is returned as a dict with 'role', 'content', and 'timestamp'.
    Note: SQLChatMessageHistory does not persist per-message timestamps; the
    timestamp field is set to the serialisation time as a placeholder.

    Returns:
        A list of dicts with keys: role ("human"|"ai"), content (str),
        timestamp (ISO8601). Empty list if no messages exist.
    """
    history = get_history(username)
    result = []
    for msg in history.messages:
        role = "human" if msg.type == "human" else "ai"
        result.append({
            "role": role,
            "content": msg.content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    return result
