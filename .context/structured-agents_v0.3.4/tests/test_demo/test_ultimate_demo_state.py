from demo.ultimate_demo.state import DemoState, TaskItem


def test_state_tracks_tasks() -> None:
    state = DemoState.initial()
    state.tasks.append(TaskItem(title="Kickoff", status="open"))
    assert state.tasks[0].title == "Kickoff"
