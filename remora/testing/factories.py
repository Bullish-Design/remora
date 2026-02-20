from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from remora.config import RunnerConfig, ServerConfig
from remora.discovery import CSTNode, NodeType
from remora.orchestrator import RemoraAgentContext
from remora.subagent import InitialContext, SubagentDefinition, ToolDefinition
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


def make_definition(
    *,
    tools: list[ToolDefinition] | None = None,
    max_turns: int = 10,
    tool_schemas: list[dict[str, Any]] | None = None,
) -> SubagentDefinition:
    if tools is None:
        tools = [
            ToolDefinition(
                tool_name="submit_result",
                pym=Path("submit.pym"),
                tool_description="Submit the result.",
                context_providers=[],
            )
        ]
    definition = SubagentDefinition(
        name="lint_agent",
        max_turns=max_turns,
        initial_context=InitialContext(
            system_prompt="You are a lint agent.",
            node_context="node {{ node_name }} {{ node_type }} {{ node_text }}",
        ),
        tools=tools,
    )
    if tool_schemas is None:
        tool_schemas = [
            tool_schema(
                tool.name,
                tool.tool_description,
                {"type": "object", "additionalProperties": False, "properties": {}},
            )
            for tool in tools
        ]
    definition._tool_schemas = tool_schemas
    return definition


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
