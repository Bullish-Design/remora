# demo/lsp/__init__.py
"""Demo LSP module - re-exports from src/remora/lsp for backward compatibility."""

from remora.lsp import RemoraLanguageServer
from remora.lsp.server import server
from remora.lsp.server import main

__all__ = ["server", "main", "RemoraLanguageServer"]
