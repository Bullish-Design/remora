"""Tree-sitter backed node discovery for Remora."""

from __future__ import annotations

import importlib.resources
import logging
import time
from pathlib import Path
from typing import Iterable

from remora.discovery.match_extractor import MatchExtractor
from remora.discovery.models import CSTNode, DiscoveryError, NodeType, compute_node_id
from remora.discovery.query_loader import CompiledQuery, QueryLoader
from remora.discovery.source_parser import SourceParser

logger = logging.getLogger(__name__)


def _default_query_dir() -> Path:
    """Return the built-in query directory inside the remora package."""
    return Path(importlib.resources.files("remora")) / "queries"  # type: ignore[arg-type]


class TreeSitterDiscoverer:
    """Discovers code nodes by parsing Python files with tree-sitter.

    Usage:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[Path("./src")],
            language="python",
            query_pack="remora_core",
        )
        nodes = discoverer.discover()
    """

    def __init__(
        self,
        root_dirs: Iterable[Path],
        language: str,
        query_pack: str,
        *,
        query_dir: Path | None = None,
        event_emitter=None,
    ) -> None:
        self.root_dirs = [Path(p).resolve() for p in root_dirs]
        self.language = language
        self.query_pack = query_pack
        self.query_dir = query_dir or _default_query_dir()
        self.event_emitter = event_emitter

        self._parser = SourceParser()
        self._loader = QueryLoader()
        self._extractor = MatchExtractor()

    def discover(self) -> list[CSTNode]:
        """Walk root_dirs, parse .py files, run queries, return CSTNodes.

        Emits a discovery event with timing if an event_emitter is set.
        """
        start = time.monotonic()
        status = "ok"
        try:
            queries = self._loader.load_query_pack(self.query_dir, self.language, self.query_pack)
            py_files = self._collect_files()
            all_nodes: list[CSTNode] = []
            for file_path in py_files:
                try:
                    tree, source_bytes = self._parser.parse_file(file_path)
                    nodes = self._extractor.extract(file_path, tree, source_bytes, queries)
                    all_nodes.extend(nodes)
                except DiscoveryError:
                    logger.warning("Skipping %s due to parse error", file_path)
                    continue
            all_nodes.sort(key=lambda n: (str(n.file_path), n.start_byte, n.node_type.value, n.name))
            return all_nodes
        except Exception:
            status = "error"
            raise
        finally:
            if self.event_emitter is not None:
                duration_ms = int((time.monotonic() - start) * 1000)
                self.event_emitter.emit(
                    {
                        "event": "discovery",
                        "phase": "discovery",
                        "status": status,
                        "duration_ms": duration_ms,
                    }
                )

    def _collect_files(self) -> list[Path]:
        """Walk root_dirs and collect all .py files."""
        files: list[Path] = []
        for root in self.root_dirs:
            if root.is_file() and root.suffix == ".py":
                files.append(root)
            elif root.is_dir():
                files.extend(sorted(root.rglob("*.py")))
        return files
