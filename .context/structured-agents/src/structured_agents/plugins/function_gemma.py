"""FunctionGemma plugin composed from component implementations."""

from __future__ import annotations

from structured_agents.plugins.composed import ComposedModelPlugin
from structured_agents.plugins.function_gemma_components import (
    FunctionGemmaGrammarProvider,
    FunctionGemmaMessageFormatter,
    FunctionGemmaResponseParser,
    FunctionGemmaToolFormatter,
)


class FunctionGemmaPlugin(ComposedModelPlugin):
    """Plugin for Google's FunctionGemma models."""

    def __init__(self) -> None:
        super().__init__(
            name="function_gemma",
            message_formatter=FunctionGemmaMessageFormatter(),
            tool_formatter=FunctionGemmaToolFormatter(),
            response_parser=FunctionGemmaResponseParser(),
            grammar_provider=FunctionGemmaGrammarProvider(),
        )
