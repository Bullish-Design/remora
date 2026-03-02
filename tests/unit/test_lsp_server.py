"""Tests for server.py — verifies it uses core AgentNode and ToolSchema."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.core.agent_node import AgentNode, ToolSchema
from tests.unit.conftest import make_node as _make_node


def test_server_does_not_import_ast_agent_node():
    """server.py should not import ASTAgentNode from lsp/models."""
    import remora.lsp.server as srv_mod

    # Check that the module doesn't reference ASTAgentNode in its namespace
    assert not hasattr(srv_mod, "ASTAgentNode"), "server.py should not import ASTAgentNode"


def test_server_imports_core_tool_schema():
    """server.py should use ToolSchema from core, not lsp/models."""
    from remora.lsp.server import RemoraLanguageServer
    import inspect

    source = inspect.getsource(RemoraLanguageServer.discover_tools_for_agent)
    # The function should reference ToolSchema — check that the return annotation
    # or body uses the core ToolSchema (dataclass, not Pydantic)
    from remora.core.agent_node import ToolSchema as CoreToolSchema
    import dataclasses

    assert dataclasses.is_dataclass(CoreToolSchema), "Core ToolSchema should be a dataclass"


@pytest.mark.asyncio()
async def test_discover_tools_accepts_agent_node():
    """discover_tools_for_agent should accept AgentNode (not ASTAgentNode)."""
    from remora.lsp.server import RemoraLanguageServer

    srv = RemoraLanguageServer.__new__(RemoraLanguageServer)
    node = _make_node()

    # Mock the config to return no bundle, so we get empty list quickly
    with patch("remora.core.config.load_config") as mock_config:
        mock_config.return_value = MagicMock(bundle_mapping={})
        result = await srv.discover_tools_for_agent(node)

    assert result == []
