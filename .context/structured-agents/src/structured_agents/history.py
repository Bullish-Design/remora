"""History management strategies for the agent loop."""

from __future__ import annotations

from typing import Protocol

from structured_agents.types import Message


class HistoryStrategy(Protocol):
    """Protocol for managing conversation history.

    Implementations control how history is trimmed to fit context limits.
    """

    def trim(self, messages: list[Message], max_messages: int) -> list[Message]:
        """Trim history to fit within limits.

        Args:
            messages: Current message history.
            max_messages: Maximum number of messages to retain.

        Returns:
            Trimmed message list. Must preserve the first message (system prompt)
            if it exists and is a system message.
        """
        ...


class SlidingWindowHistory:
    """Simple sliding window that keeps the system prompt + most recent messages.

    This is the default strategy. It preserves the system prompt (first message
    if role="system") and keeps the N most recent messages after that.
    """

    def trim(self, messages: list[Message], max_messages: int) -> list[Message]:
        if len(messages) <= max_messages:
            return messages

        if not messages:
            return messages

        if messages[0].role == "system":
            system_msg = messages[0]
            recent = messages[-(max_messages - 1) :]
            return [system_msg] + recent

        return messages[-max_messages:]


class KeepAllHistory:
    """Strategy that keeps all messages (no trimming).

    Use with caution - can exceed context limits.
    """

    def trim(self, messages: list[Message], max_messages: int) -> list[Message]:
        return messages
