"""Node State Hub - Background indexing daemon for Remora.

The Hub maintains a live index of codebase metadata, providing
instant context to Remora agents without expensive AST parsing.

Architecture:
- HubDaemon: Background process that watches and indexes files
- NodeStateStore: FSdantic-backed storage for NodeState records
- HubClient: Read-only client with "Lazy Daemon" fallback

Usage:
    # Start daemon (CLI)
    $ remora-hub start

    # Use in code
    from remora.hub import HubClient
    client = HubClient()
    context = await client.get_context(["node:/path/to/file.py:func"])
"""

from remora.hub.models import NodeState, FileIndex, HubStatus

__all__ = [
    "NodeState",
    "FileIndex",
    "HubStatus",
]
