from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from remora.config import RunnerConfig, ServerConfig
from remora.constants import TERMINATION_TOOL
from remora.discovery import CSTNode, NodeType
from remora.orchestrator import RemoraAgentContext
from remora.testing.fakes import FakeCompletionMessage, FakeToolCall


def make_ctx(agent_id: str = "ws-1", operation: str = "lint") -> RemoraAgentContext:
    return RemoraAgentContext(
        agent_id=agent_id,
        task=f"{operation} on hello",
        operation=operation,
        node_id="node-1",
    )


def tool_schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


def make_node() -> CSTNode:
    return CSTNode(
        node_id="node-1",
        node_type=NodeType.FUNCTION,
        name="hello",
        file_path=Path("src/example.py"),
        start_byte=0,
        end_byte=10,
        text="def hello(): ...",
        start_line=1,
        end_line=1,
    )


def make_server_config() -> ServerConfig:
    return ServerConfig(
        base_url="http://remora-server:8000/v1",
        api_key="EMPTY",
        timeout=30,
        default_adapter="google/functiongemma-270m-it",
    )


def make_runner_config() -> RunnerConfig:
    return RunnerConfig(max_tokens=128, temperature=0.0, tool_choice="required")


def tool_call_message(name: str, arguments: dict[str, Any], *, call_id: str = "call-1") -> FakeCompletionMessage:
    return FakeCompletionMessage(tool_calls=[FakeToolCall(name=name, arguments=json.dumps(arguments), call_id=call_id)])
