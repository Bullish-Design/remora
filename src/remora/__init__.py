"""Remora public API surface."""

from remora.core.agent_context import AgentContext
from remora.core.cairn_bridge import CairnWorkspaceService
from remora.core.cairn_externals import CairnExternals
from remora.core.config import (
    Config,
    load_config,
    serialize_config,
)

from remora.core.discovery import (
    CSTNode,
    LANGUAGE_EXTENSIONS,
    compute_node_id,
    compute_source_hash,
    discover,
)
from remora.core.errors import (
    ConfigError,
    DiscoveryError,
    ExecutionError,
    RemoraError,
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
    FileSavedEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    KernelEndEvent,
    KernelStartEvent,
    ManualTriggerEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
    CoreEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from remora.core.swarm_executor import SwarmExecutor
from remora.core.subscriptions import Subscription, SubscriptionPattern, SubscriptionRegistry
from remora.core.reconciler import (
    get_agent_dir,
    get_agent_workspace_path,
    reconcile_on_startup,
)
from remora.core.tools import RemoraGrailTool, build_virtual_fs, discover_grail_tools
from remora.core.workspace import AgentWorkspace, CairnDataProvider
from remora.utils import PathResolver, to_project_relative

__all__ = [
    "AgentContext",
    "Config",
    "ConfigError",
    "DiscoveryError",
    "ExecutionError",
    "RemoraError",
    "WorkspaceError",
    "load_config",
    "serialize_config",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "AgentMessageEvent",
    "AgentStartEvent",
    "ContentChangedEvent",
    "FileSavedEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
    "KernelEndEvent",
    "KernelStartEvent",
    "ManualTriggerEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "NodeDiscoveredEvent",
    "NodeRemovedEvent",
    "CoreEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "TurnCompleteEvent",
    "EventBus",
    "EventHandler",
    "EventStore",
    "SwarmExecutor",
    "CSTNode",
    "LANGUAGE_EXTENSIONS",
    "compute_node_id",
    "compute_source_hash",
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
    "get_agent_dir",
    "get_agent_workspace_path",
    "reconcile_on_startup",
]
