"""Performance benchmarks for discovery module."""

from __future__ import annotations

from pathlib import Path

import pytest


def _create_test_files(directory: Path, count: int, lines_per_file: int) -> None:
    """Create test Python files for benchmarking."""
    for file_index in range(count):
        lines: list[str] = []
        for line_index in range(lines_per_file // 4):
            lines.extend(
                [
                    f"def function_{line_index}():",
                    f"    '''Function {line_index} in file {file_index}.'''",
                    f"    return {line_index}",
                    "",
                ]
            )
        content = "\n".join(lines)
        (directory / f"module_{file_index}.py").write_text(content, encoding="utf-8")


@pytest.fixture
def small_codebase(tmp_path: Path) -> Path:
    """Create a small test codebase (10 files, ~100 lines each)."""
    _create_test_files(tmp_path, count=10, lines_per_file=100)
    return tmp_path


@pytest.fixture
def medium_codebase(tmp_path: Path) -> Path:
    """Create a medium test codebase (50 files, ~200 lines each)."""
    _create_test_files(tmp_path, count=50, lines_per_file=200)
    return tmp_path


@pytest.fixture
def large_codebase(tmp_path: Path) -> Path:
    """Create a large test codebase (200 files, ~500 lines each)."""
    _create_test_files(tmp_path, count=200, lines_per_file=500)
    return tmp_path


class TestDiscoveryPerformance:
    """Benchmark tests for the discovery module."""

    def test_discover_small_codebase(self, benchmark, small_codebase: Path) -> None:
        """Benchmark discovery on small codebase."""
        from remora.discovery import TreeSitterDiscoverer

        discoverer = TreeSitterDiscoverer(
            root_dirs=[small_codebase],
            languages={".py": "tree_sitter_python"},
            query_pack="remora_core",
        )

        result = benchmark(discoverer.discover)

        assert len(result) > 0

    def test_discover_medium_codebase(self, benchmark, medium_codebase: Path) -> None:
        """Benchmark discovery on medium codebase."""
        from remora.discovery import TreeSitterDiscoverer

        discoverer = TreeSitterDiscoverer(
            root_dirs=[medium_codebase],
            languages={".py": "tree_sitter_python"},
            query_pack="remora_core",
        )

        result = benchmark(discoverer.discover)

        assert len(result) > 0

    @pytest.mark.slow
    def test_discover_large_codebase(self, benchmark, large_codebase: Path) -> None:
        """Benchmark discovery on large codebase."""
        from remora.discovery import TreeSitterDiscoverer

        discoverer = TreeSitterDiscoverer(
            root_dirs=[large_codebase],
            languages={".py": "tree_sitter_python"},
            query_pack="remora_core",
        )

        result = benchmark(discoverer.discover)

        assert len(result) > 0
