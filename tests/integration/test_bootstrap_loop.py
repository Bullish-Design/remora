from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.integration.helpers import agentfs_available

from remora.bootstrap.activation import handle_agent_needed
from remora.bootstrap.coordinator import emit_agent_needed_events
from remora.bootstrap.turn_executor import TurnResult
from remora.core.agents.cairn_bridge import CairnWorkspaceService
from remora.core.code.projections import NodeProjection
from remora.core.config import Config
from remora.core.events.code_events import NodeDiscoveredEvent
from remora.core.events.subscriptions import SubscriptionRegistry
from remora.core.store.event_store import EventStore


@pytest.mark.asyncio
async def test_bootstrap_loop_emits_and_handles_agent_needed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS (fsdantic) is unavailable")

    project_root = tmp_path / "project"
    (project_root / "src").mkdir(parents=True)
    (project_root / "src" / "app.py").write_text("def run() -> None:\n    pass\n", encoding="utf-8")

    bootstrap_root = tmp_path / "bootstrap"
    (bootstrap_root / "tools").mkdir(parents=True)
    (bootstrap_root / "agents").mkdir(parents=True)

    config = Config(
        project_path=str(project_root),
        swarm_root=str(tmp_path / ".remora"),
        swarm_id="bootstrap-test",
        model_base_url="http://localhost:8000/v1",
        model_default="Qwen/Qwen3-4B",
        model_api_key="",
        timeout_s=30.0,
    )

    subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await subscriptions.initialize()

    event_store = EventStore(
        tmp_path / "events.db",
        projection=NodeProjection(),
        subscriptions=subscriptions,
    )
    await event_store.initialize()

    workspace_service = CairnWorkspaceService(
        config,
        graph_id="bootstrap-test",
        project_root=project_root,
    )

    async def _fake_run(self, activation_event=None):  # noqa: ANN001
        del activation_event
        await self._cairn_externals.write_file("role.md", "Owner of src/app.py")
        await self._cairn_externals.write_file("notes.md", "Initial bootstrap notes")
        await self._cairn_externals.write_file(
            "schema.yaml",
            (
                'version: "1"\n'
                "name: loop_agent\n"
                'system: "You are loop agent."\n'
                "tools:\n"
                "  - read_file\n"
                "subscriptions:\n"
                "  - event_type: ContentChangedEvent\n"
                'termination: "DONE"\n'
            ),
        )
        await self._cairn_externals.write_file(
            "tools/node_context.pym",
            "async def node_context() -> str:\n    return 'ok'\n",
        )
        return TurnResult(response_text="DONE", context_values={})

    monkeypatch.setattr("remora.bootstrap.activation.TurnExecutor.run", _fake_run)

    try:
        await event_store.append(
            "bootstrap-test",
            NodeDiscoveredEvent(
                node_id="module:src/app.py",
                node_type="file",
                name="app.py",
                full_name="src.app",
                file_path="src/app.py",
                start_line=1,
                end_line=2,
                source_code="def run() -> None:\n    pass\n",
                source_hash="hash-app",
            ),
        )

        emitted = await emit_agent_needed_events(
            event_store,
            swarm_id="bootstrap-test",
            coordinator_id="coordinator",
        )
        assert emitted == 1

        events = [event async for event in event_store.replay("bootstrap-test")]
        needed_events = [event for event in events if event["event_type"] == "AgentNeededEvent"]
        assert len(needed_events) == 1
        activation_event = SimpleNamespace(**needed_events[0])

        result = await handle_agent_needed(
            activation_event,
            workspace_service=workspace_service,
            subscriptions=subscriptions,
            event_store=event_store,
            config=config,
            swarm_id="bootstrap-test",
            bootstrap_root=bootstrap_root,
        )

        assert result.node_id == "module:src/app.py"
        assert result.agent_id.startswith("agent-")

        agent_node_raw = await event_store.nodes.read_graph({"node": result.agent_id})
        assert '"kind": "agent"' in agent_node_raw
        assert '"assigned_node_id": "module:src/app.py"' in agent_node_raw

        registered = await subscriptions.get_subscriptions(result.agent_id)
        direct = [sub for sub in registered if sub.pattern.to_agent == result.agent_id]
        content = [sub for sub in registered if sub.pattern.event_types == ["ContentChangedEvent"]]
        assert direct
        assert content

        all_events = [event async for event in event_store.replay("bootstrap-test")]
        synthesized = [event for event in all_events if event["event_type"] == "ToolSynthesizedEvent"]
        assert len(synthesized) == 1
        assert synthesized[0]["payload"]["tool_name"] == "node_context"
    finally:
        await workspace_service.close()
        await event_store.close()
        await subscriptions.close()
