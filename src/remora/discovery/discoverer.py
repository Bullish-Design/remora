"""Tree-sitter backed node discovery for Remora."""

from __future__ import annotations

import concurrent.futures
import importlib.resources
import logging
import time
from enum import Enum
from pathlib import Path
from typing import Iterable

from remora.config import LANGUAGES
from remora.discovery.match_extractor import MatchExtractor
from remora.discovery.models import CSTNode, DiscoveryError
from remora.discovery.query_loader import QueryLoader
from remora.discovery.source_parser import SourceParser


class EventName(str, Enum):
    """Event names for discovery."""

    DISCOVERY = "discovery"


class EventStatus(str, Enum):
    """Event status values."""

    OK = "ok"
    ERROR = "error"


logger = logging.getLogger(__name__)


def _default_query_dir() -> Path:
    """Return the built-in query directory inside the remora package."""
    return Path(importlib.resources.files("remora")) / "queries"  # type: ignore[arg-type]


class TreeSitterDiscoverer:
    """Discovers code nodes by parsing source files with tree-sitter.

    Supports multiple languages as configured in LANGUAGES dict.

    Note:
        Discovery is synchronous; use ``asyncio.to_thread`` if calling from
        an async workflow.

    Usage:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[Path("./src")],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()
    """

    def __init__(
        self,
        root_dirs: Iterable[Path],
        query_pack: str = "remora_core",
        *,
        query_dir: Path | None = None,
        event_emitter=None,
        languages: dict[str, str] | None = None,
    ) -> None:
        """Initialize the discoverer.

        Args:
            root_dirs: Directories or files to scan.
            query_pack: Query pack name (default: "remora_core").
            query_dir: Custom query directory (default: built-in queries).
            event_emitter: Optional event emitter for discovery events.
            languages: Override LANGUAGES dict (default: use remora.config.LANGUAGES).
        """
        self.root_dirs = [Path(p).resolve() for p in root_dirs]
        self.query_pack = query_pack
        self.query_dir = query_dir or _default_query_dir()
        self.event_emitter = event_emitter
        self._languages = languages or LANGUAGES

    def discover(self) -> list[CSTNode]:
        """Walk root_dirs, parse files, run queries, return CSTNodes.

        Iterates over all configured languages, collecting files by extension,
        parsing them with the appropriate tree-sitter grammar, and extracting
        nodes using the corresponding query pack.

        Emits a discovery event with timing if an event_emitter is set.
        """
        start = time.monotonic()
        status = EventStatus.OK

        try:
            all_nodes: list[CSTNode] = []

            # Group extensions by language for efficient processing
            ext_to_language: dict[str, str] = {}
            for ext, grammar_module in self._languages.items():
                language = grammar_module.replace("tree_sitter_", "")
                ext_to_language[ext] = language

            # Check which languages have query packs
            languages_with_queries: dict[str, list[str]] = {}
            for ext, language in ext_to_language.items():
                pack_dir = self.query_dir / language / self.query_pack
                if pack_dir.is_dir():
                    if language not in languages_with_queries:
                        languages_with_queries[language] = []
                    languages_with_queries[language].append(ext)

            # Process each language
            for language, extensions in languages_with_queries.items():
                grammar_module = f"tree_sitter_{language}"
                files = self._collect_files(set(extensions))

                if not files:
                    continue

                # Load queries once per language
                loader = QueryLoader()
                try:
                    queries = loader.load_query_pack(self.query_dir, language, self.query_pack)
                except DiscoveryError as e:
                    logger.warning("Skipping language %s: %s", language, e)
                    continue

                # Parse files in parallel
                def _parse_single(file_path: Path) -> list[CSTNode]:
                    try:
                        parser = SourceParser(grammar_module)
                        extractor = MatchExtractor()
                        tree, source_bytes = parser.parse_file(file_path)
                        return extractor.extract(file_path, tree, source_bytes, queries)
                    except DiscoveryError:
                        logger.warning("Skipping %s due to parse error", file_path)
                        return []

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    results_generator = executor.map(_parse_single, files)
                    for nodes in results_generator:
                        all_nodes.extend(nodes)

            # Deduplicate and sort
            seen_ids: set[str] = set()
            unique_nodes: list[CSTNode] = []
            for node in all_nodes:
                if node.node_id not in seen_ids:
                    seen_ids.add(node.node_id)
                    unique_nodes.append(node)

            unique_nodes.sort(key=lambda n: (str(n.file_path), n.start_byte, n.node_type, n.name))
            return unique_nodes

        except Exception:
            status = EventStatus.ERROR
            raise
        finally:
            if self.event_emitter is not None:
                duration_ms = int((time.monotonic() - start) * 1000)
                self.event_emitter.emit(
                    {
                        "event": EventName.DISCOVERY,
                        "phase": "discovery",
                        "status": status,
                        "duration_ms": duration_ms,
                    }
                )

    def _collect_files(self, extensions: set[str]) -> list[Path]:
        """Walk root_dirs and collect files matching the given extensions."""
        files: list[Path] = []
        for root in self.root_dirs:
            if root.is_file() and root.suffix in extensions:
                files.append(root)
            elif root.is_dir():
                for ext in extensions:
                    files.extend(sorted(root.rglob(f"*{ext}")))
        return files
