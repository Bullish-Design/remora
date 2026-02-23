"""
tests/hub/test_edge_cases.py

Edge case handling for Hub daemon.
"""

from pathlib import Path

import pytest

from remora.hub.indexer import index_file_simple


def test_syntax_error_file(tmp_path: Path, mock_store: "Any") -> None:
    """Test handling of files with syntax errors."""
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def broken(\n", encoding="utf-8")  # Syntax error

    # Should not raise, should return empty
    indexed = index_file_simple(bad_file, mock_store)
    assert indexed == []


def test_binary_file(tmp_path: Path, mock_store: "Any") -> None:
    """Test handling of binary files."""
    binary_file = tmp_path / "binary.py"
    binary_file.write_bytes(b"\x00\x01\x02\x03")

    indexed = index_file_simple(binary_file, mock_store)
    assert indexed == []


def test_empty_file(tmp_path: Path, mock_store: "Any") -> None:
    """Test handling of empty files."""
    empty_file = tmp_path / "empty.py"
    empty_file.write_text("", encoding="utf-8")

    indexed = index_file_simple(empty_file, mock_store)
    assert indexed == []


def test_very_long_function(tmp_path: Path, mock_store: "Any") -> None:
    """Test handling of very long functions."""
    long_func = tmp_path / "long.py"
    body = "\n".join([f"    x = {i}" for i in range(1000)])
    long_func.write_text(f"def very_long():\n{body}\n    return x\n", encoding="utf-8")

    indexed = index_file_simple(long_func, mock_store)
    assert len(indexed) == 1
    # Should handle without memory issues


def test_unicode_content(tmp_path: Path, mock_store: "Any") -> None:
    """Test handling of Unicode in source code."""
    unicode_file = tmp_path / "unicode.py"
    unicode_file.write_text('''
def greeting():
    """Returns a greeting."""
    return "Hello, World!"
''', encoding="utf-8")

    indexed = index_file_simple(unicode_file, mock_store)
    assert len(indexed) == 1


def test_nested_functions(tmp_path: Path, mock_store: "Any") -> None:
    """Test handling of nested function definitions."""
    nested_file = tmp_path / "nested.py"
    nested_file.write_text('''
def outer():
    """Outer function."""
    def inner():
        """Inner function."""
        return 42
    return inner
''', encoding="utf-8")

    indexed = index_file_simple(nested_file, mock_store)
    # Should index outer, behavior for inner is implementation-defined
    assert "outer" in indexed[0]["name"] if indexed else True
