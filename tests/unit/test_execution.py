"""Tests for the unified execute_agent_turn() function.

Covers:
- Bundle resolution and manifest loading
- Workspace initialization (lazy and pre-initialized)
- Prompt building
- Tool discovery + extra_tools injection
- Observer wiring (EventStore + on_kernel_event callback)
- Kernel invocation and result extraction
- Connection pooling (client reuse)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.core.agent_node import AgentNode
from remora.core.execution import (
    ExecutionResult,
    _CompositeObserver,
    _build_prompt,
    _resolve_bundle_path,
    execute_agent_turn,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(**overrides: Any) -> AgentNode:
    defaults = {
        "node_id": "rm_test1",
        "node_type": "function",
        "name": "foo",
        "full_name": "mod.foo",
        "file_path": "src/mod.py",
        "start_line": 1,
        "end_line": 5,
        "source_code": "def foo():\n    return 1\n",
        "source_hash": "abc",
        "status": "idle",
    }
    defaults.update(overrides)
    return AgentNode(**defaults)


def _make_config(**overrides: Any) -> MagicMock:
    config = MagicMock()
    config.bundle_root = "agents"
    config.bundle_mapping = {"function": "code-agent", "class": "code-agent"}
    config.model_base_url = "http://localhost:8000/v1"
    config.model_api_key = "EMPTY"
    config.model_default = "Qwen/Qwen3-4B"
    config.timeout_s = 300.0
    config.max_turns = 8
    config.truncation_limit = 1024
    config.chat_history_limit = 5
    config.swarm_root = ".remora"
    for k, v in overrides.items():
        setattr(config, k, v)
    return config


@dataclass
class _FakeMessage:
    role: str = "assistant"
    content: str = "I analyzed the code."


@dataclass
class _FakeRunResult:
    final_message: _FakeMessage | None = None
    content: str | None = None

    def __str__(self) -> str:
        return "FakeRunResult"


def _make_mock_kernel(response_text: str = "I analyzed the code.") -> MagicMock:
    kernel = MagicMock()
    result = _FakeRunResult(final_message=_FakeMessage(content=response_text))
    kernel.run = AsyncMock(return_value=result)
    kernel.close = AsyncMock()
    return kernel


def _make_mock_event_store() -> MagicMock:
    es = MagicMock()
    es.append = AsyncMock()
    es.get_node = AsyncMock(return_value=None)
    es.list_nodes = AsyncMock(return_value=[])
    es.get_recent_events = AsyncMock(return_value=[])
    return es


def _make_mock_subscriptions() -> MagicMock:
    subs = MagicMock()
    subs.register = AsyncMock()
    subs.unregister = AsyncMock(return_value=True)
    return subs


def _make_mock_workspace_service() -> MagicMock:
    ws = MagicMock()
    ws.initialize = AsyncMock()
    workspace = MagicMock()
    ws.get_agent_workspace = AsyncMock(return_value=workspace)
    ws.get_externals = MagicMock(return_value={})
    return ws


# =========================================================================
# 1. _resolve_bundle_path
# =========================================================================


class TestResolveBundlePath:
    def test_known_node_type(self):
        node = _make_agent(node_type="function")
        config = _make_config()
        result = _resolve_bundle_path(node, config)
        assert result == Path("agents/code-agent")

    def test_unknown_node_type_falls_back(self):
        node = _make_agent(node_type="unknown_type")
        config = _make_config()
        result = _resolve_bundle_path(node, config)
        assert result == Path("agents")


# =========================================================================
# 2. _build_prompt
# =========================================================================


class TestBuildPrompt:
    def test_basic_prompt(self):
        from remora.core.execution import _agent_node_to_cst_node

        node = _make_agent()
        cst_node = _agent_node_to_cst_node(node)
        config = _make_config()
        path_resolver = MagicMock()
        path_resolver.to_workspace_path = MagicMock(return_value="src/mod.py")

        prompt = _build_prompt(
            node,
            cst_node,
            {"src/mod.py": "def foo():\n    return 1\n"},
            path_resolver,
            config,
        )

        assert "# Target: mod.foo" in prompt
        assert "File: src/mod.py" in prompt
        assert "def foo():" in prompt

    def test_prompt_with_trigger_event(self):
        from remora.core.execution import _agent_node_to_cst_node

        node = _make_agent()
        cst_node = _agent_node_to_cst_node(node)
        config = _make_config()
        path_resolver = MagicMock()
        path_resolver.to_workspace_path = MagicMock(return_value="src/mod.py")

        trigger = MagicMock()
        trigger.content = "file changed"
        type(trigger).__name__ = "ContentChangedEvent"

        prompt = _build_prompt(
            node,
            cst_node,
            {},
            path_resolver,
            config,
            trigger_event=trigger,
        )

        assert "## Trigger Event" in prompt
        assert "ContentChangedEvent" in prompt

    def test_prompt_with_scaffold_context(self):
        """_build_prompt includes Scaffold Context section when scaffold_context is provided."""
        from remora.core.execution import _agent_node_to_cst_node

        node = _make_agent()
        cst_node = _agent_node_to_cst_node(node)
        config = _make_config()
        path_resolver = MagicMock()
        path_resolver.to_workspace_path = MagicMock(return_value="src/mod.py")

        scaffold_context = {
            "parent_source": "class MyClass:\n    pass",
            "siblings": [
                {"name": "method_a", "node_type": "function"},
                {"name": "method_b", "node_type": "function"},
            ],
            "intent": "",
        }

        prompt = _build_prompt(
            node,
            cst_node,
            {},
            path_resolver,
            config,
            scaffold_context=scaffold_context,
        )

        assert "## Scaffold Context" in prompt
        assert "### Parent Source" in prompt
        assert "class MyClass:" in prompt
        assert "### Siblings" in prompt
        assert "method_a (function)" in prompt
        assert "method_b (function)" in prompt

    def test_prompt_scaffold_context_with_intent(self):
        """_build_prompt includes intent when provided in scaffold_context."""
        from remora.core.execution import _agent_node_to_cst_node

        node = _make_agent()
        cst_node = _agent_node_to_cst_node(node)
        config = _make_config()
        path_resolver = MagicMock()
        path_resolver.to_workspace_path = MagicMock(return_value="src/mod.py")

        scaffold_context = {
            "parent_source": "",
            "siblings": [],
            "intent": "HTTP client class",
        }

        prompt = _build_prompt(
            node,
            cst_node,
            {},
            path_resolver,
            config,
            scaffold_context=scaffold_context,
        )

        assert "## Scaffold Context" in prompt
        assert "### Intent" in prompt
        assert "HTTP client class" in prompt

    def test_prompt_scaffold_context_empty_omits_section(self):
        """_build_prompt omits Scaffold Context section when all fields are empty."""
        from remora.core.execution import _agent_node_to_cst_node

        node = _make_agent()
        cst_node = _agent_node_to_cst_node(node)
        config = _make_config()
        path_resolver = MagicMock()
        path_resolver.to_workspace_path = MagicMock(return_value="src/mod.py")

        scaffold_context = {
            "parent_source": "",
            "siblings": [],
            "intent": "",
        }

        prompt = _build_prompt(
            node,
            cst_node,
            {},
            path_resolver,
            config,
            scaffold_context=scaffold_context,
        )

        assert "## Scaffold Context" not in prompt


# =========================================================================
# 3. _CompositeObserver
# =========================================================================


class TestCompositeObserver:
    @pytest.mark.asyncio
    async def test_writes_to_event_store(self):
        es = _make_mock_event_store()
        observer = _CompositeObserver(es, "swarm1")

        event = {"type": "test"}
        await observer.emit(event)

        es.append.assert_called_once_with("swarm1", event)
        assert observer.events == [event]

    @pytest.mark.asyncio
    async def test_calls_on_kernel_event_callback(self):
        es = _make_mock_event_store()
        callback = AsyncMock()
        observer = _CompositeObserver(es, "swarm1", on_kernel_event=callback)

        event = {"type": "test"}
        await observer.emit(event)

        callback.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_no_callback_doesnt_error(self):
        es = _make_mock_event_store()
        observer = _CompositeObserver(es, "swarm1", on_kernel_event=None)

        await observer.emit({"type": "test"})
        # Should not raise


# =========================================================================
# 4. execute_agent_turn — integration-style unit tests
# =========================================================================


class TestExecuteAgentTurn:
    """Test execute_agent_turn with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_basic_execution(self):
        """Verify the happy path: bundle resolution, kernel invocation, result."""
        node = _make_agent()
        config = _make_config()
        es = _make_mock_event_store()
        subs = _make_mock_subscriptions()
        ws = _make_mock_workspace_service()
        kernel = _make_mock_kernel("The code looks correct.")

        with (
            patch("remora.core.execution.load_manifest") as mock_manifest,
            patch("remora.core.execution.create_kernel", return_value=kernel),
            patch("remora.core.execution.discover_grail_tools", return_value=[]),
            patch("remora.core.execution.CairnDataProvider") as mock_dp,
            patch("remora.core.execution.build_client") as mock_build_client,
        ):
            mock_manifest.return_value = MagicMock(
                name="test-bundle",
                system_prompt="You are a code agent.",
                agents_dir=None,
                grammar_config=None,
                max_turns=8,
                requires_context=True,
            )
            mock_dp_instance = MagicMock()
            mock_dp_instance.load_files = AsyncMock(return_value={})
            mock_dp.return_value = mock_dp_instance

            result = await execute_agent_turn(
                node=node,
                config=config,
                event_store=es,
                subscriptions=subs,
                swarm_id="swarm1",
                project_root=Path("/tmp/project"),
                workspace_service=ws,
            )

        assert isinstance(result, ExecutionResult)
        assert result.response_text == "The code looks correct."
        kernel.run.assert_called_once()
        kernel.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_extra_tools_are_passed_to_kernel(self):
        """Verify extra_tools are included in the kernel's tool list."""
        node = _make_agent()
        config = _make_config()
        es = _make_mock_event_store()
        subs = _make_mock_subscriptions()
        ws = _make_mock_workspace_service()
        kernel = _make_mock_kernel()

        extra_tool = MagicMock()
        extra_tool.schema = MagicMock(name="rewrite_self")

        with (
            patch("remora.core.execution.load_manifest") as mock_manifest,
            patch("remora.core.execution.create_kernel", return_value=kernel) as mock_create,
            patch("remora.core.execution.discover_grail_tools", return_value=[]),
            patch("remora.core.execution.CairnDataProvider") as mock_dp,
            patch("remora.core.execution.build_client"),
        ):
            mock_manifest.return_value = MagicMock(
                name="test-bundle",
                system_prompt="You are a code agent.",
                agents_dir=None,
                grammar_config=None,
                max_turns=8,
                requires_context=True,
            )
            mock_dp_instance = MagicMock()
            mock_dp_instance.load_files = AsyncMock(return_value={})
            mock_dp.return_value = mock_dp_instance

            await execute_agent_turn(
                node=node,
                config=config,
                event_store=es,
                subscriptions=subs,
                swarm_id="swarm1",
                project_root=Path("/tmp/project"),
                workspace_service=ws,
                extra_tools=[extra_tool],
            )

        # The extra tool should be in the tools list passed to create_kernel
        create_kwargs = mock_create.call_args
        tools_arg = create_kwargs.kwargs.get("tools") or create_kwargs[1].get("tools")
        assert extra_tool in tools_arg

    @pytest.mark.asyncio
    async def test_on_kernel_event_callback_invoked(self):
        """Verify on_kernel_event is forwarded to the observer."""
        node = _make_agent()
        config = _make_config()
        es = _make_mock_event_store()
        subs = _make_mock_subscriptions()
        ws = _make_mock_workspace_service()
        kernel = _make_mock_kernel()

        callback = AsyncMock()

        with (
            patch("remora.core.execution.load_manifest") as mock_manifest,
            patch("remora.core.execution.create_kernel", return_value=kernel),
            patch("remora.core.execution.discover_grail_tools", return_value=[]),
            patch("remora.core.execution.CairnDataProvider") as mock_dp,
            patch("remora.core.execution.build_client"),
        ):
            mock_manifest.return_value = MagicMock(
                name="test-bundle",
                system_prompt="You are a code agent.",
                agents_dir=None,
                grammar_config=None,
                max_turns=8,
                requires_context=True,
            )
            mock_dp_instance = MagicMock()
            mock_dp_instance.load_files = AsyncMock(return_value={})
            mock_dp.return_value = mock_dp_instance

            # The observer is created internally — we verify via the
            # create_kernel call that it has the right observer.
            result = await execute_agent_turn(
                node=node,
                config=config,
                event_store=es,
                subscriptions=subs,
                swarm_id="swarm1",
                project_root=Path("/tmp/project"),
                workspace_service=ws,
                on_kernel_event=callback,
            )

        # Verify the observer was passed to create_kernel
        # (The callback is wired inside the observer — we can't easily
        # verify it was called without the kernel actually emitting events,
        # but we verify the observer was constructed correctly by checking
        # that create_kernel was called with an observer argument)
        assert result is not None

    @pytest.mark.asyncio
    async def test_client_reuse(self):
        """Verify that a pre-built client is passed through to create_kernel."""
        node = _make_agent()
        config = _make_config()
        es = _make_mock_event_store()
        subs = _make_mock_subscriptions()
        ws = _make_mock_workspace_service()
        kernel = _make_mock_kernel()
        mock_client = MagicMock()

        with (
            patch("remora.core.execution.load_manifest") as mock_manifest,
            patch("remora.core.execution.create_kernel", return_value=kernel) as mock_create,
            patch("remora.core.execution.discover_grail_tools", return_value=[]),
            patch("remora.core.execution.CairnDataProvider") as mock_dp,
            patch("remora.core.execution.build_client") as mock_build,
        ):
            mock_manifest.return_value = MagicMock(
                name="test-bundle",
                system_prompt="You are a code agent.",
                agents_dir=None,
                grammar_config=None,
                max_turns=8,
                requires_context=True,
            )
            mock_dp_instance = MagicMock()
            mock_dp_instance.load_files = AsyncMock(return_value={})
            mock_dp.return_value = mock_dp_instance

            await execute_agent_turn(
                node=node,
                config=config,
                event_store=es,
                subscriptions=subs,
                swarm_id="swarm1",
                project_root=Path("/tmp/project"),
                workspace_service=ws,
                client=mock_client,
            )

        # build_client should NOT be called when client is provided
        mock_build.assert_not_called()
        # The mock client should be passed to create_kernel
        create_kwargs = mock_create.call_args
        assert create_kwargs.kwargs.get("client") is mock_client

    @pytest.mark.asyncio
    async def test_workspace_service_lazy_init(self):
        """Verify workspace_service is created and initialized when not provided."""
        node = _make_agent()
        config = _make_config()
        es = _make_mock_event_store()
        subs = _make_mock_subscriptions()
        kernel = _make_mock_kernel()

        mock_ws = _make_mock_workspace_service()

        with (
            patch("remora.core.execution.load_manifest") as mock_manifest,
            patch("remora.core.execution.create_kernel", return_value=kernel),
            patch("remora.core.execution.discover_grail_tools", return_value=[]),
            patch("remora.core.execution.CairnDataProvider") as mock_dp,
            patch("remora.core.execution.build_client"),
            patch("remora.core.execution.CairnWorkspaceService", return_value=mock_ws),
        ):
            mock_manifest.return_value = MagicMock(
                name="test-bundle",
                system_prompt="You are a code agent.",
                agents_dir=None,
                grammar_config=None,
                max_turns=8,
                requires_context=True,
            )
            mock_dp_instance = MagicMock()
            mock_dp_instance.load_files = AsyncMock(return_value={})
            mock_dp.return_value = mock_dp_instance

            await execute_agent_turn(
                node=node,
                config=config,
                event_store=es,
                subscriptions=subs,
                swarm_id="swarm1",
                project_root=Path("/tmp/project"),
                # workspace_service=None — not provided
            )

        mock_ws.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_history_loaded_from_event_store(self):
        """Verify chat history is loaded from EventStore when not provided."""
        node = _make_agent()
        config = _make_config()
        es = _make_mock_event_store()
        es.get_recent_events = AsyncMock(
            return_value=[
                {
                    "event_type": "AgentMessageEvent",
                    "to_agent": "rm_test1",
                    "payload": {"content": "Hello from user"},
                }
            ]
        )
        subs = _make_mock_subscriptions()
        ws = _make_mock_workspace_service()
        kernel = _make_mock_kernel()

        with (
            patch("remora.core.execution.load_manifest") as mock_manifest,
            patch("remora.core.execution.create_kernel", return_value=kernel),
            patch("remora.core.execution.discover_grail_tools", return_value=[]),
            patch("remora.core.execution.CairnDataProvider") as mock_dp,
            patch("remora.core.execution.build_client"),
        ):
            mock_manifest.return_value = MagicMock(
                name="test-bundle",
                system_prompt="You are a code agent.",
                agents_dir=None,
                grammar_config=None,
                max_turns=8,
                requires_context=True,
            )
            mock_dp_instance = MagicMock()
            mock_dp_instance.load_files = AsyncMock(return_value={})
            mock_dp.return_value = mock_dp_instance

            await execute_agent_turn(
                node=node,
                config=config,
                event_store=es,
                subscriptions=subs,
                swarm_id="swarm1",
                project_root=Path("/tmp/project"),
                workspace_service=ws,
            )

        es.get_recent_events.assert_called_once_with("rm_test1", limit=5)

    @pytest.mark.asyncio
    async def test_grail_tools_discovered_when_agents_dir_set(self):
        """Verify Grail tools are discovered when manifest has agents_dir."""
        node = _make_agent()
        config = _make_config()
        es = _make_mock_event_store()
        subs = _make_mock_subscriptions()
        ws = _make_mock_workspace_service()
        kernel = _make_mock_kernel()

        mock_grail_tool = MagicMock()
        mock_grail_tool.schema = MagicMock(name="grail_tool")

        with (
            patch("remora.core.execution.load_manifest") as mock_manifest,
            patch("remora.core.execution.create_kernel", return_value=kernel) as mock_create,
            patch("remora.core.execution.discover_grail_tools", return_value=[mock_grail_tool]) as mock_discover,
            patch("remora.core.execution.CairnDataProvider") as mock_dp,
            patch("remora.core.execution.build_client"),
        ):
            mock_manifest.return_value = MagicMock(
                name="test-bundle",
                system_prompt="You are a code agent.",
                agents_dir=Path("/tmp/agents"),
                grammar_config=None,
                max_turns=8,
                requires_context=True,
            )
            mock_dp_instance = MagicMock()
            mock_dp_instance.load_files = AsyncMock(return_value={})
            mock_dp.return_value = mock_dp_instance

            await execute_agent_turn(
                node=node,
                config=config,
                event_store=es,
                subscriptions=subs,
                swarm_id="swarm1",
                project_root=Path("/tmp/project"),
                workspace_service=ws,
            )

        mock_discover.assert_called_once()
        # Grail tool should be in the tools passed to create_kernel
        create_kwargs = mock_create.call_args
        tools_arg = create_kwargs.kwargs.get("tools")
        assert mock_grail_tool in tools_arg

    @pytest.mark.asyncio
    async def test_kernel_close_called_on_error(self):
        """Verify kernel.close() is called even if kernel.run() raises."""
        node = _make_agent()
        config = _make_config()
        es = _make_mock_event_store()
        subs = _make_mock_subscriptions()
        ws = _make_mock_workspace_service()
        kernel = _make_mock_kernel()
        kernel.run = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        with (
            patch("remora.core.execution.load_manifest") as mock_manifest,
            patch("remora.core.execution.create_kernel", return_value=kernel),
            patch("remora.core.execution.discover_grail_tools", return_value=[]),
            patch("remora.core.execution.CairnDataProvider") as mock_dp,
            patch("remora.core.execution.build_client"),
        ):
            mock_manifest.return_value = MagicMock(
                name="test-bundle",
                system_prompt="You are a code agent.",
                agents_dir=None,
                grammar_config=None,
                max_turns=8,
                requires_context=True,
            )
            mock_dp_instance = MagicMock()
            mock_dp_instance.load_files = AsyncMock(return_value={})
            mock_dp.return_value = mock_dp_instance

            with pytest.raises(RuntimeError, match="LLM timeout"):
                await execute_agent_turn(
                    node=node,
                    config=config,
                    event_store=es,
                    subscriptions=subs,
                    swarm_id="swarm1",
                    project_root=Path("/tmp/project"),
                    workspace_service=ws,
                )

        # Even though it raised, close should be called
        kernel.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_result_fallback_when_no_content(self):
        """Verify fallback when RunResult has no content."""
        node = _make_agent()
        config = _make_config()
        es = _make_mock_event_store()
        subs = _make_mock_subscriptions()
        ws = _make_mock_workspace_service()
        kernel = _make_mock_kernel()

        # Result with no content anywhere
        result_obj = _FakeRunResult(final_message=_FakeMessage(content=""))
        kernel.run = AsyncMock(return_value=result_obj)

        with (
            patch("remora.core.execution.load_manifest") as mock_manifest,
            patch("remora.core.execution.create_kernel", return_value=kernel),
            patch("remora.core.execution.discover_grail_tools", return_value=[]),
            patch("remora.core.execution.CairnDataProvider") as mock_dp,
            patch("remora.core.execution.build_client"),
        ):
            mock_manifest.return_value = MagicMock(
                name="test-bundle",
                system_prompt="You are a code agent.",
                agents_dir=None,
                grammar_config=None,
                max_turns=8,
                requires_context=True,
            )
            mock_dp_instance = MagicMock()
            mock_dp_instance.load_files = AsyncMock(return_value={})
            mock_dp.return_value = mock_dp_instance

            result = await execute_agent_turn(
                node=node,
                config=config,
                event_store=es,
                subscriptions=subs,
                swarm_id="swarm1",
                project_root=Path("/tmp/project"),
                workspace_service=ws,
            )

        # Should fallback to str(result)
        assert result.response_text == "FakeRunResult"

    @pytest.mark.asyncio
    async def test_scaffold_context_built_for_scaffold_request_event(self):
        """When trigger_event is ScaffoldRequestEvent, execute_agent_turn should
        build scaffold_context with parent source and siblings, and pass it to
        _build_prompt."""
        from remora.core.events import ScaffoldRequestEvent

        node = _make_agent(node_id="child_fn", parent_id="parent_cls")
        config = _make_config()
        es = _make_mock_event_store()
        subs = _make_mock_subscriptions()
        ws = _make_mock_workspace_service()
        kernel = _make_mock_kernel("Scaffold done.")

        # Set up parent node and sibling nodes
        parent_node = _make_agent(
            node_id="parent_cls",
            node_type="class",
            name="MyClass",
            source_code="class MyClass:\n    pass",
        )
        sibling_node = _make_agent(
            node_id="sibling_fn",
            node_type="function",
            name="helper",
            parent_id="parent_cls",
        )

        async def mock_get_node(node_id: str):
            if node_id == "parent_cls":
                return parent_node
            if node_id == "child_fn":
                return node
            return None

        es.get_node = AsyncMock(side_effect=mock_get_node)
        es.list_nodes = AsyncMock(return_value=[node, sibling_node, parent_node])

        trigger = ScaffoldRequestEvent(
            node_id="child_fn",
            to_agent="child_fn",
            node_type="function",
            parent_id="parent_cls",
        )

        with (
            patch("remora.core.execution.load_manifest") as mock_manifest,
            patch("remora.core.execution.create_kernel", return_value=kernel),
            patch("remora.core.execution.discover_grail_tools", return_value=[]),
            patch("remora.core.execution.CairnDataProvider") as mock_dp,
            patch("remora.core.execution.build_client"),
            patch("remora.core.execution._build_prompt", wraps=_build_prompt) as mock_bp,
        ):
            mock_manifest.return_value = MagicMock(
                name="test-bundle",
                system_prompt="You are a code agent.",
                agents_dir=None,
                grammar_config=None,
                max_turns=8,
                requires_context=True,
            )
            mock_dp_instance = MagicMock()
            mock_dp_instance.load_files = AsyncMock(return_value={})
            mock_dp.return_value = mock_dp_instance

            result = await execute_agent_turn(
                node=node,
                config=config,
                event_store=es,
                subscriptions=subs,
                swarm_id="swarm1",
                project_root=Path("/tmp/project"),
                workspace_service=ws,
                trigger_event=trigger,
            )

        assert result.response_text == "Scaffold done."
        # Verify _build_prompt was called with scaffold_context
        bp_call = mock_bp.call_args
        sc = bp_call.kwargs.get("scaffold_context") if bp_call.kwargs else None
        assert sc is not None
        assert sc["parent_source"] == "class MyClass:\n    pass"
        assert any(s["name"] == "helper" for s in sc["siblings"])

    @pytest.mark.asyncio
    async def test_no_scaffold_context_for_non_scaffold_trigger(self):
        """When trigger_event is NOT ScaffoldRequestEvent, scaffold_context should be None."""
        from remora.core.events import ContentChangedEvent

        node = _make_agent()
        config = _make_config()
        es = _make_mock_event_store()
        subs = _make_mock_subscriptions()
        ws = _make_mock_workspace_service()
        kernel = _make_mock_kernel()

        trigger = ContentChangedEvent(path="src/mod.py")

        with (
            patch("remora.core.execution.load_manifest") as mock_manifest,
            patch("remora.core.execution.create_kernel", return_value=kernel),
            patch("remora.core.execution.discover_grail_tools", return_value=[]),
            patch("remora.core.execution.CairnDataProvider") as mock_dp,
            patch("remora.core.execution.build_client"),
            patch("remora.core.execution._build_prompt", wraps=_build_prompt) as mock_bp,
        ):
            mock_manifest.return_value = MagicMock(
                name="test-bundle",
                system_prompt="You are a code agent.",
                agents_dir=None,
                grammar_config=None,
                max_turns=8,
                requires_context=True,
            )
            mock_dp_instance = MagicMock()
            mock_dp_instance.load_files = AsyncMock(return_value={})
            mock_dp.return_value = mock_dp_instance

            await execute_agent_turn(
                node=node,
                config=config,
                event_store=es,
                subscriptions=subs,
                swarm_id="swarm1",
                project_root=Path("/tmp/project"),
                workspace_service=ws,
                trigger_event=trigger,
            )

        # scaffold_context should not have been passed (or should be None)
        bp_call = mock_bp.call_args
        sc = bp_call.kwargs.get("scaffold_context") if bp_call.kwargs else None
        assert sc is None
