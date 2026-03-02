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
    # Should return list of dicts, not ASTAgentNode objects
    assert all(isinstance(n, dict) for n in nodes), "Expected dicts, got non-dict objects"

    names = [(n["name"], n["node_type"]) for n in nodes]
    assert ("top_level", "function") in names
    assert ("MyClass", "class") in names
    assert ("my_method", "method") in names
    assert ("another", "function") in names


def test_parse_preserves_ids():
    """Existing IDs should be reused on re-parse."""
    watcher = ASTWatcher()
    text = "def foo(): pass\n"
    nodes1 = watcher.parse_and_inject_ids("file:///t.py", text)
    old_nodes = [{"name": n["name"], "node_type": n["node_type"], "id": n["node_id"]} for n in nodes1]
    nodes2 = watcher.parse_and_inject_ids("file:///t.py", text, old_nodes)
    assert nodes1[0]["node_id"] == nodes2[0]["node_id"]


def test_parse_multibyte_characters():
    """Function names must be correct even when file contains multi-byte UTF-8."""
    watcher = ASTWatcher()
    text = "# Comment with emoji: \u2728\ndef read_optional(path):\n    pass\n"
    nodes = watcher.parse_and_inject_ids("file:///test_mb.py", text)
    names = [n["name"] for n in nodes if n["node_type"] == "function"]
    assert "read_optional" in names, f"Expected 'read_optional', got {names}"


def test_parse_returns_required_dict_fields():
    """Every returned dict must have all fields needed for NodeDiscoveredEvent."""
    watcher = ASTWatcher()
    text = "def hello(): pass\n"
    nodes = watcher.parse_and_inject_ids("file:///fields.py", text)
    required_fields = {
        "node_id",
        "node_type",
        "name",
        "full_name",
        "file_path",
        "start_line",
        "end_line",
        "source_code",
        "source_hash",
        "parent_id",
    }
    for node in nodes:
        missing = required_fields - set(node.keys())
        assert not missing, f"Node {node.get('name')} missing fields: {missing}"


def test_parse_full_name_computation():
    """full_name should be computed correctly for all node types."""
    watcher = ASTWatcher()
    text = """
def top_func():
    pass

class MyClass:
    def my_method(self):
        pass
"""
    nodes = watcher.parse_and_inject_ids("file:///mymod.py", text)
    by_name = {n["name"]: n for n in nodes}

    # file-level node: full_name = stem
    assert by_name["mymod"]["full_name"] == "mymod"
    # function: full_name = stem.name
    assert by_name["top_func"]["full_name"] == "mymod.top_func"
    # class: full_name = stem.name
    assert by_name["MyClass"]["full_name"] == "mymod.MyClass"
    # method: full_name = stem.class.method
    assert by_name["my_method"]["full_name"] == "mymod.MyClass.my_method"


def test_parse_parent_id_links():
    """Methods should have their class as parent, functions should have file as parent."""
    watcher = ASTWatcher()
    text = """
def top_func():
    pass

class MyClass:
    def my_method(self):
        pass
"""
    nodes = watcher.parse_and_inject_ids("file:///test.py", text)
    by_name = {n["name"]: n for n in nodes}

    file_node = by_name["test"]
    class_node = by_name["MyClass"]
    method_node = by_name["my_method"]
    func_node = by_name["top_func"]

    assert func_node["parent_id"] == file_node["node_id"]
    assert class_node["parent_id"] == file_node["node_id"]
    assert method_node["parent_id"] == class_node["node_id"]


def test_parse_non_python_file():
    """Non-Python files should return a single file-level dict."""
    watcher = ASTWatcher()
    text = "# My Document\n\nSome content here.\n"
    nodes = watcher.parse_and_inject_ids("file:///readme.md", text)
    assert len(nodes) == 1
    assert isinstance(nodes[0], dict)
    assert nodes[0]["node_type"] == "file"
    assert nodes[0]["name"] == "readme"
    assert nodes[0]["full_name"] == "readme"
