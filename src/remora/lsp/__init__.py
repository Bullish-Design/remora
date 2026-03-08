"""Remora LSP server package."""
from remora.lsp.db import RemoraDB
from remora.lsp.graph import LazyGraph
from remora.lsp.server import RemoraLanguageServer


def main() -> None:
    """Compatibility entrypoint for existing remora-lsp console scripts."""
    from remora.lsp.__main__ import main as _main

    _main()


__all__ = [
    "RemoraDB",
    "LazyGraph",
    "RemoraLanguageServer",
    "main",
]
