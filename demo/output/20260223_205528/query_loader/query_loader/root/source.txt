"""Query loading and compilation for tree-sitter."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from tree_sitter import Language, Query

from remora.discovery.models import DiscoveryError

logger = logging.getLogger(__name__)


class CompiledQuery:
    """A compiled tree-sitter query with metadata."""

    def __init__(self, query: Query, source_file: Path, query_text: str, query_name: str) -> None:
        self.query = query
        self.source_file = source_file
        self.query_text = query_text
        self._query_name = query_name

    @property
    def name(self) -> str:
        """Query name derived from filename (e.g. 'function' from 'function.scm')."""
        return self._query_name


class QueryLoader:
    """Loads and compiles tree-sitter queries from .scm files.

    Usage:
        loader = QueryLoader()
        queries = loader.load_query_pack(
            query_dir=Path("src/remora/queries"),
            language="python",
            query_pack="remora_core",
        )
    """

    def load_query_pack(
        self,
        query_dir: Path,
        language: str,
        query_pack: str,
    ) -> list[CompiledQuery]:
        """Load all .scm files from a query pack directory.

        Args:
            query_dir: Root query directory (e.g. src/remora/queries/).
            language: Language subdirectory (e.g. "python", "toml", "markdown").
            query_pack: Query pack subdirectory (e.g. "remora_core").

        Returns:
            List of compiled queries.

        Raises:
            DiscoveryError: If query pack directory doesn't exist or a query has syntax errors.
        """
        pack_dir = query_dir / language / query_pack
        if not pack_dir.is_dir():
            raise DiscoveryError(
                f"Query pack directory not found: {pack_dir}",
            )

        scm_files = sorted(pack_dir.glob("*.scm"))
        if not scm_files:
            raise DiscoveryError(
                f"No .scm query files found in: {pack_dir}",
            )

        # Dynamically load the language for query compilation
        grammar_module = f"tree_sitter_{language}"
        try:
            grammar_pkg = importlib.import_module(grammar_module)
        except ImportError as exc:
            raise DiscoveryError(f"Failed to import grammar module: {grammar_module}") from exc

        ts_language = Language(grammar_pkg.language())

        compiled: list[CompiledQuery] = []
        for scm_file in scm_files:
            compiled.append(self._compile_query(scm_file, ts_language))

        logger.info(
            "Loaded %d queries from %s/%s: %s",
            len(compiled),
            language,
            query_pack,
            [q.name for q in compiled],
        )
        return compiled

    def _compile_query(self, scm_file: Path, ts_language: Language) -> CompiledQuery:
        """Compile a single .scm file into a tree-sitter Query."""
        try:
            query_text = scm_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise DiscoveryError(f"Failed to read query file: {scm_file}") from exc

        try:
            query = Query(ts_language, query_text)
        except Exception as exc:
            raise DiscoveryError(f"Query syntax error in {scm_file.name}: {exc}") from exc

        return CompiledQuery(
            query=query,
            source_file=scm_file,
            query_text=query_text,
            query_name=scm_file.stem,
        )
