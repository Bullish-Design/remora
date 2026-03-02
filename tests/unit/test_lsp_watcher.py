# tests/unit/test_lsp_watcher.py
from __future__ import annotations

import pytest
from remora.lsp.watcher import ASTWatcher


def test_parse_functions_and_classes():
    watcher = ASTWatcher()
    text = """
def top_level():
    pass

class MyClass:
    def my_method(self):
        pass

def another():
    pass
"""
    nodes = watcher.parse_and_inject_ids("file:///test.py", text)
    names = [(n.name, n.node_type) for n in nodes]
    assert ("top_level", "function") in names
    assert ("MyClass", "class") in names
    assert ("my_method", "method") in names
    assert ("another", "function") in names


def test_parse_preserves_ids():
    """Existing IDs should be reused on re-parse."""
    watcher = ASTWatcher()
    text = "def foo(): pass\n"
    nodes1 = watcher.parse_and_inject_ids("file:///t.py", text)
    old_nodes = [{"name": n.name, "node_type": n.node_type, "id": n.remora_id} for n in nodes1]
    nodes2 = watcher.parse_and_inject_ids("file:///t.py", text, old_nodes)
    assert nodes1[0].remora_id == nodes2[0].remora_id


def test_parse_multibyte_characters():
    """Function names must be correct even when file contains multi-byte UTF-8."""
    watcher = ASTWatcher()
    text = "# Comment with emoji: \u2728\ndef read_optional(path):\n    pass\n"
    nodes = watcher.parse_and_inject_ids("file:///test_mb.py", text)
    names = [n.name for n in nodes if n.node_type == "function"]
    assert "read_optional" in names, f"Expected 'read_optional', got {names}"
