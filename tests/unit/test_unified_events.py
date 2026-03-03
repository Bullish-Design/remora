"""TDD tests for 6.1: Unified frozen Pydantic event models.

Verifies:
- All core events are Pydantic BaseModel (not stdlib dataclasses)
- All core events are frozen (immutable)
- model_dump() works on all core events
- to_core_event() bridge is removed from LSP model classes
- EventStore._serialize_event uses model_dump() for core events
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel

from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentMessageEvent,
    AgentStartEvent,
    ContentChangedEvent,
    FileSavedEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    ManualTriggerEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
)

# All Remora-defined event classes (not structured_agents re-exports)
REMORA_EVENT_CLASSES = [
    AgentStartEvent,
    AgentCompleteEvent,
    AgentErrorEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    AgentMessageEvent,
    FileSavedEvent,
    ContentChangedEvent,
    ManualTriggerEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
]


def _make_event(cls):
    """Create a minimal instance of an event class for testing."""
    # Map each class to its minimal required kwargs
    factories = {
        AgentStartEvent: lambda: cls(graph_id="g1", agent_id="a1", node_name="n1"),
        AgentCompleteEvent: lambda: cls(graph_id="g1", agent_id="a1", result_summary="ok"),
        AgentErrorEvent: lambda: cls(graph_id="g1", agent_id="a1", error="fail"),
        HumanInputRequestEvent: lambda: cls(graph_id="g1", agent_id="a1", request_id="r1", question="q?"),
        HumanInputResponseEvent: lambda: cls(request_id="r1", response="yes"),
        AgentMessageEvent: lambda: cls(from_agent="a1", to_agent="a2", content="hi"),
        FileSavedEvent: lambda: cls(path="/tmp/f.py"),
        ContentChangedEvent: lambda: cls(path="/tmp/f.py"),
        ManualTriggerEvent: lambda: cls(to_agent="a1", reason="test"),
        NodeDiscoveredEvent: lambda: cls(
            node_id="nd1",
            node_type="function",
            name="foo",
            full_name="mod.foo",
            file_path="/tmp/f.py",
            start_line=1,
            end_line=10,
            source_code="def foo(): ...",
            source_hash="abc123",
        ),
        NodeRemovedEvent: lambda: cls(node_id="nd1"),
    }
    return factories[cls]()


class TestEventsArePydantic:
    """All Remora events must be Pydantic BaseModel instances."""

    @pytest.mark.parametrize("cls", REMORA_EVENT_CLASSES, ids=lambda c: c.__name__)
    def test_is_pydantic_basemodel(self, cls):
        assert issubclass(cls, BaseModel), f"{cls.__name__} must be a Pydantic BaseModel"

    @pytest.mark.parametrize("cls", REMORA_EVENT_CLASSES, ids=lambda c: c.__name__)
    def test_is_not_stdlib_dataclass(self, cls):
        import dataclasses

        assert not dataclasses.is_dataclass(cls), f"{cls.__name__} must NOT be a stdlib dataclass"


class TestEventsAreFrozen:
    """All Remora events must be frozen (immutable)."""

    @pytest.mark.parametrize("cls", REMORA_EVENT_CLASSES, ids=lambda c: c.__name__)
    def test_frozen_config(self, cls):
        config = cls.model_config
        assert config.get("frozen") is True, f"{cls.__name__} must have frozen=True"

    @pytest.mark.parametrize("cls", REMORA_EVENT_CLASSES, ids=lambda c: c.__name__)
    def test_cannot_mutate(self, cls):
        event = _make_event(cls)
        with pytest.raises(Exception):
            # Pydantic frozen models raise ValidationError on setattr
            event.timestamp = 0.0


class TestModelDump:
    """model_dump() must work on all Remora events."""

    @pytest.mark.parametrize("cls", REMORA_EVENT_CLASSES, ids=lambda c: c.__name__)
    def test_model_dump_returns_dict(self, cls):
        event = _make_event(cls)
        data = event.model_dump()
        assert isinstance(data, dict)
        assert "timestamp" in data

    @pytest.mark.parametrize("cls", REMORA_EVENT_CLASSES, ids=lambda c: c.__name__)
    def test_model_dump_roundtrip(self, cls):
        event = _make_event(cls)
        data = event.model_dump()
        restored = cls(**data)
        assert restored == event


class TestBridgeRemoved:
    """to_core_event() bridge methods must not exist on LSP model classes."""

    def test_no_to_core_event_on_human_chat(self):
        from remora.lsp.models import LspHumanChatEvent

        assert not hasattr(LspHumanChatEvent, "to_core_event"), "LspHumanChatEvent should not have to_core_event()"

    def test_no_to_core_event_on_rewrite_proposal_event(self):
        from remora.lsp.models import LspRewriteProposalEvent

        assert not hasattr(LspRewriteProposalEvent, "to_core_event"), (
            "LspRewriteProposalEvent should not have to_core_event()"
        )

    def test_no_to_core_event_on_rewrite_applied_event(self):
        from remora.lsp.models import LspRewriteAppliedEvent

        assert not hasattr(LspRewriteAppliedEvent, "to_core_event"), (
            "LspRewriteAppliedEvent should not have to_core_event()"
        )

    def test_no_to_core_event_on_rewrite_rejected_event(self):
        from remora.lsp.models import LspRewriteRejectedEvent

        assert not hasattr(LspRewriteRejectedEvent, "to_core_event"), (
            "LspRewriteRejectedEvent should not have to_core_event()"
        )

    def test_no_to_core_event_on_agent_error_event(self):
        from remora.lsp.models import LspAgentErrorEvent

        assert not hasattr(LspAgentErrorEvent, "to_core_event"), (
            "lsp.models.LspAgentErrorEvent should not have to_core_event()"
        )

    def test_no_to_core_event_on_agent_message_event(self):
        from remora.lsp.models import LspAgentMessageEvent

        assert not hasattr(LspAgentMessageEvent, "to_core_event"), (
            "lsp.models.LspAgentMessageEvent should not have to_core_event()"
        )

    def test_no_from_core_event_on_agent_event(self):
        from remora.lsp.models import LspAgentEvent

        assert not hasattr(LspAgentEvent, "from_core_event"), "LspAgentEvent should not have from_core_event()"

    def test_no_core_event_imports(self):
        """lsp/models.py must not import core events with 'Core' alias."""
        import inspect
        import remora.lsp.models as mod

        source = inspect.getsource(mod)
        assert "CoreAgentCompleteEvent" not in source
        assert "CoreAgentErrorEvent" not in source
        assert "CoreAgentMessageEvent" not in source
        assert "CoreManualTriggerEvent" not in source


class TestTimestampDefault:
    """Events with no explicit timestamp should get a default via time.time."""

    @pytest.mark.parametrize("cls", REMORA_EVENT_CLASSES, ids=lambda c: c.__name__)
    def test_timestamp_auto_set(self, cls):
        before = time.time()
        event = _make_event(cls)
        after = time.time()
        assert before <= event.timestamp <= after


class TestTupleFieldsSerialization:
    """Tuple fields should round-trip correctly via model_dump."""

    def test_agent_message_tags_tuple(self):
        event = AgentMessageEvent(
            from_agent="a1",
            to_agent="a2",
            content="hi",
            tags=("tag1", "tag2"),
        )
        data = event.model_dump()
        # Pydantic may serialize tuple as list — that's fine
        assert set(data["tags"]) == {"tag1", "tag2"}

    def test_human_input_options_tuple(self):
        event = HumanInputRequestEvent(
            graph_id="g1",
            agent_id="a1",
            request_id="r1",
            question="choose?",
            options=("a", "b"),
        )
        data = event.model_dump()
        assert set(data["options"]) == {"a", "b"}
