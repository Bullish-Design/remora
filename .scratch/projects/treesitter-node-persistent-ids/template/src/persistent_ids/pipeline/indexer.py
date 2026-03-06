"""Repository indexing pipeline scaffold."""

from __future__ import annotations

from pathlib import Path

from persistent_ids.extractors import MarkdownExtractor, PythonExtractor
from persistent_ids.parser_cache import ParserCache
from persistent_ids.settings import IndexerSettings
from persistent_ids.storage.sqlite_store import SQLiteStore


class PersistentIdIndexer:
    """High-level orchestrator for parse, extract, and persistence."""

    def __init__(self, settings: IndexerSettings) -> None:
        self._settings = settings
        self._parser_cache = ParserCache()
        self._store = SQLiteStore(settings.db_path)
        self._extractors = {
            "python": PythonExtractor(),
            "markdown": MarkdownExtractor(),
        }

    def init_db(self) -> None:
        """Initialize schema in the configured SQLite database."""

        schema_path = Path(__file__).resolve().parents[1] / "storage" / "schema.sql"
        self._store.init_schema(schema_path)

    def index_paths(self) -> None:
        """Scan configured repo globs and index matching files.

        TODO: implement file walking, language detection, extraction, and UPSERT writes.
        """

        root = self._settings.repo_root
        for glob in self._settings.include_globs:
            for path in root.glob(glob):
                if path.is_file():
                    self.index_file(path)

    def index_file(self, path: Path) -> None:
        """Index one file using language-specific extractor.

        TODO: wire parser/query execution and persistence writes.
        """

        suffix_to_language = {".py": "python", ".md": "markdown"}
        language = suffix_to_language.get(path.suffix)
        if language is None:
            return

        parser = self._parser_cache.parser_for(language)
        source = path.read_bytes()
        tree = parser.parse(source)
        extractor = self._extractors[language]
        _ = extractor.extract(tree, source)

    def close(self) -> None:
        """Release external resources."""

        self._store.close()
