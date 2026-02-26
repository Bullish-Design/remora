"""Tree-sitter backed node discovery for Remora."""

from pathlib import Path
from typing import Any

from remora.discovery.discoverer import TreeSitterDiscoverer
from remora.discovery.match_extractor import MatchExtractor
from remora.discovery.models import CSTNode, DiscoveryError, NodeType, compute_node_id
from remora.discovery.query_loader import CompiledQuery, QueryLoader
from remora.discovery.source_parser import SourceParser

__all__ = [
    "CSTNode",
    "CompiledQuery",
    "DiscoveryError",
    "MatchExtractor",
    "NodeType",
    "QueryLoader",
    "SourceParser",
    "TreeSitterDiscoverer",
    "compute_node_id",
    "discover",
]


def discover(
    paths: list[Path] | list[str],
    languages: list[str] | None = None,
    query_pack: str | None = None,
) -> list[CSTNode]:
    """Discover code nodes from source files.

    Args:
        paths: List of file or directory paths to scan
        languages: List of languages to scan (default: python)
        query_pack: Optional query pack name

    Returns:
        List of CSTNode objects representing discovered code nodes
    """
    if languages is None:
        languages = ["python"]

    path_objects = [Path(p) if isinstance(p, str) else p for p in paths]

    discoverer = TreeSitterDiscoverer(
        root_dirs=path_objects,
        query_pack=query_pack or "remora_core",
        languages={ext: lang for lang in languages for ext in _get_extensions(lang)},
    )

    return discoverer.discover()


def _get_extensions(language: str) -> list[str]:
    """Get file extensions for a language."""
    extensions = {
        "python": [".py", ".pyi"],
        "markdown": [".md"],
        "toml": [".toml"],
    }
    return extensions.get(language, [f".{language}"])
