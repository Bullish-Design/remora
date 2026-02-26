"""Tests for public API surface."""


def test_all_exports_importable() -> None:
    """Verify all __all__ exports are importable."""
    import structured_agents

    for name in structured_agents.__all__:
        obj = getattr(structured_agents, name)
        assert obj is not None, f"Export {name} is None"


def test_version_exists() -> None:
    import structured_agents

    assert hasattr(structured_agents, "__version__")
    assert isinstance(structured_agents.__version__, str)


def test_core_classes_importable() -> None:
    from structured_agents import (
        AgentKernel,
        Agent,
        AgentManifest,
        ModelAdapter,
        Message,
        ToolCall,
        ToolResult,
        ToolSchema,
        TokenUsage,
        StepResult,
        RunResult,
        build_client,
        LLMClient,
        OpenAICompatibleClient,
    )

    assert AgentKernel.__name__ == "AgentKernel"
    assert Agent.__name__ == "Agent"
    assert AgentManifest.__name__ == "AgentManifest"
    assert ModelAdapter.__name__ == "ModelAdapter"
    assert Message.__name__ == "Message"
    assert ToolCall.__name__ == "ToolCall"
    assert ToolResult.__name__ == "ToolResult"
    assert ToolSchema.__name__ == "ToolSchema"
    assert TokenUsage.__name__ == "TokenUsage"
    assert StepResult.__name__ == "StepResult"
    assert RunResult.__name__ == "RunResult"
    assert build_client.__name__ == "build_client"
    assert LLMClient.__name__ == "LLMClient"
    assert OpenAICompatibleClient.__name__ == "OpenAICompatibleClient"
