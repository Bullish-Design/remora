import asyncio

from demo.ultimate_demo.coordinator import build_demo_state
from demo.ultimate_demo.runner import DemoRunner
from demo.ultimate_demo.state import DemoState
from structured_agents.types import Message, RunResult


class FakeAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, user_input: str, **kwargs) -> RunResult:
        self.calls.append(user_input)
        reply = Message(role="assistant", content=f"Echo: {user_input}")
        return RunResult(
            final_message=reply,
            history=[reply],
            turn_count=1,
            termination_reason="no_tool_calls",
        )


def test_runner_builds_state() -> None:
    state = build_demo_state()
    assert state == DemoState.initial()

    fake_agent = FakeAgent()
    runner = DemoRunner(
        state=state,
        agent=fake_agent,
        tool_names=["log_update"],
        subagent_names=["risk_analyst"],
    )
    result_state = asyncio.run(runner.run(["Kickoff", "Wrap up"]))

    assert result_state is state
    assert result_state.inbox == ["Kickoff", "Wrap up"]
    assert result_state.outbox == ["Echo: Kickoff", "Echo: Wrap up"]
    assert fake_agent.calls == ["Kickoff", "Wrap up"]
