"""Incremental parser state cache scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from tree_sitter import Language, Parser


@dataclass
class CachedTree:
    """Cached parse tree and source bytes per file."""

    source: bytes
    tree: object


class ParserCache:
    """Per-language parser cache and per-file tree state."""

    def __init__(self) -> None:
        self._parsers: dict[str, Parser] = {}
        self._trees: dict[str, CachedTree] = {}

    def parser_for(self, language: str) -> Parser:
        """Get/create parser for a language module such as tree_sitter_python."""

        parser = self._parsers.get(language)
        if parser is not None:
            return parser

        module = import_module(f"tree_sitter_{language}")
        parser = Parser(Language(module.language()))
        self._parsers[language] = parser
        return parser

    def get_cached_tree(self, key: str) -> CachedTree | None:
        """Return cached parse info by file key."""

        return self._trees.get(key)

    def set_cached_tree(self, key: str, source: bytes, tree: object) -> None:
        """Store parse state after parse/update."""

        self._trees[key] = CachedTree(source=source, tree=tree)
