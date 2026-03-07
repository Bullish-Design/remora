"""TDD for W4: core events are split into bounded modules."""


def test_bounded_event_modules_are_importable():
    from remora.core.events.agent_events import AgentStartEvent
    from remora.core.events.code_events import NodeDiscoveredEvent
    from remora.core.events.interaction_events import AgentMessageEvent
    from remora.core.events.kernel_events import KernelStartEvent

    assert AgentStartEvent.__name__ == "AgentStartEvent"
    assert AgentMessageEvent.__name__ == "AgentMessageEvent"
    assert NodeDiscoveredEvent.__name__ == "NodeDiscoveredEvent"
    assert KernelStartEvent.__name__ == "KernelStartEvent"
