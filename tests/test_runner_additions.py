from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from openai import APIConnectionError

from remora.config import RunnerConfig
from remora.orchestrator import RemoraAgentContext
from remora.runner import FunctionGemmaRunner

from tests.helpers import (
    FakeAsyncOpenAI,
    FakeChatCompletions,
    make_definition,
    make_node,
    make_runner_config,
    make_server_config,
    patch_openai,
    tool_call_message,
)


def test_tool_choice_is_always_configured_value_even_on_last_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    # Setup response (doesn't matter much for this test, but need something)
    patch_openai(monkeypatch, responses=[tool_call_message("submit_result", {})])
    
    definition = make_definition(max_turns=2)
    node = make_node()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=RemoraAgentContext(agent_id="ws-1", task="test", operation="test", node_id="node-1"),
        server_config=make_server_config(),
        runner_config=RunnerConfig(tool_choice="auto"),
    )
    
    # Check turn 1
    assert runner._tool_choice_for_turn(1) == "auto"
    # Check turn 100 (way past max_turns)
    assert runner._tool_choice_for_turn(100) == "auto"


def test_runner_retries_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # We need a FakeAsyncOpenAI that fails once then succeeds
    # Better approach: modify FakeChatCompletions to fail N times
    class FlakyChatCompletions(FakeChatCompletions):
        def __init__(self, responses: list[Any], fail_times: int = 1, error: Exception | None = None) -> None:
            super().__init__(responses)
            self.fail_times = fail_times
            self.failures = 0
            self.error_to_raise = error

        async def create(self, **kwargs: Any) -> Any:
            if self.failures < self.fail_times:
                self.failures += 1
                if self.error_to_raise:
                    raise self.error_to_raise
            return await super().create(**kwargs)

    # Custom factory for this test
    def _flaky_factory(*_: Any, **kwargs: Any) -> FakeAsyncOpenAI:
        client = FakeAsyncOpenAI(
            base_url=kwargs["base_url"],
            api_key=kwargs["api_key"],
            timeout=kwargs["timeout"],
            responses=[tool_call_message("submit_result", {})],
        )
        client.chat.completions = FlakyChatCompletions(
            responses=[tool_call_message("submit_result", {})],
            fail_times=2, # Fail twice, succeed third time
            error=APIConnectionError(message="connection refused", request=cast(Any, None))
        )
        return client

    monkeypatch.setattr("remora.runner.AsyncOpenAI", _flaky_factory)

    definition = make_definition()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=make_node(),
        ctx=RemoraAgentContext(agent_id="ws-1", task="test", operation="test", node_id="node-1"),
        server_config=make_server_config(),
        runner_config=make_runner_config(),
    )

    # fast forward retry usage of asyncio.sleep so test is fast
    async def _fake_sleep(_: float) -> None: pass
    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    result = asyncio.run(runner.run())
    assert result.status == "success"
