"""Base extractor protocol and utilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from persistent_ids.models import ChangedRange, ExtractedEntity


class BaseExtractor(ABC):
    """Language-specific extraction contract."""

    language: str
    query_path: Path

    @abstractmethod
    def extract(
        self,
        tree: object,
        source: bytes,
        *,
        changed_ranges: list[ChangedRange] | None = None,
    ) -> list[ExtractedEntity]:
        """Extract durable nodes from a tree."""

    @staticmethod
    def query_text(path: Path) -> str:
        """Load query text from disk."""

        return path.read_text(encoding="utf-8")
