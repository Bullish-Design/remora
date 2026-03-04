"""Companion LSP server for receiving cursor notifications from editors.

This is a lightweight LSP server that:
1. Receives cursor position notifications from Neovim
2. Forwards them to the CompanionRuntime
3. Serves the composed sidebar on request

Usage:
    # Start via command line
    companion-lsp --workspace /path/to/project

    # Or programmatically
    from remora_demo.companion.lsp.server import start_server
    start_server(workspace_path="/path/to/project")
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from remora_demo.companion.runtime import CompanionConfig, CompanionRuntime

logger = logging.getLogger("companion.lsp")


class CompanionLanguageServer(LanguageServer):
    """LSP server for Companion integration with editors.

    Handles:
    - $/companion/cursorMoved: cursor position notifications
    - $/companion/getSidebar: request current sidebar content
    - textDocument/didOpen: track open documents
    - textDocument/didChange: track edits (optional)
    """

    def __init__(self, config: CompanionConfig | None = None) -> None:
        super().__init__(name="companion", version="0.1.0")
        self.config = config or CompanionConfig()
        self._runtime: CompanionRuntime | None = None
        self._runtime_started = False
        self._start_lock = asyncio.Lock()

    @property
    def runtime(self) -> CompanionRuntime:
        """Get the Companion runtime (lazy initialization)."""
        if self._runtime is None:
            self._runtime = CompanionRuntime(self.config)
        return self._runtime

    async def ensure_runtime_started(self) -> None:
        """Ensure the runtime is started (idempotent)."""
        async with self._start_lock:
            if not self._runtime_started:
                await self.runtime.start()
                self._runtime_started = True
                logger.info("Companion runtime started")

    async def shutdown_runtime(self) -> None:
        """Shutdown the runtime gracefully."""
        if self._runtime and self._runtime_started:
            await self._runtime.stop()
            self._runtime_started = False
            logger.info("Companion runtime stopped")


# Create server singleton
_server: CompanionLanguageServer | None = None


def get_server(config: CompanionConfig | None = None) -> CompanionLanguageServer:
    """Get the global CompanionLanguageServer singleton."""
    global _server
    if _server is None:
        _server = CompanionLanguageServer(config)
        _register_handlers(_server)
    return _server


def _register_handlers(server: CompanionLanguageServer) -> None:
    """Register all LSP handlers on the server."""

    # ========================================
    # Standard LSP Lifecycle
    # ========================================

    @server.feature(lsp.INITIALIZE)
    async def on_initialize(params: lsp.InitializeParams) -> lsp.InitializeResult:
        """Handle LSP initialization."""
        logger.info("Companion LSP initializing...")

        # Update workspace path from client
        if params.root_uri:
            root_path = to_fs_path(params.root_uri)
            server.config.workspace_path = Path(root_path)
            logger.info(f"Workspace: {root_path}")

        # Start the runtime
        await server.ensure_runtime_started()

        return lsp.InitializeResult(
            capabilities=lsp.ServerCapabilities(
                text_document_sync=lsp.TextDocumentSyncOptions(
                    open_close=True,
                    change=lsp.TextDocumentSyncKind.Incremental,
                ),
                # We don't provide traditional LSP features
                hover_provider=False,
                completion_provider=None,
                code_action_provider=False,
            ),
            server_info=lsp.ServerInfo(name="companion", version="0.1.0"),
        )

    @server.feature(lsp.SHUTDOWN)
    async def on_shutdown(params: Any) -> None:
        """Handle LSP shutdown."""
        logger.info("Companion LSP shutting down...")
        await server.shutdown_runtime()

    # ========================================
    # Document Sync (for context)
    # ========================================

    @server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
    async def on_did_open(params: lsp.DidOpenTextDocumentParams) -> None:
        """Track when documents are opened."""
        uri = params.text_document.uri
        file_path = to_fs_path(uri)
        logger.debug(f"Document opened: {file_path}")
        # Could trigger indexing or context extraction here

    @server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
    async def on_did_change(params: lsp.DidChangeTextDocumentParams) -> None:
        """Track document changes (edits)."""
        uri = params.text_document.uri
        file_path = to_fs_path(uri)

        # Forward content changes to runtime
        for change in params.content_changes:
            if isinstance(change, lsp.TextDocumentContentChangeEvent_Type1):
                # Incremental change with range
                start_line = change.range.start.line
                end_line = change.range.end.line
                text = change.text
                await server.runtime.on_content_edited(file_path, start_line, end_line, text)
            else:
                # Full document sync (change is TextDocumentContentChangeEvent_Type2)
                # For full sync, we'd need to diff - skip for now
                logger.debug(f"Full document sync for {file_path} (not forwarding)")

    # ========================================
    # Companion-specific notifications
    # ========================================

    @server.feature("$/companion/cursorMoved")
    async def on_cursor_moved(params: dict) -> None:
        """Handle cursor position updates from editor.

        Expected params:
            uri: str - document URI
            line: int - 0-indexed line number
            col: int - 0-indexed column number (optional)
        """
        try:
            # Normalize params (pygls may pass attrs object)
            if not isinstance(params, dict):
                params = {
                    "uri": getattr(params, "uri", None),
                    "line": getattr(params, "line", None),
                    "col": getattr(params, "col", 0),
                }

            uri = params.get("uri")
            line = params.get("line")
            col = params.get("col", 0)

            if not uri or line is None:
                logger.warning("Invalid cursorMoved params: missing uri or line")
                return

            file_path = to_fs_path(uri)
            logger.debug(f"Cursor moved: {file_path}:{line}:{col}")

            await server.runtime.on_cursor_moved(file_path, line, col)

        except Exception:
            logger.exception("Error in on_cursor_moved handler")

    @server.feature("$/companion/getSidebar")
    async def on_get_sidebar(params: dict) -> dict:
        """Request the current sidebar content.

        Returns:
            markdown: str - the composed sidebar markdown
            timestamp: float - when the sidebar was last updated
        """
        try:
            sidebar = await server.runtime.get_sidebar()
            return {
                "markdown": sidebar or "",
                "timestamp": 0.0,  # TODO: track actual timestamp
            }
        except Exception:
            logger.exception("Error in on_get_sidebar handler")
            return {"markdown": "", "timestamp": 0.0, "error": "Failed to get sidebar"}

    @server.feature("$/companion/getContext")
    async def on_get_context(params: dict) -> dict:
        """Get the current context state for debugging."""
        try:
            return await server.runtime.get_context()
        except Exception:
            logger.exception("Error in on_get_context handler")
            return {}

    @server.feature("$/companion/getActivations")
    async def on_get_activations(params: dict) -> list:
        """Get agent activations for timeline visualization."""
        try:
            return server.runtime.get_activations()
        except Exception:
            logger.exception("Error in on_get_activations handler")
            return []


def start_server(
    workspace_path: str | Path | None = None,
    sidebar_output_path: str | Path | None = None,
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B",
    auto_index: bool = True,
) -> None:
    """Start the Companion LSP server (blocking).

    Args:
        workspace_path: Root directory to index and watch
        sidebar_output_path: File to write sidebar markdown to
        embedding_model: Sentence transformer model for embeddings
        auto_index: Whether to index workspace on startup
    """
    config = CompanionConfig(
        workspace_path=Path(workspace_path) if workspace_path else Path.cwd(),
        sidebar_output_path=Path(sidebar_output_path) if sidebar_output_path else None,
        embedding_model=embedding_model,
        auto_index=auto_index,
    )

    server = get_server(config)

    # Run the server
    logger.info("Starting Companion LSP server...")
    server.start_io()


def main() -> None:
    """CLI entrypoint for companion-lsp command."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="Companion LSP Server")
    parser.add_argument(
        "--workspace",
        "-w",
        type=str,
        default=None,
        help="Workspace directory to index",
    )
    parser.add_argument(
        "--sidebar-output",
        "-o",
        type=str,
        default=None,
        help="File to write sidebar markdown to",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default="Qwen/Qwen3-Embedding-0.6B",
        help="Sentence transformer model for embeddings",
    )
    parser.add_argument(
        "--no-auto-index",
        action="store_true",
        help="Skip automatic indexing on startup",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("companion").setLevel(logging.DEBUG)

    start_server(
        workspace_path=args.workspace,
        sidebar_output_path=args.sidebar_output,
        embedding_model=args.embedding_model,
        auto_index=not args.no_auto_index,
    )


if __name__ == "__main__":
    main()
