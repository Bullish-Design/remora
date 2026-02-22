from __future__ import annotations

from typing import Protocol

from structured_agents.grammar.artifacts import GrammarArtifact
from structured_agents.grammar.config import GrammarConfig
from structured_agents.types import ToolSchema


class GrammarBuilder(Protocol):
    """Protocol for building grammar artifacts from tool schemas."""

    def build(self, tools: list[ToolSchema], config: GrammarConfig) -> GrammarArtifact:
        """Build a grammar artifact for the given tools.

        Args:
            tools: Available tool schemas.
            config: Grammar configuration.

        Returns:
            Grammar artifact (EBNF, structural tag, or JSON schema).
        """
        ...

    def supports_mode(self, mode: str) -> bool:
        """Check if this builder supports the given mode."""
        ...
