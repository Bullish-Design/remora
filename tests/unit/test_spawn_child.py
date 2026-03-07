"""Tests for the spawn_child tool.

The spawn_child tool allows any agent to create a new scaffold child node.
It writes a stub to disk, emits NodeDiscoveredEvent + ScaffoldRequestEvent,
and returns the new node_id.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from remora.core.agents.agent_context import AgentContext
from remora.core.tools.spawn_child import SpawnChildTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(**overrides: Any) -> AgentContext:
    defaults = {
        "agent_id": "parent_agent_1",
        "emit_event": AsyncMock(),
        "register_subscription": AsyncMock(),
        "unsubscribe_subscription": AsyncMock(),
        "broadcast": AsyncMock(),
        "query_agents": AsyncMock(return_value=[]),
    }
    defaults.update(overrides)
    return AgentContext(**defaults)


def _make_tool_call(call_id: str = "call_1") -> MagicMock:
    tc = MagicMock()
    tc.id = call_id
    return tc


# =========================================================================
# Schema
# =========================================================================


class TestSpawnChildSchema:
    """Verify the tool has the correct schema."""

    def test_tool_name(self, tmp_path):
        ctx = _make_context()
        tool = SpawnChildTool(ctx, project_root=tmp_path)
        assert tool.schema.name == "spawn_child"

    def test_required_parameters(self, tmp_path):
        ctx = _make_context()
        tool = SpawnChildTool(ctx, project_root=tmp_path)
        params = tool.schema.parameters
        assert "node_type" in params["properties"]
        assert "name" in params["properties"]
        assert "intent" in params["properties"]
        assert set(params["required"]) == {"node_type", "name"}


# =========================================================================
# Stub generation
# =========================================================================


class TestSpawnChildStubGeneration:
    """Verify that spawn_child writes appropriate stubs to disk."""

    @pytest.mark.asyncio
    async def test_class_stub_written(self, tmp_path):
        ctx = _make_context()
        tool = SpawnChildTool(ctx, project_root=tmp_path)
        file_path = str(tmp_path / "src" / "models.py")
        (tmp_path / "src").mkdir(parents=True)
        (tmp_path / "src" / "models.py").write_text("# existing content\n")

        result = await tool.execute(
            {"node_type": "class", "name": "HttpClient", "file_path": file_path},
            _make_tool_call(),
        )

        assert not result.is_error
        content = (tmp_path / "src" / "models.py").read_text()
        assert "class HttpClient: pass" in content

    @pytest.mark.asyncio
    async def test_function_stub_written(self, tmp_path):
        ctx = _make_context()
        tool = SpawnChildTool(ctx, project_root=tmp_path)
        file_path = str(tmp_path / "src" / "utils.py")
        (tmp_path / "src").mkdir(parents=True)
        (tmp_path / "src" / "utils.py").write_text("# existing content\n")

        result = await tool.execute(
            {"node_type": "function", "name": "process_data", "file_path": file_path},
            _make_tool_call(),
        )

        assert not result.is_error
        content = (tmp_path / "src" / "utils.py").read_text()
        assert "def process_data(): pass" in content

    @pytest.mark.asyncio
    async def test_file_stub_creates_empty_file(self, tmp_path):
        ctx = _make_context()
        tool = SpawnChildTool(ctx, project_root=tmp_path)
        file_path = str(tmp_path / "src" / "new_module.py")
        (tmp_path / "src").mkdir(parents=True)

        result = await tool.execute(
            {"node_type": "file", "name": "new_module.py", "file_path": file_path},
            _make_tool_call(),
        )

        assert not result.is_error
        assert (tmp_path / "src" / "new_module.py").exists()

    @pytest.mark.asyncio
    async def test_class_stub_appended_to_existing_file(self, tmp_path):
        ctx = _make_context()
        tool = SpawnChildTool(ctx, project_root=tmp_path)
        existing_file = tmp_path / "module.py"
        existing_file.write_text("import os\n\ndef existing(): pass\n")

        result = await tool.execute(
            {"node_type": "class", "name": "NewClass", "file_path": str(existing_file)},
            _make_tool_call(),
        )

        assert not result.is_error
        content = existing_file.read_text()
        assert "import os" in content  # Original preserved
        assert "class NewClass: pass" in content


# =========================================================================
# Event emission
# =========================================================================


class TestSpawnChildEvents:
    """Verify that spawn_child emits the correct events."""

    @pytest.mark.asyncio
    async def test_emits_node_discovered_event(self, tmp_path):
        emit_mock = AsyncMock()
        ctx = _make_context(emit_event=emit_mock)
        tool = SpawnChildTool(ctx, project_root=tmp_path)
        file_path = str(tmp_path / "app.py")
        (tmp_path / "app.py").write_text("")

        await tool.execute(
            {"node_type": "function", "name": "do_work", "file_path": file_path},
            _make_tool_call(),
        )

        # Should have been called twice: NodeDiscoveredEvent + ScaffoldRequestEvent
        assert emit_mock.call_count == 2
        first_call = emit_mock.call_args_list[0]
        assert first_call[0][0] == "NodeDiscoveredEvent"
        event = first_call[0][1]
        assert event.node_type == "function"
        assert event.name == "do_work"
        assert event.parent_id == "parent_agent_1"

    @pytest.mark.asyncio
    async def test_emits_scaffold_request_event(self, tmp_path):
        emit_mock = AsyncMock()
        ctx = _make_context(emit_event=emit_mock)
        tool = SpawnChildTool(ctx, project_root=tmp_path)
        file_path = str(tmp_path / "app.py")
        (tmp_path / "app.py").write_text("")

        await tool.execute(
            {
                "node_type": "class",
                "name": "Worker",
                "file_path": file_path,
                "intent": "Background job processor",
            },
            _make_tool_call(),
        )

        second_call = emit_mock.call_args_list[1]
        assert second_call[0][0] == "ScaffoldRequestEvent"
        event = second_call[0][1]
        assert event.node_type == "class"
        assert event.intent == "Background job processor"
        assert event.parent_id == "parent_agent_1"

    @pytest.mark.asyncio
    async def test_emits_scaffold_request_with_empty_intent(self, tmp_path):
        emit_mock = AsyncMock()
        ctx = _make_context(emit_event=emit_mock)
        tool = SpawnChildTool(ctx, project_root=tmp_path)
        file_path = str(tmp_path / "app.py")
        (tmp_path / "app.py").write_text("")

        await tool.execute(
            {"node_type": "function", "name": "helper", "file_path": file_path},
            _make_tool_call(),
        )

        second_call = emit_mock.call_args_list[1]
        event = second_call[0][1]
        assert event.intent == ""


# =========================================================================
# Return value
# =========================================================================


class TestSpawnChildReturn:
    """Verify the tool returns the new node_id."""

    @pytest.mark.asyncio
    async def test_returns_node_id_in_output(self, tmp_path):
        ctx = _make_context()
        tool = SpawnChildTool(ctx, project_root=tmp_path)
        file_path = str(tmp_path / "mod.py")
        (tmp_path / "mod.py").write_text("")

        result = await tool.execute(
            {"node_type": "function", "name": "my_func", "file_path": file_path},
            _make_tool_call(),
        )

        assert not result.is_error
        output = json.loads(result.output)
        assert "node_id" in output
        assert isinstance(output["node_id"], str)
        assert len(output["node_id"]) > 0

    @pytest.mark.asyncio
    async def test_returns_file_path_in_output(self, tmp_path):
        ctx = _make_context()
        tool = SpawnChildTool(ctx, project_root=tmp_path)
        file_path = str(tmp_path / "mod.py")
        (tmp_path / "mod.py").write_text("")

        result = await tool.execute(
            {"node_type": "function", "name": "my_func", "file_path": file_path},
            _make_tool_call(),
        )

        output = json.loads(result.output)
        assert "file_path" in output


# =========================================================================
# Error handling
# =========================================================================


class TestSpawnChildErrors:
    """Verify error cases are handled gracefully."""

    @pytest.mark.asyncio
    async def test_missing_name_returns_error(self, tmp_path):
        ctx = _make_context()
        tool = SpawnChildTool(ctx, project_root=tmp_path)

        result = await tool.execute(
            {"node_type": "function"},
            _make_tool_call(),
        )

        assert result.is_error

    @pytest.mark.asyncio
    async def test_missing_node_type_returns_error(self, tmp_path):
        ctx = _make_context()
        tool = SpawnChildTool(ctx, project_root=tmp_path)

        result = await tool.execute(
            {"name": "foo"},
            _make_tool_call(),
        )

        assert result.is_error

    @pytest.mark.asyncio
    async def test_invalid_node_type_returns_error(self, tmp_path):
        ctx = _make_context()
        tool = SpawnChildTool(ctx, project_root=tmp_path)

        result = await tool.execute(
            {"node_type": "invalid_type", "name": "foo", "file_path": str(tmp_path / "x.py")},
            _make_tool_call(),
        )

        assert result.is_error
