"""Tests for Batch 8 quality/polish fixes.

Each test class targets a specific item from the launch plan.
Tests are written first (TDD), then implementations follow.
"""

from __future__ import annotations

import html
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from remora.core.config import Config
from remora.core.event_bus import EventBus
from remora.core.events import AgentStartEvent, AgentCompleteEvent, AgentErrorEvent
from remora.ui.projector import UiStateProjector


# ── 8.9  S1: get_subscriptions name collision ─────────────────────────────


class TestGetSubscriptionsNameCollision:
    """8.9 — The no-arg registry getter must not be shadowed by the async method."""

    def test_subscription_registry_accessor(self):
        """After fix: subscription_registry returns the SubscriptionRegistry."""
        from remora.service.api import RemoraService

        mock_registry = MagicMock()
        svc = RemoraService(
            config=Config(),
            project_root=Path("/tmp"),
            event_bus=EventBus(),
            subscriptions=mock_registry,
        )
        # The old `get_subscriptions()` no-arg path should now be `subscription_registry`
        assert svc.subscription_registry is mock_registry

    @pytest.mark.asyncio
    async def test_get_agent_subscriptions(self):
        """After fix: get_agent_subscriptions(agent_id) still works for agent lookups."""
        from remora.service.api import RemoraService

        mock_registry = MagicMock()
        svc = RemoraService(
            config=Config(),
            project_root=Path("/tmp"),
            event_bus=EventBus(),
            subscriptions=mock_registry,
        )
        # The async agent lookup is now `get_agent_subscriptions`
        assert hasattr(svc, "get_agent_subscriptions")


# ── 8.10 S2: total_agents counter bug ─────────────────────────────────────


class TestTotalAgentsCounter:
    """8.10 — total_agents should increment for every new agent, not just the first."""

    def test_multiple_agents_counted(self):
        proj = UiStateProjector()

        proj.record(AgentStartEvent(graph_id="g", agent_id="a1", node_name="a1"))
        proj.record(AgentStartEvent(graph_id="g", agent_id="a2", node_name="a2"))
        proj.record(AgentStartEvent(graph_id="g", agent_id="a3", node_name="a3"))

        assert proj.total_agents == 3

    def test_same_agent_not_double_counted(self):
        proj = UiStateProjector()

        proj.record(AgentStartEvent(graph_id="g", agent_id="a1", node_name="a1"))
        proj.record(AgentStartEvent(graph_id="g", agent_id="a1", node_name="a1"))

        assert proj.total_agents == 1


# ── 8.13 S5: duplicate prompt context ─────────────────────────────────────


class TestDuplicatePromptContext:
    """8.13 — The prompt should NOT include chat history when it will also be
    passed as kernel messages (requires_context=False avoids duplication)."""

    def test_prompt_without_context_excludes_history(self):
        from remora.core.swarm_executor import SwarmExecutor
        from remora.core.agent_state import AgentState
        from remora.core.discovery import CSTNode

        state = AgentState(
            agent_id="test",
            name="test_fn",
            full_name="mod.test_fn",
            file_path="test.py",
            node_type="function",
            chat_history=[
                {"role": "user", "content": "old prompt"},
                {"role": "assistant", "content": "old response"},
            ],
        )
        node = CSTNode(
            node_id="test",
            node_type="function",
            name="test_fn",
            full_name="mod.test_fn",
            file_path="test.py",
            text="def test_fn(): pass",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=19,
        )
        config = Config()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_state=MagicMock(),
            swarm_id="test",
            project_root=Path("/tmp"),
        )

        prompt = executor._build_prompt(state, node, {}, requires_context=False)
        assert "Recent Chat History" not in prompt

    def test_prompt_with_context_includes_history(self):
        from remora.core.swarm_executor import SwarmExecutor
        from remora.core.agent_state import AgentState
        from remora.core.discovery import CSTNode

        state = AgentState(
            agent_id="test",
            name="test_fn",
            full_name="mod.test_fn",
            file_path="test.py",
            node_type="function",
            chat_history=[
                {"role": "user", "content": "old prompt"},
                {"role": "assistant", "content": "old response"},
            ],
        )
        node = CSTNode(
            node_id="test",
            node_type="function",
            name="test_fn",
            full_name="mod.test_fn",
            file_path="test.py",
            text="def test_fn(): pass",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=19,
        )
        config = Config()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_state=MagicMock(),
            swarm_id="test",
            project_root=Path("/tmp"),
        )

        prompt = executor._build_prompt(state, node, {}, requires_context=True)
        assert "Recent Chat History" in prompt


# ── 8.21 R7: XSS in BlockedAgentCard ──────────────────────────────────────


