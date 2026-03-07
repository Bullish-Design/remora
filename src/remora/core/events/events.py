"""Backward-compatible re-export barrel.

Import from the specific submodules instead:
  remora.core.events.agent_events
  remora.core.events.interaction_events
  remora.core.events.code_events
  remora.core.events.kernel_events

This barrel exists only to avoid breaking existing imports during the
transition. It will be deprecated once all internal imports are updated.
"""

from remora.core.events.agent_events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentEvent,
    AgentStartEvent,
    HumanChatEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    RewriteAppliedEvent,
    RewriteProposalEvent,
    RewriteRejectedEvent,
)
from remora.core.events.code_events import (
    NodeDiscoveredEvent,
    NodeRemovedEvent,
    ScaffoldRequestEvent,
)
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

__all__ = [
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "AgentEvent",
    "HumanChatEvent",
    "RewriteProposalEvent",
    "RewriteAppliedEvent",
    "RewriteRejectedEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
    "AgentMessageEvent",
    "FileSavedEvent",
    "ContentChangedEvent",
    "CursorFocusEvent",
    "ManualTriggerEvent",
    "NodeDiscoveredEvent",
    "ScaffoldRequestEvent",
    "NodeRemovedEvent",
    "KernelStartEvent",
    "KernelEndEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "TurnCompleteEvent",
    "CoreEvent",
]
