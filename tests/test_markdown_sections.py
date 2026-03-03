"""Tests for markdown section discovery ordering and name extraction.

Tests three fixes:
1. _collect_captures dict-branch must sort by document position
2. _extract_name must handle nested captures (section > heading > inline)
3. section.scm should capture both sections (heading + paragraphs) and headings
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from remora.core.discovery import (
    CSTNode,
    _collect_captures,
    _extract_name,
    _parse_file,
    discover,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_MD = FIXTURE_DIR / "sample.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_md(tmp_path: Path, content: str) -> Path:
    """Write markdown content to a temp file and return its path."""
    md_file = tmp_path / "test.md"
    md_file.write_text(dedent(content), encoding="utf-8")
    return md_file


# ---------------------------------------------------------------------------
# Phase 1: _collect_captures ordering
# ---------------------------------------------------------------------------


class TestCollectCapturesOrdering:
    """_collect_captures must return captures sorted by document position,
    even when tree-sitter returns a dict grouped by capture name."""

    def test_captures_sorted_by_start_position(self) -> None:
        """Captures from the dict branch must be sorted by (row, col)."""
        import tree_sitter_markdown
        from tree_sitter import Language, Parser, Query

        lang = Language(tree_sitter_markdown.language())
        parser = Parser(lang)

        md = dedent("""\
            # First

            Paragraph one.

            ## Second

            Paragraph two.

            # Third

            Paragraph three.
        """)
        tree = parser.parse(md.encode())

        query_text = """
        (section
          (atx_heading
            (inline) @section.name)) @section.def
        """
        query = Query(lang, query_text)

        captures = _collect_captures(query, tree.root_node)

        # Filter to just .def captures (skip .name)
        defs = [(node, name) for node, name in captures if name == "section.def"]

        # Must be in document order: First (line 0), Second (line 4), Third (line 8)
        positions = [node.start_point[0] for node, _ in defs]
        assert positions == sorted(positions), f"Captures not in document order: lines {positions}"


# ---------------------------------------------------------------------------
# Phase 2: _extract_name for nested captures
# ---------------------------------------------------------------------------


class TestExtractNameNested:
    """_extract_name must find .name captures that are descendants of the
    .def node, not just direct children."""

    def test_section_node_gets_heading_text_as_name(self) -> None:
        """A section node's name should be the heading text (inline),
        even though inline is a grandchild (section > atx_heading > inline)."""
        import tree_sitter_markdown
        from tree_sitter import Language, Parser, Query

        lang = Language(tree_sitter_markdown.language())
        parser = Parser(lang)

        md = "# My Section Title\n\nSome paragraph text.\n"
        tree = parser.parse(md.encode())

        query_text = """
        (section
          (atx_heading
            (inline) @section.name)) @section.def
        """
        query = Query(lang, query_text)
        captures = _collect_captures(query, tree.root_node)

        # Find the section.def node
        section_node = None
        for node, name in captures:
            if name == "section.def":
                section_node = node
                break

        assert section_node is not None, "No section.def capture found"

        extracted = _extract_name(section_node, captures)
        assert extracted == "My Section Title", f"Expected 'My Section Title', got {extracted!r}"


# ---------------------------------------------------------------------------
# Phase 3: Two-node-type markdown discovery (sections AND headings)
# ---------------------------------------------------------------------------


class TestMarkdownSectionDiscovery:
    """discover() on markdown files should return section CSTNodes that
    include heading + paragraph text, with correct names and ordering."""

    def test_section_text_includes_paragraphs(self, tmp_path: Path) -> None:
        """Section CSTNodes should contain the heading and all paragraphs."""
        md_file = _write_md(
            tmp_path,
            """\
            # My Section

            First paragraph.

            Second paragraph.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])

        sections = [n for n in nodes if n.node_type == "section"]
        assert len(sections) >= 1, "Expected at least one section node"

        section = sections[0]
        assert "# My Section" in section.text
        assert "First paragraph." in section.text
        assert "Second paragraph." in section.text

    def test_section_name_is_heading_text(self, tmp_path: Path) -> None:
        """Section names should be the heading inline text."""
        md_file = _write_md(
            tmp_path,
            """\
            # Introduction

            Some text.

            ## Details

            More text.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])

        sections = [n for n in nodes if n.node_type == "section"]
        names = [s.name for s in sections]
        assert "Introduction" in names
        assert "Details" in names

    def test_sections_ordered_by_document_position(self, tmp_path: Path) -> None:
        """Sections must appear in document order."""
        md_file = _write_md(
            tmp_path,
            """\
            # Alpha

            Text.

            ## Beta

            Text.

            # Gamma

            Text.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])

        sections = [n for n in nodes if n.node_type == "section"]
        names = [s.name for s in sections]
        # Alpha contains Beta as a subsection, so ordering should be:
        # Alpha (line 1), Beta (line 5), Gamma (line 9)
        assert names == ["Alpha", "Beta", "Gamma"], f"Sections not in document order: {names}"

    def test_subsection_does_not_include_sibling_content(self, tmp_path: Path) -> None:
        """A subsection's text should only include its own heading + paragraphs,
        not content from sibling or parent sections."""
        md_file = _write_md(
            tmp_path,
            """\
            # Parent

            Parent paragraph.

            ## Child

            Child paragraph.

            # Sibling

            Sibling paragraph.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])

        sections = {n.name: n for n in nodes if n.node_type == "section"}
        assert "Child" in sections

        child = sections["Child"]
        assert "Child paragraph." in child.text
        assert "Parent paragraph." not in child.text
        assert "Sibling paragraph." not in child.text


class TestMarkdownHeadingDiscovery:
    """discover() on markdown files should also return heading CSTNodes
    that contain just the heading line, distinct from section nodes."""

    def test_heading_nodes_returned(self, tmp_path: Path) -> None:
        """Headings should appear as separate CSTNodes with node_type='heading'."""
        md_file = _write_md(
            tmp_path,
            """\
            # Title

            Paragraph.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])

        headings = [n for n in nodes if n.node_type == "heading"]
        assert len(headings) == 1, f"Expected 1 heading, got {len(headings)}"
        assert headings[0].name == "Title"

    def test_heading_text_is_just_heading_line(self, tmp_path: Path) -> None:
        """Heading CSTNodes should contain only the heading line, not paragraphs."""
        md_file = _write_md(
            tmp_path,
            """\
            # Title

            Paragraph content here.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])

        headings = [n for n in nodes if n.node_type == "heading"]
        assert len(headings) == 1
        assert "# Title" in headings[0].text
        assert "Paragraph" not in headings[0].text

    def test_both_sections_and_headings_returned(self, tmp_path: Path) -> None:
        """Both section and heading CSTNodes should be returned for the same content."""
        md_file = _write_md(
            tmp_path,
            """\
            # Alpha

            Text.

            ## Beta

            More text.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])

        sections = [n for n in nodes if n.node_type == "section"]
        headings = [n for n in nodes if n.node_type == "heading"]

        section_names = [s.name for s in sections]
        heading_names = [h.name for h in headings]

        assert "Alpha" in section_names
        assert "Beta" in section_names
        assert "Alpha" in heading_names
        assert "Beta" in heading_names

    def test_sections_and_headings_interleaved_in_document_order(self, tmp_path: Path) -> None:
        """Sections and headings should be interleaved by document position."""
        md_file = _write_md(
            tmp_path,
            """\
            # First

            Text.

            # Second

            Text.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])

        # Filter to just section + heading nodes
        relevant = [n for n in nodes if n.node_type in ("section", "heading")]

        # Should be sorted by start_line (discover guarantees this)
        lines = [n.start_line for n in relevant]
        assert lines == sorted(lines), f"Not in document order: {lines}"

    def test_heading_count_matches_section_count(self, tmp_path: Path) -> None:
        """Each section should have a corresponding heading."""
        md_file = _write_md(
            tmp_path,
            """\
            # One

            Text.

            ## Two

            Text.

            # Three

            Text.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])

        sections = [n for n in nodes if n.node_type == "section"]
        headings = [n for n in nodes if n.node_type == "heading"]

        assert len(sections) == len(headings), f"Section count ({len(sections)}) != heading count ({len(headings)})"


