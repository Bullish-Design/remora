"""Code discovery/projection/reconciliation."""

from remora.core.code.discovery import CSTNode, LANGUAGE_EXTENSIONS, compute_node_id, compute_source_hash, discover, parse_content
from remora.core.code.projections import NodeProjection
from remora.core.code.reconciler import get_agent_dir, get_agent_workspace_path, reconcile_on_startup

__all__ = [
    "CSTNode",
    "LANGUAGE_EXTENSIONS",
    "NodeProjection",
    "compute_node_id",
    "compute_source_hash",
    "discover",
    "get_agent_dir",
    "get_agent_workspace_path",
    "parse_content",
    "reconcile_on_startup",
]
