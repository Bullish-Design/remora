"""Source file parsing using tree-sitter."""

from __future__ import annotations

import logging
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Tree

from remora.discovery.models import DiscoveryError
from remora.errors import DISC_004

logger = logging.getLogger(__name__)

PY_LANGUAGE = Language(tspython.language())


class SourceParser:
    """Parses Python source files into tree-sitter Trees.

    Usage:
        parser = SourceParser()
        tree, source_bytes = parser.parse_file(Path("example.py"))
        # tree is a tree_sitter.Tree
        # source_bytes is the raw file content as bytes
    """

    def __init__(self) -> None:
        self._parser = Parser(PY_LANGUAGE)

    def parse_file(self, file_path: Path) -> tuple[Tree, bytes]:
        """Parse a Python file and return (tree, source_bytes).

        Args:
            file_path: Path to a .py file.

        Returns:
            Tuple of (parsed Tree, raw source bytes).

        Raises:
            DiscoveryError: If the file cannot be read.
        """
        resolved = file_path.resolve()
        try:
            source_bytes = resolved.read_bytes()
        except OSError as exc:
            raise DiscoveryError(DISC_004, f"Failed to read source file: {resolved}") from exc

        tree = self._parser.parse(source_bytes)
        if tree.root_node.has_error:
            logger.warning("Parse errors in %s (continuing with partial tree)", resolved)

        return tree, source_bytes

    def parse_bytes(self, source_bytes: bytes) -> Tree:
        """Parse raw bytes and return a tree-sitter Tree.

        Useful for testing without writing to disk.
        """
        return self._parser.parse(source_bytes)
