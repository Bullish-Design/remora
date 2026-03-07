"""Tests for markdown note and todo node discovery.

Tests three features:
1. Note nodes: .md files with YAML frontmatter produce a 'note' CSTNode
2. Todo checkbox items: - [ ] / - [x] items become 'todo' CSTNodes
3. Todo notes: frontmatter with type: todo sets node_type='todo' on the note
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from remora.core.code.discovery import (
    CSTNode,
    _parse_file,
    discover,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_md(tmp_path: Path, content: str) -> Path:
    """Write markdown content to a temp file and return its path."""
    md_file = tmp_path / "test.md"
    md_file.write_text(dedent(content), encoding="utf-8")
    return md_file


# ===========================================================================
# Phase 1: Note Nodes (frontmatter)
# ===========================================================================


class TestNoteNodeFromFrontmatter:
    """Markdown files with YAML frontmatter should produce a 'note' CSTNode."""

    def test_frontmatter_produces_note_node(self, tmp_path: Path) -> None:
        """A .md file with frontmatter should have a note CSTNode."""
        md_file = _write_md(
            tmp_path,
            """\
            ---
            title: My Test Note
            tags: [python, testing]
            ---

            # My Test Note

            Some content here.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        notes = [n for n in nodes if n.node_type == "note"]
        assert len(notes) == 1, f"Expected 1 note node, got {len(notes)}"

    def test_note_name_from_frontmatter_title(self, tmp_path: Path) -> None:
        """The note's name should come from the frontmatter title key."""
        md_file = _write_md(
            tmp_path,
            """\
            ---
            title: Important Ideas
            ---

            # Important Ideas

            Content.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        notes = [n for n in nodes if n.node_type == "note"]
        assert len(notes) == 1
        assert notes[0].name == "Important Ideas"

    def test_note_text_is_entire_file(self, tmp_path: Path) -> None:
        """The note's text should be the entire file content."""
        content = dedent("""\
            ---
            title: Full Content Note
            ---

            # Full Content Note

            Paragraph one.

            Paragraph two.
        """)
        md_file = tmp_path / "test.md"
        md_file.write_text(content, encoding="utf-8")

        nodes = discover([md_file], languages=["markdown"])
        notes = [n for n in nodes if n.node_type == "note"]
        assert len(notes) == 1
        assert notes[0].text == content

    def test_note_spans_entire_file(self, tmp_path: Path) -> None:
        """The note should start at line 1 and end at the last line."""
        md_file = _write_md(
            tmp_path,
            """\
            ---
            title: Spanning Note
            ---

            # Spanning Note

            Content here.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        notes = [n for n in nodes if n.node_type == "note"]
        assert len(notes) == 1
        assert notes[0].start_line == 1

    def test_no_frontmatter_no_note_node(self, tmp_path: Path) -> None:
        """A .md file without frontmatter should NOT produce a note node."""
        md_file = _write_md(
            tmp_path,
            """\
            # Just a Heading

            No frontmatter here.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        notes = [n for n in nodes if n.node_type == "note"]
        assert len(notes) == 0, f"Expected 0 note nodes, got {len(notes)}"

    def test_note_name_fallback_to_filename(self, tmp_path: Path) -> None:
        """If frontmatter has no title key, name should fall back to filename."""
        md_file = _write_md(
            tmp_path,
            """\
            ---
            tags: [misc]
            date: 2026-01-01
            ---

            # Some Heading

            Content.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        notes = [n for n in nodes if n.node_type == "note"]
        assert len(notes) == 1
        assert notes[0].name == "test.md"

    def test_note_coexists_with_sections(self, tmp_path: Path) -> None:
        """A note node should coexist with section/heading nodes."""
        md_file = _write_md(
            tmp_path,
            """\
            ---
            title: Coexisting Note
            ---

            # Heading One

            Paragraph.

            ## Heading Two

            More text.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        notes = [n for n in nodes if n.node_type == "note"]
        sections = [n for n in nodes if n.node_type == "section"]
        headings = [n for n in nodes if n.node_type == "heading"]

        assert len(notes) == 1
        assert len(sections) >= 1
        assert len(headings) >= 1


# ===========================================================================
# Phase 2: Todo Checkbox Items
# ===========================================================================


class TestTodoCheckboxItems:
    """Checkbox list items (- [ ] / - [x]) should become 'todo' CSTNodes."""

    def test_unchecked_item_produces_todo(self, tmp_path: Path) -> None:
        """A - [ ] item should produce a todo CSTNode."""
        md_file = _write_md(
            tmp_path,
            """\
            # Tasks

            - [ ] Buy groceries
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        todos = [n for n in nodes if n.node_type == "todo"]
        assert len(todos) == 1
        assert todos[0].name == "Buy groceries"

    def test_checked_item_produces_todo(self, tmp_path: Path) -> None:
        """A - [x] item should also produce a todo CSTNode."""
        md_file = _write_md(
            tmp_path,
            """\
            # Tasks

            - [x] Already done
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        todos = [n for n in nodes if n.node_type == "todo"]
        assert len(todos) == 1
        assert todos[0].name == "Already done"

    def test_multiple_todos(self, tmp_path: Path) -> None:
        """Multiple checkbox items should each produce a todo CSTNode."""
        md_file = _write_md(
            tmp_path,
            """\
            # Tasks

            - [ ] First task
            - [x] Second task
            - [ ] Third task
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        todos = [n for n in nodes if n.node_type == "todo"]
        assert len(todos) == 3
        names = [t.name for t in todos]
        assert "First task" in names
        assert "Second task" in names
        assert "Third task" in names

    def test_todo_text_contains_full_list_item(self, tmp_path: Path) -> None:
        """Todo text should contain the full list item including marker."""
        md_file = _write_md(
            tmp_path,
            """\
            # Tasks

            - [ ] Important task
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        todos = [n for n in nodes if n.node_type == "todo"]
        assert len(todos) == 1
        assert "[ ]" in todos[0].text
        assert "Important task" in todos[0].text

    def test_todos_in_document_order(self, tmp_path: Path) -> None:
        """Todos should appear in document order."""
        md_file = _write_md(
            tmp_path,
            """\
            # Tasks

            - [ ] Alpha
            - [x] Beta
            - [ ] Gamma
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        todos = [n for n in nodes if n.node_type == "todo"]
        names = [t.name for t in todos]
        assert names == ["Alpha", "Beta", "Gamma"]

    def test_regular_list_items_not_todos(self, tmp_path: Path) -> None:
        """Regular list items (without checkboxes) should NOT be todos."""
        md_file = _write_md(
            tmp_path,
            """\
            # Items

            - Regular item one
            - Regular item two
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        todos = [n for n in nodes if n.node_type == "todo"]
        assert len(todos) == 0

    def test_todos_coexist_with_sections(self, tmp_path: Path) -> None:
        """Todos should coexist with section and heading nodes."""
        md_file = _write_md(
            tmp_path,
            """\
            # My Section

            Some text.

            - [ ] A task
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        todos = [n for n in nodes if n.node_type == "todo"]
        sections = [n for n in nodes if n.node_type == "section"]
        assert len(todos) == 1
        assert len(sections) >= 1


# ===========================================================================
# Phase 3: Todo Note (frontmatter type: todo)
# ===========================================================================


class TestTodoNote:
    """A note with type: todo in frontmatter should get node_type='todo'."""

    def test_type_todo_in_frontmatter(self, tmp_path: Path) -> None:
        """Frontmatter with type: todo should produce a file-level todo node."""
        md_file = _write_md(
            tmp_path,
            """\
            ---
            title: Shopping List
            type: todo
            ---

            # Shopping List

            - [ ] Milk
            - [ ] Eggs
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        # Should have a file-level todo (from frontmatter type), NOT a note
        file_level_todos = [n for n in nodes if n.node_type == "todo" and n.start_line == 1]
        assert len(file_level_todos) == 1
        assert file_level_todos[0].name == "Shopping List"

        # Should NOT have a note node
        notes = [n for n in nodes if n.node_type == "note"]
        assert len(notes) == 0

    def test_type_note_stays_as_note(self, tmp_path: Path) -> None:
        """Frontmatter with type: note should stay as a note node."""
        md_file = _write_md(
            tmp_path,
            """\
            ---
            title: Regular Note
            type: note
            ---

            # Regular Note

            Content.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        notes = [n for n in nodes if n.node_type == "note"]
        assert len(notes) == 1
        assert notes[0].name == "Regular Note"

    def test_no_type_defaults_to_note(self, tmp_path: Path) -> None:
        """Frontmatter without a type key should default to note."""
        md_file = _write_md(
            tmp_path,
            """\
            ---
            title: Default Type
            ---

            Content.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        notes = [n for n in nodes if n.node_type == "note"]
        assert len(notes) == 1

    def test_todo_note_with_checkbox_items(self, tmp_path: Path) -> None:
        """A todo note should have both the file-level todo and checkbox todos."""
        md_file = _write_md(
            tmp_path,
            """\
            ---
            title: Task List
            type: todo
            due: 2026-03-15
            ---

            # Task List

            - [ ] First task
            - [x] Done task
            - [ ] Another task
        """,
        )
        nodes = discover([md_file], languages=["markdown"])
        todos = [n for n in nodes if n.node_type == "todo"]

        # Should have 1 file-level todo + 3 checkbox todos = 4 total
        file_level = [t for t in todos if t.start_line == 1]
        checkbox = [t for t in todos if t.start_line > 1]

        assert len(file_level) == 1, f"Expected 1 file-level todo, got {len(file_level)}"
        assert file_level[0].name == "Task List"
        assert len(checkbox) == 3, f"Expected 3 checkbox todos, got {len(checkbox)}"


# ===========================================================================
# Integration: Full scenario
# ===========================================================================


class TestNotesAndTodosIntegration:
    """End-to-end integration tests combining notes, todos, and existing features."""

    def test_full_note_with_todos(self, tmp_path: Path) -> None:
        """A complete note with frontmatter, headings, sections, and todos."""
        md_file = _write_md(
            tmp_path,
            """\
            ---
            title: My Project Note
            tags: [python, testing]
            ---

            # My Project Note

            Some content here.

            ## Tasks

            - [ ] Write tests
            - [x] Review code
            - [ ] Deploy

            ## Notes

            Additional notes here.
        """,
        )
        nodes = discover([md_file], languages=["markdown"])

        node_types = {n.node_type for n in nodes}
        assert "note" in node_types
        assert "todo" in node_types
        assert "section" in node_types
        assert "heading" in node_types

        # Check counts
        notes = [n for n in nodes if n.node_type == "note"]
        todos = [n for n in nodes if n.node_type == "todo"]
        assert len(notes) == 1
        assert len(todos) == 3
        assert notes[0].name == "My Project Note"

    def test_discover_directory_with_mixed_files(self, tmp_path: Path) -> None:
        """discover() on a directory should handle .md files with and without frontmatter."""
        # File with frontmatter
        note_file = tmp_path / "note.md"
        note_file.write_text(
            dedent("""\
            ---
            title: A Note
            ---

            # A Note

            Content.
        """),
            encoding="utf-8",
        )

        # File without frontmatter
        plain_file = tmp_path / "plain.md"
        plain_file.write_text(
            dedent("""\
            # Plain Heading

            Just plain markdown.
        """),
            encoding="utf-8",
        )

        nodes = discover([tmp_path], languages=["markdown"])

        # note.md should have a note node
        note_nodes = [n for n in nodes if n.node_type == "note"]
        assert len(note_nodes) == 1
        assert note_nodes[0].name == "A Note"

        # plain.md should NOT have a note node
        plain_notes = [n for n in nodes if n.node_type == "note" and "plain.md" in n.file_path]
        assert len(plain_notes) == 0
