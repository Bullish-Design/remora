"""Remora public API surface."""

from remora.core.cairn_bridge import CairnWorkspaceService
from remora.core.cairn_externals import CairnExternals
from remora.core.config import (
    Config,
    ConfigError,
    load_config,
    serialize_config,
)

from remora.core.discovery import (
    CSTNode,
    LANGUAGE_EXTENSIONS,
    NodeType,
    TreeSitterDiscoverer,
    compute_node_id,
    discover,
)
from remora.core.errors import (
    ConfigError,
    DiscoveryError,
    ExecutionError,
    RemoraError,
    SwarmError,
    WorkspaceError,
)
from remora.core.event_bus import EventBus, EventHandler
from remora.core.event_store import EventStore
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentMessageEvent,
    AgentStartEvent,
    ContentChangedEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    RemoraEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from remora.core.agent_state import AgentState
from remora.core.agent_runner import AgentRunner, ExecutionContext
from remora.core.swarm_executor import SwarmExecutor
from remora.core.subscriptions import Subscription, SubscriptionPattern, SubscriptionRegistry
from remora.core.swarm_state import AgentMetadata, SwarmState
from remora.core.reconciler import (
    get_agent_dir,
    get_agent_state_path,
    get_agent_workspace_path,
    reconcile_on_startup,
)
from remora.core.tools import RemoraGrailTool, build_virtual_fs, discover_grail_tools
from remora.core.workspace import AgentWorkspace, CairnDataProvider
from remora.utils import PathResolver, to_project_relative

__all__ = [
    "Config",
    "ConfigError",
    "DiscoveryError",
    "ExecutionError",
    "RemoraError",
    "SwarmError",
    "WorkspaceError",
    "load_config",
    "serialize_config",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "AgentMessageEvent",
    "AgentStartEvent",
    "ContentChangedEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
    "KernelEndEvent",
    "KernelStartEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "RemoraEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "TurnCompleteEvent",
    "EventBus",
    "EventHandler",
    "EventStore",
    "AgentState",
    "AgentRunner",
    "ExecutionContext",
    "SwarmExecutor",
    "CSTNode",
    "LANGUAGE_EXTENSIONS",
    "NodeType",
    "TreeSitterDiscoverer",
    "compute_node_id",
    "discover",
    "AgentWorkspace",
    "CairnDataProvider",
    "CairnExternals",
    "build_virtual_fs",
    "discover_grail_tools",
    "PathResolver",
    "to_project_relative",
    "Subscription",
    "SubscriptionPattern",
    "SubscriptionRegistry",
    "SwarmState",
    "AgentMetadata",
    "get_agent_dir",
    "get_agent_state_path",
    "get_agent_workspace_path",
    "reconcile_on_startup",
]
