"""Test utilities for Remora V2.

This module provides fakes for testing V2 components.
"""

from remora.testing.fakes import (
    FakeAsyncOpenAI,
    FakeChatCompletions,
    FakeCompletionChoice,
    FakeCompletionMessage,
    FakeCompletionResponse,
    FakeGrailExecutor,
    FakeToolCall,
    FakeToolCallFunction,
)

__all__ = [
    "FakeAsyncOpenAI",
    "FakeChatCompletions",
    "FakeCompletionChoice",
    "FakeCompletionMessage",
    "FakeCompletionResponse",
    "FakeGrailExecutor",
    "FakeToolCall",
    "FakeToolCallFunction",
]
