from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xgrammar import StructuralTag


@dataclass(frozen=True, slots=True)
class EBNFGrammar:
    """EBNF grammar string for XGrammar."""

    grammar: str

    def to_vllm_payload(self) -> dict[str, Any]:
        return {
            "structured_outputs": {
                "type": "grammar",
                "grammar": self.grammar,
            }
        }


@dataclass(frozen=True, slots=True)
class StructuralTagGrammar:
    """XGrammar structural tag for optimized tool calling."""

    tag: StructuralTag

    def to_vllm_payload(self) -> dict[str, Any]:
        return {
            "structured_outputs": {
                "type": "structural_tag",
                "structural_tag": self.tag,
            }
        }


@dataclass(frozen=True, slots=True)
class JsonSchemaGrammar:
    """JSON schema constraint."""

    schema: dict[str, Any]

    def to_vllm_payload(self) -> dict[str, Any]:
        return {
            "structured_outputs": {
                "type": "json_schema",
                "json_schema": self.schema,
            }
        }


GrammarArtifact = EBNFGrammar | StructuralTagGrammar | JsonSchemaGrammar | None
