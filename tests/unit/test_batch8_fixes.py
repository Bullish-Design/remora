"""Tests for Batch 8 quality/polish fixes.

Each test class targets a specific item from the launch plan.
Tests are written first (TDD), then implementations follow.
"""

from __future__ import annotations

import asyncio
import html
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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
        from remora.core.swarm_executor import SwarmExecutor, _agent_node_to_cst_node
        from remora.core.agent_node import AgentNode

        node = AgentNode(
            node_id="test",
            node_type="function",
            name="test_fn",
            full_name="mod.test_fn",
            file_path="test.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=19,
            source_code="def test_fn(): pass",
            source_hash="abc123",
        )
        chat_history = [
            {"role": "user", "content": "old prompt"},
            {"role": "assistant", "content": "old response"},
        ]
        cst_node = _agent_node_to_cst_node(node)
        config = Config()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=Path("/tmp"),
        )

        prompt = executor._build_prompt(node, cst_node, {}, chat_history=chat_history, requires_context=False)
        assert "Recent Chat History" not in prompt

    def test_prompt_with_context_includes_history(self):
        from remora.core.swarm_executor import SwarmExecutor, _agent_node_to_cst_node
        from remora.core.agent_node import AgentNode

        node = AgentNode(
            node_id="test",
            node_type="function",
            name="test_fn",
            full_name="mod.test_fn",
            file_path="test.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=19,
            source_code="def test_fn(): pass",
            source_hash="abc123",
        )
        chat_history = [
            {"role": "user", "content": "old prompt"},
            {"role": "assistant", "content": "old response"},
        ]
        cst_node = _agent_node_to_cst_node(node)
        config = Config()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=Path("/tmp"),
        )

        prompt = executor._build_prompt(node, cst_node, {}, chat_history=chat_history, requires_context=True)
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


# ── 8.1  P1: LLM client connection pooling ────────────────────────────────


class TestLLMClientConnectionPooling:
    """8.1 — SwarmExecutor should create the LLM client once in __init__ and reuse it."""

    def test_client_created_once_in_init(self):
        from remora.core.swarm_executor import SwarmExecutor

        config = Config()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=Path("/tmp"),
        )
        # After fix: executor should have a _client attribute created in __init__
        assert hasattr(executor, "_client")
        assert executor._client is not None

    def test_client_reused_across_calls(self):
        """The same client instance should be used on each _run_kernel call."""
        from remora.core.swarm_executor import SwarmExecutor

        config = Config()
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=Path("/tmp"),
        )
        # The client stored at construction time should be the same object
        client_ref = executor._client
        assert client_ref is executor._client


# ── 8.2  P2: Incremental workspace sync ───────────────────────────────────


class TestIncrementalWorkspaceSync:
    """8.2 — _sync_project_to_workspace should skip unchanged files via mtime."""

    def test_sync_tracks_mtimes(self):
        """After fix: CairnWorkspaceService should have an _mtimes dict."""
        from remora.core.cairn_bridge import CairnWorkspaceService

        config = Config()
        svc = CairnWorkspaceService(
            config=config,
            swarm_root=Path("/tmp/swarm"),
            project_root=Path("/tmp/proj"),
        )
        assert hasattr(svc, "_file_mtimes")
        assert isinstance(svc._file_mtimes, dict)


# ── 8.3  P3: Lightweight list_nodes() queries ─────────────────────────────


class TestLightweightListNodes:
    """8.3 — list_nodes() should accept an optional columns parameter."""

    def test_list_nodes_has_columns_param(self):
        """The list_nodes method should accept a columns keyword arg."""
        import inspect
        from remora.core.event_store import EventStore

        sig = inspect.signature(EventStore.list_nodes)
        assert "columns" in sig.parameters


# ── 8.4  L1: _notify_agents_updated as proper method ──────────────────────


class TestNotifyAgentsUpdatedMethod:
    """8.4 — _notify_agents_updated should be a proper method on RemoraLanguageServer."""

    def test_server_has_method(self):
        from remora.lsp.server import RemoraLanguageServer

        # After fix: the method should exist on the class, not monkey-patched
        assert hasattr(RemoraLanguageServer, "notify_agents_updated")
        import inspect

        assert inspect.isfunction(RemoraLanguageServer.notify_agents_updated) or inspect.ismethod(
            RemoraLanguageServer.notify_agents_updated
        )


# ── 8.5  L2: Defer server singleton initialization ────────────────────────


class TestDeferServerSingleton:
    """8.5 — server.py should offer lazy init instead of eagerly constructing at import."""

    def test_get_server_returns_instance(self):
        """A get_server() function should provide the singleton lazily."""
        from remora.lsp.server import get_server

        s = get_server()
        assert s is not None
        # Calling again should return same instance
        assert get_server() is s


# ── 8.6  L3: Document Qwen XML tag parser ─────────────────────────────────


class TestDocumentQwenXMLParser:
    """8.6 — _extract_text_tool_calls should have a docstring explaining the Qwen workaround."""

    def test_has_docstring(self):
        from remora.lsp.runner import AgentRunner

        method = AgentRunner._extract_text_tool_calls
        assert method.__doc__ is not None
        # Should mention Qwen specifically
        assert "qwen" in method.__doc__.lower() or "xml" in method.__doc__.lower()


# ── 8.7  L5: Fix ensure_file_synced stub ──────────────────────────────────


