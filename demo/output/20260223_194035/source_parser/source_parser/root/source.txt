"""Source file parsing using tree-sitter."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from tree_sitter import Language, Parser, Tree

from remora.discovery.models import DiscoveryError

logger = logging.getLogger(__name__)


class SourceParser:
    """Parses source files into tree-sitter Trees.

    Dynamically loads the appropriate tree-sitter grammar based on the
    grammar_module parameter (e.g., "tree_sitter_python", "tree_sitter_toml").

    Usage:
        parser = SourceParser("tree_sitter_python")
        tree, source_bytes = parser.parse_file(Path("example.py"))
    """

    def __init__(self, grammar_module: str) -> None:
        """Initialize parser with a specific grammar module.

        Args:
            grammar_module: The tree-sitter grammar module name,
                           e.g., "tree_sitter_python", "tree_sitter_toml".
        """
        try:
            grammar_pkg = importlib.import_module(grammar_module)
        except ImportError as exc:
            raise DiscoveryError(f"Failed to import grammar module: {grammar_module}") from exc

        self._language = Language(grammar_pkg.language())
        self._parser = Parser(self._language)
        self._grammar_module = grammar_module

    @property
    def language(self) -> Language:
        """Return the tree-sitter Language object."""
        return self._language

    def parse_file(self, file_path: Path) -> tuple[Tree, bytes]:
        """Parse a source file and return (tree, source_bytes).

        Args:
            file_path: Path to the source file.

        Returns:
            Tuple of (parsed Tree, raw source bytes).

        Raises:
            DiscoveryError: If the file cannot be read.
        """
        resolved = file_path.resolve()
        try:
            source_bytes = resolved.read_bytes()
        except OSError as exc:
            raise DiscoveryError(f"Failed to read source file: {resolved}") from exc

        tree = self._parser.parse(source_bytes)
        if tree.root_node.has_error:
            logger.warning("Parse errors in %s (continuing with partial tree)", resolved)

        return tree, source_bytes

    def parse_bytes(self, source_bytes: bytes) -> Tree:
        """Parse raw bytes and return a tree-sitter Tree.

        Useful for testing without writing to disk.
        """
        return self._parser.parse(source_bytes)
