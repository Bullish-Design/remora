"""Test utilities for Remora.

This module provides fakes, factories, and patches for testing Remora
components. It can be used both internally and by downstream projects.
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
from remora.testing.factories import (
    make_ctx,
    make_definition,
    make_node,
    make_runner_config,
    make_server_config,
    tool_call_message,
    tool_schema,
)
from remora.testing.mock_vllm_server import MockVLLMServer

__all__ = [
    # Fakes
    "FakeAsyncOpenAI",
    "FakeChatCompletions",
    "FakeCompletionChoice",
    "FakeCompletionMessage",
    "FakeCompletionResponse",
    "FakeGrailExecutor",
    "FakeToolCall",
    "FakeToolCallFunction",
    # Factories
    "make_ctx",
    "make_definition",
    "make_node",
    "make_runner_config",
    "make_server_config",
    "tool_call_message",
    "tool_schema",
    # Patches
    # Mock server
    "MockVLLMServer",
]
