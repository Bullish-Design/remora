from __future__ import annotations

from remora.lsp.protocols import LspServer
from remora.lsp.handlers.companion import register_companion_handlers


def register_handlers(server: LspServer) -> None:
    """Register all LSP handlers on the server instance."""
    if getattr(server, "_handlers_registered", False):
        return
    server._handlers_registered = True

    from remora.lsp.handlers.actions import register_action_handlers
    from remora.lsp.handlers.capabilities import register_capability_handlers
    from remora.lsp.handlers.commands import register_command_handlers
    from remora.lsp.handlers.documents import register_document_handlers
    from remora.lsp.handlers.hover import register_hover_handlers
    from remora.lsp.handlers.lens import register_lens_handlers
    from remora.lsp.notifications import register_notification_handlers

    register_command_handlers(server)
    register_document_handlers(server)
    register_action_handlers(server)
    register_capability_handlers(server)
    register_hover_handlers(server)
    register_lens_handlers(server)
    register_notification_handlers(server)
    register_companion_handlers(server)


__all__ = ["register_handlers"]
