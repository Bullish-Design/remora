"""Pydantic models for AST Summary."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AstNode(BaseModel):
    """Represents a universal structural block of a file."""

    node_type: str
    name: str
    source_text: str
    children: list[AstNode] = Field(default_factory=list)
    summary: str | None = None
    status: str = "pending"

    def flatten(self) -> list[AstNode]:
        """Flatten tree into list of all nodes (including self)."""
        result: list[AstNode] = [self]
        for child in self.children:
            result.extend(child.flatten())
        return result
