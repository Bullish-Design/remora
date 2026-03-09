"""Core event types, bus, and subscriptions."""

from remora.core.events.agent_events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentEvent,
    AgentStartEvent,
    AgentTextResponseEvent,
    HumanChatEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    RewriteAppliedEvent,
    RewriteProposalEvent,
    RewriteRejectedEvent,
)
from remora.core.events.code_events import NodeDiscoveredEvent, NodeRemovedEvent, ScaffoldRequestEvent
from remora.core.events.interaction_events import (
    AgentMessageEvent,
    ContentChangedEvent,
    CursorFocusEvent,
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

CoreEvent = (
    AgentStartEvent
    | AgentCompleteEvent
    | AgentErrorEvent
    | AgentEvent
    | AgentTextResponseEvent
    | HumanChatEvent
    | RewriteProposalEvent
    | RewriteAppliedEvent
    | RewriteRejectedEvent
    | HumanInputRequestEvent
    | HumanInputResponseEvent
    | AgentMessageEvent
    | FileSavedEvent
    | ContentChangedEvent
    | CursorFocusEvent
    | ManualTriggerEvent
    | NodeDiscoveredEvent
    | ScaffoldRequestEvent
    | NodeRemovedEvent
    | KernelStartEvent
    | KernelEndEvent
    | ToolCallEvent
    | ToolResultEvent
    | ModelRequestEvent
    | ModelResponseEvent
    | TurnCompleteEvent
)

from remora.core.events.event_bus import EventBus, EventHandler
from remora.core.events.subscriptions import Subscription, SubscriptionPattern, SubscriptionRegistry

__all__ = [
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "AgentMessageEvent",
    "AgentStartEvent",
    "AgentTextResponseEvent",
    "ContentChangedEvent",
    "CoreEvent",
    "CursorFocusEvent",
    "EventBus",
    "EventHandler",
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
    "ScaffoldRequestEvent",
    "Subscription",
    "SubscriptionPattern",
    "SubscriptionRegistry",
    "ToolCallEvent",
    "ToolResultEvent",
    "TurnCompleteEvent",
]
