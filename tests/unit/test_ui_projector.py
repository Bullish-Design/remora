from remora.core.events import (
    AgentCompleteEvent,
    AgentStartEvent,
    GraphStartEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
)
from remora.ui.projector import UiStateProjector, normalize_event


def test_projector_tracks_progress_and_blocked() -> None:
    projector = UiStateProjector()
    projector.record(GraphStartEvent(graph_id="graph-1", node_count=2))
    projector.record(AgentStartEvent(graph_id="graph-1", agent_id="agent-1", node_name="agent-1"))
    projector.record(
        HumanInputRequestEvent(
            graph_id="graph-1",
            agent_id="agent-1",
            request_id="req-1",
            question="Continue?",
            options=("yes", "no"),
        )
    )

    snapshot = projector.snapshot()
    assert snapshot["progress"]["total"] == 2
    assert snapshot["blocked"][0]["request_id"] == "req-1"

    projector.record(HumanInputResponseEvent(request_id="req-1", response="yes"))
    snapshot = projector.snapshot()
    assert snapshot["blocked"] == []


def test_projector_records_results() -> None:
    projector = UiStateProjector()
    projector.record(
        AgentCompleteEvent(
            graph_id="graph-1",
            agent_id="agent-1",
            result_summary="ok",
        )
    )
    snapshot = projector.snapshot()
    assert snapshot["results"][0]["content"] == "ok"


def test_normalize_event_envelope() -> None:
    envelope = normalize_event(GraphStartEvent(graph_id="graph-1", node_count=1))
    assert envelope["kind"] == "graph"
    assert envelope["type"] == "GraphStartEvent"
    assert envelope["graph_id"] == "graph-1"
