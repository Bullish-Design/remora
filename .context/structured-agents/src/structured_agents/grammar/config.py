from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class GrammarConfig:
    """Configuration for grammar generation."""

    mode: Literal["ebnf", "structural_tag", "json_schema"] = "ebnf"
    allow_parallel_calls: bool = True
    args_format: Literal["permissive", "escaped_strings", "json"] = "permissive"
