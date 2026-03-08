"""Cross-node link types."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LinkRelationship(str, Enum):
    CALLS = "calls"
    CALLED_BY = "called_by"
    TESTS = "tests"
    TESTED_BY = "tested_by"
    DOCUMENTS = "documents"
    DOCUMENTED_BY = "documented_by"
    IMPORTS = "imports"
    IMPORTED_BY = "imported_by"
    SIMILAR_TO = "similar_to"
    RELATED_TO = "related_to"


@dataclass
class NodeLink:
    source_node_id: str
    target_node_id: str
    relationship: str
    confidence: float
    note: str = ""

    @classmethod
    def from_dict(cls, source_node_id: str, data: dict) -> "NodeLink":
        return cls(
            source_node_id=source_node_id,
            target_node_id=data["target_node_id"],
            relationship=data["relationship"],
            confidence=data.get("confidence", 1.0),
            note=data.get("note", ""),
        )

    @classmethod
    def from_agent_node(cls, source_node_id: str, target_node_id: str, relationship: str) -> "NodeLink":
        return cls(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relationship=relationship,
            confidence=1.0,
            note="graph-derived",
        )


__all__ = ["NodeLink", "LinkRelationship"]
