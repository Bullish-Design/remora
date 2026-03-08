"""Tests for MicroSwarm base and orchestration."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from remora.companion.swarms.base import SwarmContext, run_post_exchange_swarms


def make_ctx(**overrides):
    node = MagicMock()
    node.name = "my_func"
    node.node_id = "node_abc"
    defaults = dict(
        node_id="node_abc",
        node=node,
        workspace=MagicMock(),
        session_id="session_1",
        user_message="Why does this break?",
        assistant_message="It breaks because of the off-by-one on line 42.",
        event_bus=AsyncMock(),
        model_name="test-model",
        model_base_url="http://localhost:8000/v1",
        model_api_key="",
    )
    defaults.update(overrides)
    return SwarmContext(**defaults)


@pytest.mark.asyncio
async def test_run_post_exchange_swarms_all_run():
    called = []

    class FakeSwarm:
        async def run(self, ctx):
            called.append(type(self).__name__)

    await run_post_exchange_swarms(make_ctx(), [FakeSwarm(), FakeSwarm()])
    assert len(called) == 2


@pytest.mark.asyncio
async def test_run_post_exchange_swarms_failure_does_not_propagate():
    class BadSwarm:
        async def run(self, ctx):
            raise RuntimeError("swarm failed")

    class GoodSwarm:
        async def run(self, ctx):
            return None

    await run_post_exchange_swarms(make_ctx(), [BadSwarm(), GoodSwarm()])
