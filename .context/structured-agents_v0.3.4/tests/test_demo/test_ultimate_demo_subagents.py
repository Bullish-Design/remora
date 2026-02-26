from demo.ultimate_demo.state import DemoState
from demo.ultimate_demo.subagents import SubagentSpec, SubagentTool


def test_subagent_spec_structures() -> None:
    spec = SubagentSpec(
        name="risk_analyst",
        description="Analyze delivery risks",
        system_prompt="Identify risks and mitigations.",
    )

    assert spec.name == "risk_analyst"
    assert spec.description == "Analyze delivery risks"
    assert spec.system_prompt == "Identify risks and mitigations."

    tool = SubagentTool(state=DemoState.initial(), spec=spec)
    schema = tool.schema

    assert schema.name == "risk_analyst"
    assert schema.description == "Analyze delivery risks"
    assert schema.parameters["type"] == "object"
    assert schema.parameters["properties"]["task"]["type"] == "string"
    assert schema.parameters["required"] == ["task"]
