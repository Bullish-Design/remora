"""Qwen plugin composed from component implementations."""

from __future__ import annotations

from structured_agents.plugins.composed import ComposedModelPlugin
from structured_agents.plugins.qwen_components import (
    QwenGrammarProvider,
    QwenMessageFormatter,
    QwenResponseParser,
    QwenToolFormatter,
)


class QwenPlugin(ComposedModelPlugin):
    """Example implementation; not feature-complete."""

    def __init__(self) -> None:
        super().__init__(
            name="qwen",
            message_formatter=QwenMessageFormatter(),
            tool_formatter=QwenToolFormatter(),
            response_parser=QwenResponseParser(),
            grammar_provider=QwenGrammarProvider(),
        )
