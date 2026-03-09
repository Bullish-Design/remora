from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from remora.bootstrap.schema_loader import ContextStep, TurnSchema
from remora.bootstrap.turn_executor import TurnExecutor


class FakeTool:
    def __init__(self, name: str, *, output: str = "", is_error: bool = False) -> None:
        self.schema = SimpleNamespace(name=name)
        self._output = output
        self._is_error = is_error
        self.calls: list[tuple[dict[str, object], object]] = []

    async def execute(self, arguments: dict[str, object], context: object | None = None):
        self.calls.append((arguments, context))
        return SimpleNamespace(output=self._output, is_error=self._is_error)


class FakeKernel:
    def __init__(self, result: object) -> None:
        self.result = result
        self.run_calls: list[tuple[list[object], list[object], int]] = []
        self.closed = False

    async def run(self, messages: list[object], tool_schemas: list[object], max_turns: int):
        self.run_calls.append((messages, tool_schemas, max_turns))
        return self.result

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_run_executes_context_pipeline_and_dispatches_kernel(monkeypatch: pytest.MonkeyPatch) -> None:
    schema = TurnSchema(
        name="bootstrap_agent",
        system="You are {node.node_id}. Context={{ctx}}",
        context=[ContextStep(name="ctx", tool="read_file", args={"path": "{node.file_path}"})],
        tools=["read_file", "write_file", "missing_tool"],
        max_turns=7,
    )

    async def _fake_load_schema(*args, **kwargs):
        return schema

    monkeypatch.setattr("remora.bootstrap.turn_executor.load_schema", _fake_load_schema)

    read_tool = FakeTool("read_file", output="ROLE:builder")
    write_tool = FakeTool("write_file", output="ok")

    fake_result = SimpleNamespace(final_message=SimpleNamespace(content="DONE"))
    fake_kernel = FakeKernel(fake_result)
    kernel_args: dict[str, object] = {}

    def _fake_create_kernel(**kwargs):
        kernel_args.update(kwargs)
        return fake_kernel

    build_client = MagicMock(return_value=object())
    monkeypatch.setattr("remora.bootstrap.turn_executor.build_client", build_client)
    monkeypatch.setattr("remora.bootstrap.turn_executor.create_kernel", _fake_create_kernel)

    config = SimpleNamespace(
        model_base_url="http://localhost:8000/v1",
        model_api_key="",
        model_default="Qwen/Qwen3-4B",
        timeout_s=30.0,
    )

    executor = TurnExecutor(
        agent_id="agent-1",
        cairn_externals=SimpleNamespace(),
        tools=[read_tool, write_tool],
        node_attrs={"node_id": "node:file:1", "file_path": "src/app.py"},
        config=config,
    )

    result = await executor.run(SimpleNamespace(event_type="AgentNeededEvent", node_id="node:file:1"))

    assert result.response_text == "DONE"
    assert result.context_values == {"ctx": "ROLE:builder"}
    assert read_tool.calls[0][0] == {"path": "src/app.py"}
    assert read_tool.calls[0][1] is None

    assert kernel_args["tools"] == [read_tool, write_tool]
    assert kernel_args["model_name"] == "Qwen/Qwen3-4B"
    build_client.assert_called_once()

    messages, tool_schemas, max_turns = fake_kernel.run_calls[0]
    assert messages[0].content == "You are node:file:1. Context=ROLE:builder"
    assert "Activation event: AgentNeededEvent" in messages[1].content
    assert "Node: node:file:1" in messages[1].content
    assert [schema.name for schema in tool_schemas] == ["read_file", "write_file"]
    assert max_turns == 7
    assert fake_kernel.closed


@pytest.mark.asyncio
async def test_run_reuses_client_and_tolerates_optional_missing_context_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = TurnSchema(
        name="bootstrap_agent",
        system="Context={{maybe}}",
        context=[ContextStep(name="maybe", tool="missing_tool", optional=True)],
        tools=[],
        max_turns=2,
    )

    async def _fake_load_schema(*args, **kwargs):
        return schema

    monkeypatch.setattr("remora.bootstrap.turn_executor.load_schema", _fake_load_schema)

    sentinel_client = object()
    build_client = MagicMock(side_effect=AssertionError("build_client should not be called"))
    monkeypatch.setattr("remora.bootstrap.turn_executor.build_client", build_client)

    fake_result = SimpleNamespace(content="fallback")
    fake_kernel = FakeKernel(fake_result)
    kernel_args: dict[str, object] = {}

    def _fake_create_kernel(**kwargs):
        kernel_args.update(kwargs)
        return fake_kernel

    monkeypatch.setattr("remora.bootstrap.turn_executor.create_kernel", _fake_create_kernel)

    config = SimpleNamespace(
        model_base_url="http://localhost:8000/v1",
        model_api_key="",
        model_default="Qwen/Qwen3-4B",
        timeout_s=30.0,
    )

    executor = TurnExecutor(
        agent_id="agent-1",
        cairn_externals=SimpleNamespace(),
        tools=[],
        node_attrs={},
        config=config,
        client=sentinel_client,
    )

    result = await executor.run()

    assert result.response_text == "fallback"
    assert result.context_values == {"maybe": ""}
    assert kernel_args["client"] is sentinel_client
    assert fake_kernel.closed