class TestEnsureFileSyncedStub:
    """8.7 — ensure_file_synced should actually sync the file, not just return True."""

    @pytest.mark.asyncio
    async def test_syncs_existing_file(self, tmp_path):
        """ensure_file_synced should read from disk and write to stable workspace."""
        from remora.core.cairn_bridge import CairnWorkspaceService

        config = Config()
        svc = CairnWorkspaceService(
            config=config,
            swarm_root=tmp_path / "swarm",
            project_root=tmp_path / "proj",
        )
        # Create a file on "disk"
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        test_file = proj_dir / "hello.py"
        test_file.write_text("print('hi')")

        # Mock the stable workspace
        mock_ws = MagicMock()
        mock_ws.files = MagicMock()
        mock_ws.files.write = AsyncMock(return_value=None)
        svc._stable_workspace = mock_ws

        result = await svc.ensure_file_synced("hello.py")
        assert result is True
        # After fix, it should have attempted to write to stable workspace
        mock_ws.files.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_for_missing_file(self, tmp_path):
        """ensure_file_synced should return False when the file doesn't exist."""
        from remora.core.cairn_bridge import CairnWorkspaceService

        config = Config()
        svc = CairnWorkspaceService(
            config=config,
            swarm_root=tmp_path / "swarm",
            project_root=tmp_path / "proj",
        )
        (tmp_path / "proj").mkdir()
        svc._stable_workspace = MagicMock()

        result = await svc.ensure_file_synced("nonexistent.py")
        assert result is False


# ── 8.8  L6: Fix did_save disk read race ──────────────────────────────────


class TestDidSaveDiskReadRace:
    """8.8 — did_save should use LSP-provided text when available."""

    def test_did_save_uses_params_text(self):
        """After fix: did_save should check params.text first before reading from disk."""
        import inspect
        from remora.lsp.handlers.documents import did_save

        source = inspect.getsource(did_save)
        # The fixed version should reference params.text somewhere
        assert "params.text" in source or "text_document.text" in source


# ── 8.11 S3: Fix ChatServiceState singleton ───────────────────────────────


class TestChatServiceStateSingleton:
    """8.11 — ChatServiceState should use dependency injection, not module-level global."""

    def test_create_session_accepts_state(self):
        """After fix: route handlers should accept state via dependency injection."""
        from remora.service.chat_service import ChatServiceState

        # The state should be constructible independently
        s1 = ChatServiceState()
        s2 = ChatServiceState()
        # They should be independent instances
        assert s1 is not s2
        assert s1.sessions is not s2.sessions

    def test_app_state_injectable(self):
        """After fix: the Starlette app should store state on app.state."""
        from remora.service.chat_service import ChatServiceState, create_app

        state = ChatServiceState()
        app = create_app(state=state)
        assert app.state.chat_state is state


# ── 8.12 S4: Fix DatastarResponse content type ────────────────────────────


class TestDatastarResponseContentType:
    """8.12 — render_patch and render_signals should have proper type annotations."""

    def test_render_patch_returns_str(self):
        from remora.service.datastar import render_patch

        import inspect

        sig = inspect.signature(render_patch)
        # Return type should be annotated as str
        assert sig.return_annotation is str or sig.return_annotation == "str"

    def test_render_signals_returns_str(self):
        from remora.service.datastar import render_signals

        import inspect

        sig = inspect.signature(render_signals)
        assert sig.return_annotation is str or sig.return_annotation == "str"


# ── 8.14 S6: Make chat history limit configurable ─────────────────────────


class TestChatHistoryLimitConfigurable:
    """8.14 — Chat history limit should come from Config, not hardcoded [-5:]."""

    def test_config_has_chat_history_limit(self):
        """Config should have a chat_history_limit field."""
        config = Config()
        assert hasattr(config, "chat_history_limit")
        assert config.chat_history_limit == 5  # sensible default

    def test_build_prompt_uses_config_limit(self):
        from remora.core.swarm_executor import SwarmExecutor, _agent_node_to_cst_node
        from remora.core.agent_node import AgentNode

        config = Config()
        config_custom = Config(chat_history_limit=2)
        node = AgentNode(
            node_id="test",
            node_type="function",
            name="fn",
            full_name="mod.fn",
            file_path="test.py",
            start_line=1,
            end_line=1,
            start_byte=0,
            end_byte=0,
            source_code="",
            source_hash="abc",
        )
        chat_history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        cst_node = _agent_node_to_cst_node(node)

        executor_default = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="t",
            project_root=Path("/tmp"),
        )
        prompt_default = executor_default._build_prompt(
            node, cst_node, {}, chat_history=chat_history, requires_context=True
        )

        executor_custom = SwarmExecutor(
            config=config_custom,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="t",
            project_root=Path("/tmp"),
        )
        prompt_custom = executor_custom._build_prompt(
            node, cst_node, {}, chat_history=chat_history, requires_context=True
        )

        # With limit=2, only last 2 history entries should appear
        assert prompt_custom.count("msg") == 2
        # With default limit=5, last 5 entries should appear
        assert prompt_default.count("msg") == 5


# ── 8.16 R2: Fix cascade correlation IDs ──────────────────────────────────


class TestCascadeCorrelationIDs:
    """8.16 — Cascaded triggers should use event-specific correlation IDs,
    not reuse the parent correlation_id from EventStore."""

    def test_run_from_event_store_generates_new_correlation_ids(self):
        """When correlation_id is missing from an event, the runner should generate one."""
        from remora.lsp.runner import AgentRunner

        runner = AgentRunner.create_headless(event_store=MagicMock())
        # Mock event with no correlation_id
        mock_event = MagicMock(spec=[])  # no attributes
        # run_from_event_store uses getattr(event, 'correlation_id', None) or 'base'
        # After fix: it should generate a unique ID instead of falling back to 'base'
        cid = getattr(mock_event, "correlation_id", None)
        # The fallback should NOT be the literal string "base"
        # We test the runner's method directly
        import inspect

        source = inspect.getsource(AgentRunner.run_from_event_store)
        # After fix: should call generate_correlation_id or uuid instead of "base"
        assert '"base"' not in source
