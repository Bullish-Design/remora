"""Markdown section extractor scaffold."""

from __future__ import annotations

from pathlib import Path

from persistent_ids.extractors.base import BaseExtractor
from persistent_ids.id_format import parse_graph_id
from persistent_ids.line_index import LineIndex
from persistent_ids.models import ChangedRange, ExtractedEntity


class MarkdownExtractor(BaseExtractor):
    """Extract Markdown section/heading durable nodes."""

    language = "markdown"
    query_path = Path(__file__).resolve().parents[3] / "queries" / "markdown" / "sections.scm"

    def extract(
        self,
        tree: object,
        source: bytes,
        *,
        changed_ranges: list[ChangedRange] | None = None,
    ) -> list[ExtractedEntity]:
        """Return extracted entities from Markdown tree.

        TODO: traverse section nodes and emit hierarchical edges.
        """

        _ = tree
        _ = changed_ranges
        line_index = LineIndex(source)
        header_line = line_index.line_at_row(0)
        _ = parse_graph_id(header_line)
        return []
