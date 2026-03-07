"""Remora public API surface."""

import os

# Avoid startup network fetch noise in offline/dev environments.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")

from remora.core.agents.agent_context import AgentContext
from remora.core.agents.cairn_bridge import CairnWorkspaceService
from remora.core.agents.cairn_externals import CairnExternals
from remora.core.config import (
    Config,
    load_config,
    serialize_config,
)

from remora.core.code.discovery import (
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
from remora.core.events import CoreEvent
from remora.core.events.agent_events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
)
from remora.core.events.event_bus import EventBus, EventHandler
from remora.core.events.interaction_events import (
    AgentMessageEvent,
    ContentChangedEvent,
    FileSavedEvent,
    ManualTriggerEvent,
)
from remora.core.events.kernel_events import (
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from remora.core.events.code_events import NodeDiscoveredEvent, NodeRemovedEvent
from remora.core.store.event_store import EventStore
from remora.core.agents.swarm_executor import SwarmExecutor
from remora.core.events.subscriptions import Subscription, SubscriptionPattern, SubscriptionRegistry
from remora.core.code.reconciler import (
    get_agent_dir,
    get_agent_workspace_path,
    reconcile_on_startup,
)
from remora.core.tools import RemoraGrailTool, build_virtual_fs, discover_grail_tools
from remora.core.agents.workspace import AgentWorkspace, CairnDataProvider
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
