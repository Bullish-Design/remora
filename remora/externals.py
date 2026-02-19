from __future__ import annotations

from typing import Any, Callable

from cairn.runtime.external_functions import create_external_functions
from fsdantic import Workspace


def create_remora_externals(
    agent_id: str,
    node_source: str,
    node_metadata: dict[str, Any],
    agent_fs: Workspace,
    stable_fs: Workspace,
) -> dict[str, Callable]:
    """Create external functions available to Remora's .pym tools.

    Extends Cairn's base externals with Remora-specific functions
    like node context access.

    Args:
        agent_id: Unique agent identifier.
        node_source: Source code of the node being analyzed.
        node_metadata: Metadata dict for the node (name, type, etc).
        agent_fs: The agent's private workspace filesystem.
        stable_fs: The read-only backing filesystem (codebase).

    Returns:
        Dictionary of functions to inject into the Grail script.
    """
    base_externals = create_external_functions(agent_id, agent_fs, stable_fs)

    async def get_node_source() -> str:
        """Return the source code of the current node being analyzed."""
        return node_source

    async def get_node_metadata() -> dict[str, str]:
        """Return metadata about the current node."""
        return node_metadata

    # Remora-specific overrides or additions
    base_externals["get_node_source"] = get_node_source
    base_externals["get_node_metadata"] = get_node_metadata

    return base_externals
