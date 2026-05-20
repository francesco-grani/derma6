"""Chat history management for conversation context.

Uses LangChain's SQLChatMessageHistory to persist conversation messages
keyed by session_id (username).
"""

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
        connection_string=settings.sqlite_url,
    )


def clear(username: str) -> None:
    """Clear all chat history for a user.

    Args:
        username: The username whose history should be cleared.
    """
    history = get_history(username)
    history.clear()
