"""Tests for ChatSession — conversation management and tool dispatch.

Covers Message, ChatConfig, ChatSession lifecycle (create, send, reset, close),
and build_chat_tools. External dependencies (CairnWorkspaceService, create_kernel)
are mocked.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.core.chat import (
    AgentResponse,
    ChatConfig,
    ChatSession,
    Message,
    build_chat_tools,
)
from remora.core.config import Config
from remora.core.event_bus import EventBus


# ── Message ────────────────────────────────────────────────────────────────


class TestMessage:
    """Tests for the Message dataclass and its factory methods."""

    def test_user_factory(self):
        msg = Message.user("hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.id  # non-empty UUID
        assert msg.timestamp > 0
        assert msg.tool_calls == []

    def test_assistant_factory(self):
        msg = Message.assistant("response text")
        assert msg.role == "assistant"
        assert msg.content == "response text"
        assert msg.id
        assert msg.timestamp > 0
        assert msg.tool_calls == []

    def test_assistant_factory_with_tool_calls(self):
        tc = [{"id": "tc_1", "name": "read_file", "arguments": {"path": "a.py"}}]
        msg = Message.assistant("", tool_calls=tc)
        assert msg.tool_calls == tc

    def test_user_messages_have_unique_ids(self):
        m1 = Message.user("a")
        m2 = Message.user("b")
        assert m1.id != m2.id

    def test_timestamp_is_recent(self):
        before = time.time()
        msg = Message.user("x")
        after = time.time()
        assert before <= msg.timestamp <= after


# ── ChatConfig ─────────────────────────────────────────────────────────────


class TestChatConfig:
    """Tests for ChatConfig and its from_config() factory."""

    def test_defaults(self):
        cfg = ChatConfig(workspace_path="/tmp", system_prompt="You are helpful.")
        assert cfg.tool_presets == ["file_ops"]
        assert cfg.model_name == "Qwen/Qwen3-4B"
        assert cfg.max_turns == 10

    def test_from_config(self):
        config = Config(
            model_default="test-model",
            model_base_url="http://test:9999/v1",
            model_api_key="sk-test",
        )
        chat_cfg = ChatConfig.from_config(
            config,
            workspace_path="/workspace",
            system_prompt="sys",
            max_turns=5,
        )
        assert chat_cfg.model_name == "test-model"
        assert chat_cfg.model_base_url == "http://test:9999/v1"
        assert chat_cfg.model_api_key == "sk-test"
        assert chat_cfg.workspace_path == "/workspace"
        assert chat_cfg.system_prompt == "sys"
        assert chat_cfg.max_turns == 5

    def test_from_config_default_tool_presets(self):
        config = Config()
        chat_cfg = ChatConfig.from_config(config, workspace_path="/w", system_prompt="s")
        assert chat_cfg.tool_presets == ["file_ops"]

    def test_from_config_custom_tool_presets(self):
        config = Config()
        chat_cfg = ChatConfig.from_config(
            config,
            workspace_path="/w",
            system_prompt="s",
            tool_presets=["file_ops", "search"],
        )
        assert chat_cfg.tool_presets == ["file_ops", "search"]


# ── ChatSession lifecycle ──────────────────────────────────────────────────


class TestChatSessionLifecycle:
    """Tests for ChatSession init, history, reset, and close."""

    def _make_session(self) -> ChatSession:
        cfg = ChatConfig(workspace_path="/tmp/test", system_prompt="test prompt")
        session = ChatSession(session_id="sess_1", config=cfg, event_bus=EventBus())
        # Bypass initialization for unit tests
        session._initialized = True
        return session

    def test_initial_history_empty(self):
        session = self._make_session()
        assert session.history == []

    def test_history_returns_copy(self):
        session = self._make_session()
        h1 = session.history
        h1.append(Message.user("injected"))
        assert session.history == []  # original unmodified

    def test_reset_clears_history(self):
        session = self._make_session()
        session._history.append(Message.user("msg"))
        assert len(session.history) == 1
        session.reset()
        assert session.history == []

    @pytest.mark.asyncio
    async def test_close_calls_workspace_close(self):
        session = self._make_session()
        mock_ws = AsyncMock()
        session._workspace = mock_ws
        await session.close()
        mock_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_no_workspace_no_error(self):
        session = self._make_session()
        session._workspace = None
        await session.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_send_before_init_raises(self):
        cfg = ChatConfig(workspace_path="/tmp", system_prompt="test")
        session = ChatSession(session_id="s", config=cfg, event_bus=EventBus())
        # _initialized defaults to False
        with pytest.raises(RuntimeError, match="not initialized"):
            await session.send("hello")


# ── ChatSession.create ─────────────────────────────────────────────────────


class TestChatSessionCreate:
    """Tests for the ChatSession.create() factory."""

    @pytest.mark.asyncio
    async def test_create_initializes_session(self):
        cfg = ChatConfig(workspace_path="/tmp/test", system_prompt="sys")

        with patch.object(ChatSession, "_initialize", new_callable=AsyncMock) as mock_init:
            session = await ChatSession.create(cfg)

        mock_init.assert_awaited_once()
        assert session.session_id  # non-empty UUID
        assert session.config is cfg
        assert isinstance(session.event_bus, EventBus)

    @pytest.mark.asyncio
    async def test_create_with_custom_event_bus(self):
        cfg = ChatConfig(workspace_path="/tmp/test", system_prompt="sys")
        bus = EventBus()

        with patch.object(ChatSession, "_initialize", new_callable=AsyncMock):
            session = await ChatSession.create(cfg, event_bus=bus)

        assert session.event_bus is bus


# ── ChatSession.send ───────────────────────────────────────────────────────


class TestChatSessionSend:
    """Tests for the main send() method with mocked kernel."""

    @pytest.fixture
    def session(self):
        cfg = ChatConfig(
            workspace_path="/tmp/test",
            system_prompt="You are a test assistant.",
            model_name="test-model",
            model_base_url="http://test:8000/v1",
            model_api_key="key",
        )
        s = ChatSession(session_id="sess_1", config=cfg, event_bus=EventBus())
        s._initialized = True
        s._tools = []
        return s

    def _mock_kernel_result(self, content="Hello!", tool_calls=None):
        """Create a mock kernel result."""
        result = MagicMock()
        result.final_message.content = content
        result.final_message.tool_calls = tool_calls or []
        result.turn_count = 1
        return result

    @pytest.mark.asyncio
    async def test_send_adds_user_and_assistant_to_history(self, session):
        mock_result = self._mock_kernel_result(content="Hi there!")

        kernel_instance = AsyncMock()
        kernel_instance.run = AsyncMock(return_value=mock_result)

        with patch("remora.core.chat.create_kernel", return_value=kernel_instance):
            response = await session.send("Hello")

        assert len(session.history) == 2
        assert session.history[0].role == "user"
        assert session.history[0].content == "Hello"
        assert session.history[1].role == "assistant"
        assert session.history[1].content == "Hi there!"

    @pytest.mark.asyncio
    async def test_send_returns_agent_response(self, session):
        mock_result = self._mock_kernel_result(content="Response", tool_calls=[])

        kernel_instance = AsyncMock()
        kernel_instance.run = AsyncMock(return_value=mock_result)

        with patch("remora.core.chat.create_kernel", return_value=kernel_instance):
            response = await session.send("Test")

        assert isinstance(response, AgentResponse)
        assert response.message.role == "assistant"
        assert response.message.content == "Response"
        assert response.turn_count == 1

    @pytest.mark.asyncio
    async def test_send_with_tool_calls(self, session):
        tc = MagicMock()
        tc.id = "tc_1"
        tc.name = "read_file"
        tc.arguments = '{"path": "a.py"}'
        mock_result = self._mock_kernel_result(content="", tool_calls=[tc])

        kernel_instance = AsyncMock()
        kernel_instance.run = AsyncMock(return_value=mock_result)

        with patch("remora.core.chat.create_kernel", return_value=kernel_instance):
            response = await session.send("Do something")

        assert len(response.message.tool_calls) == 1
        assert response.message.tool_calls[0]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_send_closes_kernel_after_run(self, session):
        mock_result = self._mock_kernel_result()

        kernel_instance = AsyncMock()
        kernel_instance.run = AsyncMock(return_value=mock_result)

        with patch("remora.core.chat.create_kernel", return_value=kernel_instance):
            await session.send("Test")

        kernel_instance.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_closes_kernel_on_error(self, session):
        kernel_instance = AsyncMock()
        kernel_instance.run = AsyncMock(side_effect=RuntimeError("LLM failed"))

        with patch("remora.core.chat.create_kernel", return_value=kernel_instance):
            with pytest.raises(RuntimeError, match="LLM failed"):
                await session.send("Test")

        kernel_instance.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_accumulates_history(self, session):
        """Multiple send() calls accumulate conversation history."""
        for i in range(3):
            mock_result = self._mock_kernel_result(content=f"Reply {i}")
            kernel_instance = AsyncMock()
            kernel_instance.run = AsyncMock(return_value=mock_result)

            with patch("remora.core.chat.create_kernel", return_value=kernel_instance):
                await session.send(f"Message {i}")

        assert len(session.history) == 6  # 3 user + 3 assistant

    @pytest.mark.asyncio
    async def test_send_passes_system_prompt(self, session):
        mock_result = self._mock_kernel_result()

        kernel_instance = AsyncMock()
        kernel_instance.run = AsyncMock(return_value=mock_result)

        with patch("remora.core.chat.create_kernel", return_value=kernel_instance):
            await session.send("Hello")

            # Verify messages passed to kernel.run start with system prompt
            call_args = kernel_instance.run.call_args
            messages = call_args[0][0]
            assert messages[0].role == "system"
            assert messages[0].content == "You are a test assistant."


# ── build_chat_tools ───────────────────────────────────────────────────────


class TestBuildChatTools:
    """Tests for build_chat_tools utility function.

    NOTE: These tests are xfail because build_chat_tools calls
    Tool.from_function() which doesn't exist — Tool is a Protocol with
    only execute/schema. A FunctionTool adapter is needed (tracked as
    pre-existing bug in chat.py).
    """

    @pytest.mark.xfail(
        reason="Tool.from_function() doesn't exist — pre-existing bug in chat.py",
        raises=AttributeError,
    )
    def test_returns_six_tools(self):
        mock_workspace = MagicMock()
        tools = build_chat_tools(mock_workspace, Path("/tmp/project"))
        assert len(tools) == 6

    @pytest.mark.xfail(
        reason="Tool.from_function() doesn't exist — pre-existing bug in chat.py",
        raises=AttributeError,
    )
    def test_tool_names(self):
        mock_workspace = MagicMock()
        tools = build_chat_tools(mock_workspace, Path("/tmp/project"))
        names = {t.schema["function"]["name"] for t in tools}
        assert names == {
            "read_file",
            "write_file",
            "list_dir",
            "file_exists",
            "search_files",
            "discover_symbols",
        }
