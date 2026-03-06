"""Python durable-node extractor scaffold."""

from __future__ import annotations

from pathlib import Path

from persistent_ids.extractors.base import BaseExtractor
from persistent_ids.id_format import parse_graph_id
from persistent_ids.line_index import LineIndex
from persistent_ids.models import ChangedRange, ExtractedEntity


class PythonExtractor(BaseExtractor):
    """Extract Python class/function/method declarations."""

    language = "python"
    query_path = Path(__file__).resolve().parents[3] / "queries" / "python" / "tags.scm"

    def extract(
        self,
        tree: object,
        source: bytes,
        *,
        changed_ranges: list[ChangedRange] | None = None,
    ) -> list[ExtractedEntity]:
        """Return extracted entities from Python tree.

        TODO: execute query captures and map them into ExtractedEntity records.
        """

        _ = tree
        _ = changed_ranges
        line_index = LineIndex(source)

        # Scaffold behavior: no AST query execution yet.
        # Placeholder demonstrates how header-line ID scan should be wired.
        header_line = line_index.line_at_row(0)
        _ = parse_graph_id(header_line)
        return []
