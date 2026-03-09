"""Bootstrap runtime package."""

from remora.bootstrap.activation import ActivationResult, default_agent_id, handle_agent_needed
from remora.bootstrap.bedrock import (
    BootstrapEvent,
    build_bedrock,
    extract_workspace_tools,
    make_files_provider,
)
from remora.bootstrap.coordinator import AgentNeededPlan, emit_agent_needed_events, find_unassigned_modules
from remora.bootstrap.runner import BootstrapRunner, run_bootstrap
from remora.bootstrap.schema_loader import (
    ContextStep,
    SubscriptionSpec,
    TurnSchema,
    load_schema,
    resolve_context_vars,
)
from remora.bootstrap.seed_graph import seed_coordinator_node, seed_module_nodes_from_filesystem, seed_modules_if_empty
from remora.bootstrap.turn_executor import TurnExecutor, TurnResult

__all__ = [
    "ActivationResult",
    "default_agent_id",
    "handle_agent_needed",
    "BootstrapEvent",
    "build_bedrock",
    "make_files_provider",
    "extract_workspace_tools",
    "AgentNeededPlan",
    "find_unassigned_modules",
    "emit_agent_needed_events",
    "ContextStep",
    "SubscriptionSpec",
    "TurnSchema",
    "load_schema",
    "resolve_context_vars",
    "BootstrapRunner",
    "run_bootstrap",
    "seed_module_nodes_from_filesystem",
    "seed_coordinator_node",
    "seed_modules_if_empty",
    "TurnExecutor",
    "TurnResult",
]