class TestMarkdownSampleFixture:
    """End-to-end test with the existing sample.md fixture."""

    def test_sample_md_produces_sections_and_headings(self) -> None:
        """sample.md should produce correctly named sections and headings."""
        nodes = discover([SAMPLE_MD], languages=["markdown"])

        sections = [n for n in nodes if n.node_type == "section"]
        headings = [n for n in nodes if n.node_type == "heading"]

        section_names = [s.name for s in sections]
        heading_names = [h.name for h in headings]

        # sample.md has: # Sample Document, ## Introduction, ### Subsection,
        # ## Code Examples, ## Conclusion
        for name in ["Sample Document", "Introduction", "Subsection", "Code Examples", "Conclusion"]:
            assert name in section_names, f"Missing section: {name}"
            assert name in heading_names, f"Missing heading: {name}"

    def test_sample_md_section_text_includes_paragraphs(self) -> None:
        """The Introduction section should include its paragraph text."""
        nodes = discover([SAMPLE_MD], languages=["markdown"])

        sections = {n.name: n for n in nodes if n.node_type == "section"}
        assert "Introduction" in sections

        intro = sections["Introduction"]
        assert "introductory text" in intro.text

    def test_sample_md_heading_text_excludes_paragraphs(self) -> None:
        """The Introduction heading should NOT include paragraph text."""
        nodes = discover([SAMPLE_MD], languages=["markdown"])

        headings = {n.name: n for n in nodes if n.node_type == "heading"}
        assert "Introduction" in headings

        intro_heading = headings["Introduction"]
        assert "## Introduction" in intro_heading.text
        assert "introductory text" not in intro_heading.text
