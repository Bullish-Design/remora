"""Tests verifying ASTWatcher produces correct source_code for stub nodes.

The watcher's job is faithful source extraction. These tests confirm that
stubs (empty files, pass-only defs/classes, ellipsis bodies) produce
source_code values that ``_is_stub()`` in projections will detect as
scaffolds. No watcher code changes are expected — these tests document
the existing behavior that the scaffold pipeline depends on.
"""

from __future__ import annotations

import pytest

from remora.core.projections import _is_stub
from remora.lsp.watcher import ASTWatcher


@pytest.fixture()
def watcher():
    return ASTWatcher()


# =========================================================================
# Empty / whitespace-only files
# =========================================================================


class TestWatcherEmptyFile:
    """Empty .py files should produce a file node whose source_code is stub."""

    def test_empty_file_produces_file_node(self, watcher):
        nodes = watcher.parse_and_inject_ids("file:///empty.py", "")
        assert len(nodes) == 1
        assert nodes[0]["node_type"] == "file"

    def test_empty_file_source_code_is_stub(self, watcher):
        nodes = watcher.parse_and_inject_ids("file:///empty.py", "")
        assert _is_stub(nodes[0]["source_code"])

    def test_whitespace_only_file_is_stub(self, watcher):
        nodes = watcher.parse_and_inject_ids("file:///ws.py", "   \n\n  \n")
        file_node = nodes[0]
        assert file_node["node_type"] == "file"
        assert _is_stub(file_node["source_code"])


# =========================================================================
# Stub class definitions
# =========================================================================


class TestWatcherStubClass:
    """Class definitions with only ``pass`` or ``...`` body are stubs."""

    def test_class_pass_inline(self, watcher):
        text = "class Foo: pass\n"
        nodes = watcher.parse_and_inject_ids("file:///stub_cls.py", text)
        cls = [n for n in nodes if n["node_type"] == "class"]
        assert len(cls) == 1
        assert _is_stub(cls[0]["source_code"])

    def test_class_pass_block(self, watcher):
        text = "class Foo:\n    pass\n"
        nodes = watcher.parse_and_inject_ids("file:///stub_cls2.py", text)
        cls = [n for n in nodes if n["node_type"] == "class"]
        assert len(cls) == 1
        assert _is_stub(cls[0]["source_code"])

    def test_class_ellipsis(self, watcher):
        text = "class Foo: ...\n"
        nodes = watcher.parse_and_inject_ids("file:///stub_cls3.py", text)
        cls = [n for n in nodes if n["node_type"] == "class"]
        assert len(cls) == 1
        assert _is_stub(cls[0]["source_code"])

    def test_class_with_docstring_and_pass(self, watcher):
        text = 'class Foo:\n    """A placeholder."""\n    pass\n'
        nodes = watcher.parse_and_inject_ids("file:///stub_cls4.py", text)
        cls = [n for n in nodes if n["node_type"] == "class"]
        assert len(cls) == 1
        assert _is_stub(cls[0]["source_code"])

    def test_real_class_is_not_stub(self, watcher):
        text = "class Foo:\n    def __init__(self):\n        self.x = 1\n"
        nodes = watcher.parse_and_inject_ids("file:///real_cls.py", text)
        cls = [n for n in nodes if n["node_type"] == "class"]
        assert len(cls) == 1
        assert not _is_stub(cls[0]["source_code"])


# =========================================================================
# Stub function definitions
# =========================================================================


class TestWatcherStubFunction:
    """Function definitions with only ``pass`` or ``...`` body are stubs."""

    def test_def_pass_inline(self, watcher):
        text = "def foo(): pass\n"
        nodes = watcher.parse_and_inject_ids("file:///stub_fn.py", text)
        fns = [n for n in nodes if n["node_type"] == "function"]
        assert len(fns) == 1
        assert _is_stub(fns[0]["source_code"])

    def test_def_pass_block(self, watcher):
        text = "def foo():\n    pass\n"
        nodes = watcher.parse_and_inject_ids("file:///stub_fn2.py", text)
        fns = [n for n in nodes if n["node_type"] == "function"]
        assert len(fns) == 1
        assert _is_stub(fns[0]["source_code"])

    def test_def_ellipsis(self, watcher):
        text = "def foo(): ...\n"
        nodes = watcher.parse_and_inject_ids("file:///stub_fn3.py", text)
        fns = [n for n in nodes if n["node_type"] == "function"]
        assert len(fns) == 1
        assert _is_stub(fns[0]["source_code"])

    def test_def_with_docstring_and_pass(self, watcher):
        text = 'def foo():\n    """Placeholder."""\n    pass\n'
        nodes = watcher.parse_and_inject_ids("file:///stub_fn4.py", text)
        fns = [n for n in nodes if n["node_type"] == "function"]
        assert len(fns) == 1
        assert _is_stub(fns[0]["source_code"])

    def test_async_def_pass(self, watcher):
        text = "async def bar(): pass\n"
        nodes = watcher.parse_and_inject_ids("file:///stub_async.py", text)
        fns = [n for n in nodes if n["node_type"] == "function"]
        assert len(fns) == 1
        assert _is_stub(fns[0]["source_code"])

    def test_real_function_is_not_stub(self, watcher):
        text = "def foo():\n    return 42\n"
        nodes = watcher.parse_and_inject_ids("file:///real_fn.py", text)
        fns = [n for n in nodes if n["node_type"] == "function"]
        assert len(fns) == 1
        assert not _is_stub(fns[0]["source_code"])


# =========================================================================
# Source code fidelity
# =========================================================================


class TestWatcherSourceFidelity:
    """Watcher source_code extraction must be exact enough for _is_stub."""

    def test_function_source_matches_text(self, watcher):
        """source_code for a function should be the exact text of that function."""
        text = "def foo(): pass\n"
        nodes = watcher.parse_and_inject_ids("file:///fidelity.py", text)
        fn = [n for n in nodes if n["node_type"] == "function"][0]
        # source_code should be exactly the function text (without trailing newline
        # since tree-sitter captures up to end_byte)
        assert fn["source_code"] == "def foo(): pass"

    def test_class_source_matches_text(self, watcher):
        text = "class Bar: pass\n"
        nodes = watcher.parse_and_inject_ids("file:///fidelity2.py", text)
        cls = [n for n in nodes if n["node_type"] == "class"][0]
        assert cls["source_code"] == "class Bar: pass"

    def test_file_source_is_prefix(self, watcher):
        """File node source_code is first 200 chars (sufficient for empty files)."""
        text = "# just a comment\n"
        nodes = watcher.parse_and_inject_ids("file:///prefix.py", text)
        file_node = [n for n in nodes if n["node_type"] == "file"][0]
        assert file_node["source_code"] == text[:200]