class TestBlockedAgentCardXSS:
    """8.21 — All user-controlled data in BlockedAgentCard must be HTML-escaped."""

    def test_question_is_escaped(self):
        from remora.ui.components.dashboard import BlockedAgentCard

        card = BlockedAgentCard(
            blocked={
                "agent_id": "safe_id",
                "question": '<script>alert("xss")</script>',
                "options": [],
                "request_id": "req_1",
            }
        )
        rendered = card.render()
        # The raw script tag must NOT appear in the output
        assert "<script>" not in rendered
        assert html.escape('<script>alert("xss")</script>') in rendered

    def test_request_id_is_escaped(self):
        from remora.ui.components.dashboard import BlockedAgentCard

        card = BlockedAgentCard(
            blocked={
                "agent_id": "safe",
                "question": "Safe question",
                "options": [],
                "request_id": "'; alert('xss'); //",
            }
        )
        rendered = card.render()
        # The raw injection must not appear unescaped
        assert "'; alert('xss'); //" not in rendered or "\\'" in rendered


# ── 8.18 R4: build_virtual_fs duplicates ──────────────────────────────────


class TestBuildVirtualFsDuplicates:
    """8.18 — build_virtual_fs should NOT add both /path and path entries."""

    def test_no_duplicate_entries(self):
        from remora.core.tools.grail import build_virtual_fs

        files = {"src/main.py": "content", "tests/test.py": "test"}
        result = build_virtual_fs(files)

        # Each file should appear exactly once
        assert len(result) == len(files)

    def test_normalized_paths(self):
        from remora.core.tools.grail import build_virtual_fs

        files = {"src/main.py": "content"}
        result = build_virtual_fs(files)

        # Should have normalized path without leading slash
        assert "src/main.py" in result


# ── 8.15 R1: Deduplicate ignore patterns ──────────────────────────────────


class TestDeduplicateIgnorePatterns:
    """8.15 — discovery._walk_directory should read from config ignore patterns."""

    def test_walk_directory_uses_config_patterns(self):
        from remora.core.config import DEFAULT_IGNORE_PATTERNS
        from remora.core.discovery import _walk_directory

        # The function should accept ignore_patterns parameter
        # (After fix, it reads from config or accepts a parameter)
        import inspect

        sig = inspect.signature(_walk_directory)
        assert "ignore_patterns" in sig.parameters


# ── 8.19 R5: _find_config_file sentinel ───────────────────────────────────


class TestFindConfigFileSentinel:
    """8.19 — _find_config_file should return None when no config file exists."""

    def test_returns_none_when_not_found(self, tmp_path, monkeypatch):
        from remora.core.config import _find_config_file

        monkeypatch.chdir(tmp_path)
        # Create pyproject.toml to stop the upward search
        (tmp_path / "pyproject.toml").touch()
        result = _find_config_file()
        assert result is None


# ── 8.20 R6: _to_jsonable type mismatch ───────────────────────────────────


class TestToJsonableTypeMismatch:
    """8.20 — _to_jsonable should handle Pydantic models, not just dataclasses."""

    def test_handles_pydantic_model(self):
        from pydantic import BaseModel
        from remora.ui.projector import _to_jsonable

        class Sample(BaseModel):
            name: str = "test"
            value: int = 42

        result = _to_jsonable(Sample())
        assert result == {"name": "test", "value": 42}

    def test_handles_enum(self):
        from enum import Enum
        from remora.ui.projector import _to_jsonable

        class Color(Enum):
            RED = "red"

        result = _to_jsonable(Color.RED)
        assert result == "red"


# ── 8.17 R3: Configurable event bus error policy ─────────────────────────


class TestEventBusErrorPolicy:
    """8.17 — EventBus should support configurable error policies."""

    @pytest.mark.asyncio
    async def test_default_policy_logs(self):
        """Default policy should log and swallow errors (existing behavior)."""
        bus = EventBus()
        errors = []

        def bad_handler(event):
            raise ValueError("boom")

        bus.subscribe_all(bad_handler)

        # Should not raise
        from remora.core.events import AgentStartEvent

        await bus.emit(AgentStartEvent(graph_id="g", agent_id="a1", node_name="a1"))

    @pytest.mark.asyncio
    async def test_propagate_policy_raises(self):
        """PROPAGATE policy should re-raise handler errors."""
        bus = EventBus(error_policy="propagate")

        def bad_handler(event):
            raise ValueError("boom")

        bus.subscribe_all(bad_handler)

        from remora.core.events import AgentStartEvent

        with pytest.raises(ValueError, match="boom"):
            await bus.emit(AgentStartEvent(graph_id="g", agent_id="a1", node_name="a1"))


# ── 8.22 R8: Extension cache global state ────────────────────────────────


class TestExtensionCacheGlobalState:
    """8.22 — load_extensions should accept an optional cache parameter."""

    def test_custom_cache(self, tmp_path):
        from remora.extensions import load_extensions

        cache: dict = {}
        result = load_extensions(tmp_path, cache=cache)
        assert result == []
        # Cache should be populated
        assert str(tmp_path) in cache

    def test_default_uses_global_cache(self, tmp_path):
        from remora.extensions import load_extensions

        # Should still work without explicit cache
        result = load_extensions(tmp_path)
        assert result == []
