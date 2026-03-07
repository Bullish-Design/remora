"""Tests for SwarmExecutor — the reactive agent execution engine.

Tests cover:
- Prompt building logic (_build_prompt)
- Bundle path resolution (_resolve_bundle_path)
- Model name resolution (_resolve_model_name)
- Language tag helper (_lang_tag_for)
- AgentNode → CSTNode conversion (_agent_node_to_cst_node)
- Connection pooling (LLM client reuse)
- EventStore observer wiring
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.core.agents.agent_node import AgentNode
from remora.core.config import Config
from remora.core.events.events import AgentCompleteEvent, AgentErrorEvent, AgentStartEvent
from remora.core.agents.execution import (
    _lang_tag_for,
    _agent_node_to_cst_node,
    _resolve_bundle_path,
    _resolve_model_name,
    _build_prompt,
)
from remora.core.agents.swarm_executor import SwarmExecutor
from remora.utils import PathResolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, **overrides: Any) -> Config:
    defaults = {
        "project_path": str(tmp_path),
        "bundle_root": str(tmp_path / "agents"),
        "bundle_mapping": {"function": "code", "file": "file"},
        "model_base_url": "http://localhost:8000/v1",
        "model_default": "test/model",
        "model_api_key": "test-key",
        "swarm_root": str(tmp_path / ".remora"),
        "swarm_id": "test-swarm",
        "max_concurrency": 4,
        "max_turns": 3,
        "truncation_limit": 512,
        "timeout_s": 10.0,
        "chat_history_limit": 5,
    }
    defaults.update(overrides)
    return Config(**defaults)


def _make_node(**overrides: Any) -> AgentNode:
    defaults = {
        "node_id": "agent_func_1",
        "node_type": "function",
        "name": "calculate_total",
        "full_name": "billing.calculate_total",
        "file_path": "src/billing.py",
        "start_line": 10,
        "end_line": 25,
        "start_byte": 0,
        "end_byte": 0,
        "source_code": "def calculate_total(items): return sum(items)",
        "source_hash": "abc123",
        "parent_id": None,
    }
    defaults.update(overrides)
    return AgentNode(**defaults)


# =========================================================================
# 1. _lang_tag_for — pure function
# =========================================================================


class TestLangTagFor:
    """Verify markdown language tag lookup from file paths."""

    def test_python_file(self):
        assert _lang_tag_for("src/main.py") == "python"

    def test_typescript_file(self):
        assert _lang_tag_for("src/app.ts") == "typescript"

    def test_javascript_file(self):
        assert _lang_tag_for("src/app.js") == "javascript"

    def test_rust_file(self):
        assert _lang_tag_for("src/main.rs") == "rust"

    def test_go_file(self):
        assert _lang_tag_for("cmd/main.go") == "go"

    def test_yaml_file(self):
        assert _lang_tag_for("config.yaml") == "yaml"

    def test_yml_file(self):
        assert _lang_tag_for("config.yml") == "yaml"

    def test_json_file(self):
        assert _lang_tag_for("package.json") == "json"

    def test_toml_file(self):
        assert _lang_tag_for("pyproject.toml") == "toml"

    def test_markdown_file(self):
        assert _lang_tag_for("README.md") == "markdown"

    def test_bash_file(self):
        assert _lang_tag_for("build.sh") == "bash"

    def test_unknown_extension_returns_empty(self):
        assert _lang_tag_for("data.xyz") == ""

    def test_no_extension_returns_empty(self):
        assert _lang_tag_for("Makefile") == ""

    def test_case_insensitive(self):
        assert _lang_tag_for("src/Main.PY") == "python"


# =========================================================================
# 2. _agent_node_to_cst_node — conversion helper
# =========================================================================


class TestAgentNodeToCstNode:
    """Verify AgentNode -> CSTNode conversion."""

    def test_basic_conversion(self):
        node = _make_node()
        cst = _agent_node_to_cst_node(node)
        assert cst.node_id == "agent_func_1"
        assert cst.node_type == "function"
        assert cst.name == "calculate_total"
        assert cst.full_name == "billing.calculate_total"
        assert cst.file_path == "src/billing.py"
        assert cst.start_line == 10
        assert cst.end_line == 25

    def test_source_code_maps_to_text(self):
        node = _make_node(source_code="def foo(): pass")
        cst = _agent_node_to_cst_node(node)
        assert cst.text == "def foo(): pass"

    def test_byte_offsets_preserved(self):
        node = _make_node(start_byte=100, end_byte=500)
        cst = _agent_node_to_cst_node(node)
        assert cst.start_byte == 100
        assert cst.end_byte == 500


# =========================================================================
# 3. _resolve_bundle_path
# =========================================================================


class TestResolveBundlePath:
    """Verify bundle path resolution from config mapping."""

    def test_mapped_node_type(self, tmp_path):
        config = _make_config(tmp_path, bundle_mapping={"function": "code"})
        node = _make_node(node_type="function")
        path = _resolve_bundle_path(node, config)
        assert path == Path(config.bundle_root) / "code"

    def test_unmapped_node_type_returns_bundle_root(self, tmp_path):
        config = _make_config(tmp_path, bundle_mapping={"function": "code"})
        node = _make_node(node_type="module")
        path = _resolve_bundle_path(node, config)
        assert path == Path(config.bundle_root)


# =========================================================================
# 4. _build_prompt
# =========================================================================


class TestBuildPrompt:
    """Verify prompt construction from AgentNode and context."""

    def test_prompt_contains_target_info(self, tmp_path):
        config = _make_config(tmp_path)
        resolver = PathResolver(tmp_path)
        node = _make_node()
        cst_node = _agent_node_to_cst_node(node)
        prompt = _build_prompt(node, cst_node, {}, resolver, config)
        assert "billing.calculate_total" in prompt
        assert "src/billing.py" in prompt
        assert "Lines: 10-25" in prompt

    def test_prompt_includes_code_when_available(self, tmp_path):
        config = _make_config(tmp_path)
        resolver = PathResolver(tmp_path)
        node = _make_node()
        cst_node = _agent_node_to_cst_node(node)
        files = {"src/billing.py": "def calculate_total(items): return sum(items)"}
        prompt = _build_prompt(node, cst_node, files, resolver, config)
        assert "## Code" in prompt
        assert "def calculate_total" in prompt
        assert "```python" in prompt

    def test_prompt_includes_trigger_event(self, tmp_path):
        config = _make_config(tmp_path)
        resolver = PathResolver(tmp_path)
        node = _make_node()
        cst_node = _agent_node_to_cst_node(node)

        class FakeTrigger:
            content = "file changed"

        prompt = _build_prompt(node, cst_node, {}, resolver, config, trigger_event=FakeTrigger())
        assert "## Trigger Event" in prompt
        assert "file changed" in prompt

    def test_prompt_includes_chat_history(self, tmp_path):
        config = _make_config(tmp_path)
        resolver = PathResolver(tmp_path)
        node = _make_node()
        cst_node = _agent_node_to_cst_node(node)
        chat_history = [
            {"role": "user", "content": "fix the bug"},
            {"role": "assistant", "content": "I fixed it"},
        ]
        prompt = _build_prompt(node, cst_node, {}, resolver, config, chat_history=chat_history, requires_context=True)
        assert "## Recent Chat History" in prompt
        assert "fix the bug" in prompt
        assert "I fixed it" in prompt

    def test_prompt_skips_history_when_requires_context_false(self, tmp_path):
        config = _make_config(tmp_path)
        resolver = PathResolver(tmp_path)
        node = _make_node()
        cst_node = _agent_node_to_cst_node(node)
        chat_history = [{"role": "user", "content": "fix the bug"}]
        prompt = _build_prompt(node, cst_node, {}, resolver, config, chat_history=chat_history, requires_context=False)
        assert "## Recent Chat History" not in prompt

    def test_prompt_respects_chat_history_limit(self, tmp_path):
        config = _make_config(tmp_path, chat_history_limit=2)
        resolver = PathResolver(tmp_path)
        node = _make_node()
        cst_node = _agent_node_to_cst_node(node)
        chat_history = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "resp1"},
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "resp2"},
            {"role": "user", "content": "msg3"},
        ]
        prompt = _build_prompt(node, cst_node, {}, resolver, config, chat_history=chat_history, requires_context=True)
        # Only the last 2 entries should be included
        assert "msg1" not in prompt
        assert "resp1" not in prompt
        assert "resp2" in prompt
        assert "msg3" in prompt


# =========================================================================
# 5. Connection Pooling — LLM client created once
# =========================================================================


class TestConnectionPooling:
    """Verify that the LLM client is created once in __init__."""

    @patch("remora.core.swarm_executor.build_client")
    def test_client_created_in_init(self, mock_build_client, tmp_path):
        mock_build_client.return_value = MagicMock()
        config = _make_config(tmp_path)
        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        mock_build_client.assert_called_once()
        assert executor._client is mock_build_client.return_value

    @patch("remora.core.swarm_executor.build_client")
    def test_client_receives_config_values(self, mock_build_client, tmp_path):
        mock_build_client.return_value = MagicMock()
        config = _make_config(
            tmp_path,
            model_base_url="http://custom:9999/v1",
            model_api_key="my-key",
            model_default="custom/model",
            timeout_s=42.0,
        )
        SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=MagicMock(),
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        call_args = mock_build_client.call_args[0][0]
        assert call_args["base_url"] == "http://custom:9999/v1"
        assert call_args["api_key"] == "my-key"
        assert call_args["model"] == "custom/model"
        assert call_args["timeout"] == 42.0


# =========================================================================
# 6. _resolve_model_name
# =========================================================================


class TestResolveModelName:
    """Verify model name resolution from bundle.yaml or config fallback."""

    def test_falls_back_to_config_default(self, tmp_path):
        config = _make_config(tmp_path, model_default="default/model")
        # Non-existent bundle path -> falls back to config default
        manifest = MagicMock(model="")
        model = _resolve_model_name(tmp_path / "nonexistent", manifest, config)
        assert model == "default/model"

    def test_reads_from_bundle_yaml(self, tmp_path):
        config = _make_config(tmp_path, model_default="default/model")
        # Create a bundle.yaml with a model override
        bundle_dir = tmp_path / "agents" / "code"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "bundle.yaml").write_text("model:\n  id: custom/override\n")

        manifest = MagicMock(model="")
        model = _resolve_model_name(bundle_dir, manifest, config)
        assert model == "custom/override"


# =========================================================================
# 7. SwarmExecutor emits AgentStartEvent / AgentCompleteEvent
# =========================================================================


class TestSwarmExecutorDomainEvents:
    """Verify SwarmExecutor.run_agent emits AgentStartEvent/AgentCompleteEvent
    via event_store.append() so that NodeProjection populates last_trigger_event
    and last_completed_at (Workstream E — Gap #11)."""

    @pytest.mark.asyncio
    @patch("remora.core.swarm_executor.build_client")
    @patch("remora.core.swarm_executor.execute_agent_turn", new_callable=AsyncMock)
    async def test_emits_start_and_complete_events(self, mock_exec, mock_build_client, tmp_path):
        from remora.core.agents.execution import ExecutionResult

        mock_build_client.return_value = MagicMock()
        mock_exec.return_value = ExecutionResult(response_text="Done.", kernel_events=[])

        config = _make_config(tmp_path)
        event_store = MagicMock()
        event_store.append = AsyncMock(return_value=1)

        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=event_store,
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        executor._workspace_initialized = True  # skip workspace init

        node = _make_node()
        await executor.run_agent(node)

        # Find AgentStartEvent
        start_events = [call for call in event_store.append.call_args_list if isinstance(call[0][1], AgentStartEvent)]
        assert len(start_events) == 1
        assert start_events[0][0][1].agent_id == "agent_func_1"

        # Find AgentCompleteEvent
        complete_events = [
            call for call in event_store.append.call_args_list if isinstance(call[0][1], AgentCompleteEvent)
        ]
        assert len(complete_events) == 1
        assert complete_events[0][0][1].agent_id == "agent_func_1"

    @pytest.mark.asyncio
    @patch("remora.core.swarm_executor.build_client")
    @patch("remora.core.swarm_executor.execute_agent_turn", new_callable=AsyncMock)
    async def test_emits_error_event_on_failure(self, mock_exec, mock_build_client, tmp_path):
        mock_build_client.return_value = MagicMock()
        mock_exec.side_effect = RuntimeError("model error")

        config = _make_config(tmp_path)
        event_store = MagicMock()
        event_store.append = AsyncMock(return_value=1)

        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=event_store,
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        executor._workspace_initialized = True

        node = _make_node()
        with pytest.raises(RuntimeError, match="model error"):
            await executor.run_agent(node)

        # Find AgentErrorEvent
        error_events = [call for call in event_store.append.call_args_list if isinstance(call[0][1], AgentErrorEvent)]
        assert len(error_events) == 1
        assert "model error" in error_events[0][0][1].error

        # Should NOT have emitted AgentCompleteEvent
        complete_events = [
            call for call in event_store.append.call_args_list if isinstance(call[0][1], AgentCompleteEvent)
        ]
        assert len(complete_events) == 0

    @pytest.mark.asyncio
    @patch("remora.core.swarm_executor.build_client")
    @patch("remora.core.swarm_executor.execute_agent_turn", new_callable=AsyncMock)
    async def test_scaffold_trigger_adds_scaffold_tag(self, mock_exec, mock_build_client, tmp_path):
        """When trigger_event is ScaffoldRequestEvent, AgentCompleteEvent should have tags=('scaffold',)."""
        from remora.core.events.events import ScaffoldRequestEvent
        from remora.core.agents.execution import ExecutionResult

        mock_build_client.return_value = MagicMock()
        mock_exec.return_value = ExecutionResult(response_text="Scaffolded.", kernel_events=[])

        config = _make_config(tmp_path)
        event_store = MagicMock()
        event_store.append = AsyncMock(return_value=1)

        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=event_store,
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        executor._workspace_initialized = True

        node = _make_node()
        trigger = ScaffoldRequestEvent(
            node_id="agent_func_1",
            to_agent="agent_func_1",
            node_type="function",
        )
        await executor.run_agent(node, trigger_event=trigger)

        # Find AgentCompleteEvent and check tags
        complete_events = [
            call for call in event_store.append.call_args_list if isinstance(call[0][1], AgentCompleteEvent)
        ]
        assert len(complete_events) == 1
        assert complete_events[0][0][1].tags == ("scaffold",)

    @pytest.mark.asyncio
    @patch("remora.core.swarm_executor.build_client")
    @patch("remora.core.swarm_executor.execute_agent_turn", new_callable=AsyncMock)
    async def test_non_scaffold_trigger_has_no_tags(self, mock_exec, mock_build_client, tmp_path):
        """When trigger_event is not ScaffoldRequestEvent, AgentCompleteEvent tags should be empty."""
        from remora.core.events.events import ContentChangedEvent
        from remora.core.agents.execution import ExecutionResult

        mock_build_client.return_value = MagicMock()
        mock_exec.return_value = ExecutionResult(response_text="Done.", kernel_events=[])

        config = _make_config(tmp_path)
        event_store = MagicMock()
        event_store.append = AsyncMock(return_value=1)

        executor = SwarmExecutor(
            config=config,
            event_bus=None,
            event_store=event_store,
            subscriptions=MagicMock(),
            swarm_id="test",
            project_root=tmp_path,
        )
        executor._workspace_initialized = True

        node = _make_node()
        trigger = ContentChangedEvent(path="src/billing.py")
        await executor.run_agent(node, trigger_event=trigger)

        complete_events = [
            call for call in event_store.append.call_args_list if isinstance(call[0][1], AgentCompleteEvent)
        ]
        assert len(complete_events) == 1
        assert complete_events[0][0][1].tags == ()


# =========================================================================
# 8. Swarm tools end-to-end with real SubscriptionRegistry (Gap #3)
# =========================================================================


class TestSwarmToolsEndToEnd:
    """Verify SubscribeTool and UnsubscribeTool work end-to-end
    with a real SubscriptionRegistry backed by in-memory SQLite.

    This closes Gap #3: swarm tools wired end-to-end."""

    @pytest.fixture
    async def registry(self):
        """Create a real SubscriptionRegistry with in-memory SQLite."""
        from remora.core.events.subscriptions import SubscriptionRegistry

        reg = SubscriptionRegistry(db_path=":memory:")
        await reg.initialize()
        yield reg
        await reg.close()

    def _make_context(self, registry) -> "AgentContext":
        """Build an AgentContext with real registry callbacks."""
        from remora.core.agents.agent_context import AgentContext
        from remora.core.events.subscriptions import SubscriptionRegistry

        async def _register_sub(agent_id: str, pattern) -> None:
            await registry.register(agent_id, pattern)

        async def _unsubscribe_sub(subscription_id: int) -> str:
            removed = await registry.unregister(subscription_id)
            if removed:
                return f"Subscription {subscription_id} removed."
            return f"No subscription found for {subscription_id}."

        async def _emit_event(event_type: str, event_obj) -> None:
            pass  # no-op for this test

        async def _broadcast(to_pattern: str, content: str) -> str:
            return "ok"

        async def _query_agents(filter_type=None):
            return []

        return AgentContext(
            agent_id="agent_test_1",
            correlation_id="corr_test",
            emit_event=_emit_event,
            register_subscription=_register_sub,
            unsubscribe_subscription=_unsubscribe_sub,
            broadcast=_broadcast,
            query_agents=_query_agents,
        )

    @pytest.mark.asyncio
    async def test_subscribe_tool_registers_subscription(self, registry):
        """SubscribeTool.execute() should create a subscription in the registry."""
        from remora.core.tools.swarm import SubscribeTool

        ctx = self._make_context(registry)
        tool = SubscribeTool(ctx)

        result = await tool.execute(
            {"event_types": ["ContentChangedEvent"], "path_glob": "src/*.py"},
            context=None,
        )

        assert not result.is_error
        assert "successfully" in result.output.lower()

        # Verify it's actually in the registry
        subs = await registry.get_subscriptions("agent_test_1")
        assert len(subs) == 1
        assert subs[0].pattern.event_types == ["ContentChangedEvent"]
        assert subs[0].pattern.path_glob == "src/*.py"

    @pytest.mark.asyncio
    async def test_unsubscribe_tool_removes_subscription(self, registry):
        """UnsubscribeTool.execute() should remove the subscription from the registry."""
        from remora.core.events.subscriptions import SubscriptionPattern
        from remora.core.tools.swarm import UnsubscribeTool

        # Pre-register a subscription
        pattern = SubscriptionPattern(event_types=["AgentMessageEvent"])
        sub = await registry.register("agent_test_1", pattern)

        ctx = self._make_context(registry)
        tool = UnsubscribeTool(ctx)

        result = await tool.execute(
            {"subscription_id": sub.id},
            context=None,
        )

        assert not result.is_error
        assert "removed" in result.output.lower()

        # Verify it's gone from the registry
        subs = await registry.get_subscriptions("agent_test_1")
        assert len(subs) == 0

    @pytest.mark.asyncio
    async def test_subscribe_then_unsubscribe_round_trip(self, registry):
        """Full round-trip: subscribe via tool, verify, unsubscribe via tool, verify gone."""
        from remora.core.tools.swarm import SubscribeTool, UnsubscribeTool

        ctx = self._make_context(registry)

        # Subscribe
        sub_tool = SubscribeTool(ctx)
        await sub_tool.execute(
            {"event_types": ["ContentChangedEvent", "AgentMessageEvent"]},
            context=None,
        )

        subs = await registry.get_subscriptions("agent_test_1")
        assert len(subs) == 1
        sub_id = subs[0].id

        # Unsubscribe
        unsub_tool = UnsubscribeTool(ctx)
        result = await unsub_tool.execute(
            {"subscription_id": sub_id},
            context=None,
        )

        assert not result.is_error
        subs = await registry.get_subscriptions("agent_test_1")
        assert len(subs) == 0

    @pytest.mark.asyncio
    async def test_subscribe_tool_matches_events(self, registry):
        """A subscription created by SubscribeTool should match events via get_matching_agents."""
        from remora.core.events.events import ContentChangedEvent
        from remora.core.tools.swarm import SubscribeTool

        ctx = self._make_context(registry)
        tool = SubscribeTool(ctx)

        await tool.execute(
            {"event_types": ["ContentChangedEvent"]},
            context=None,
        )

        # Now check that this agent matches a ContentChangedEvent
        event = ContentChangedEvent(path="/src/foo.py")
        matching = await registry.get_matching_agents(event)
        assert "agent_test_1" in matching

    @pytest.mark.asyncio
    async def test_build_swarm_tools_includes_subscribe_unsubscribe(self):
        """build_swarm_tools() should include SubscribeTool and UnsubscribeTool."""
        from remora.core.tools.swarm import build_swarm_tools, SubscribeTool, UnsubscribeTool

        ctx = MagicMock()
        ctx.agent_id = "agent_1"
        tools = build_swarm_tools(ctx)

        tool_types = [type(t) for t in tools]
        assert SubscribeTool in tool_types
        assert UnsubscribeTool in tool_types
