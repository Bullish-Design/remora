# tests/test_models/test_adapter.py
from dataclasses import dataclass
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.models.adapter import ModelAdapter
from structured_agents.types import ToolSchema, ToolCall, ToolResult, TokenUsage
from structured_agents.grammar.config import DecodingConstraint


@dataclass
class MockParser:
    def parse(self, content, tool_calls):
        return content, []


def test_model_adapter_creation():
    pipeline = ConstraintPipeline(DecodingConstraint())
    adapter = ModelAdapter(
        name="test_model",
        response_parser=MockParser(),
        constraint_pipeline=pipeline,
    )
    assert adapter.name == "test_model"
    assert adapter.constraint_pipeline is pipeline


def test_model_adapter_format_messages_default():
    adapter = ModelAdapter(
        name="test",
        response_parser=MockParser(),
    )
    from structured_agents.types import Message

    msg = Message(role="user", content="hello")
    formatter = adapter.format_messages
    assert formatter is not None
    result = formatter([msg])
    assert result[0]["role"] == "user"
