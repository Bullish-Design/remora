"""Validate all production agents after refactoring."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from remora.config import load_config
from remora.subagent import load_subagent_definition


async def validate_agent(agent_name: str, agents_dir: Path) -> bool:
    """Validate an agent loads correctly and has proper configuration."""
    try:
        yaml_path = agents_dir / agent_name / f"{agent_name}_subagent.yaml"
        if not yaml_path.exists():
            print(f"  {agent_name}: SKIP (no yaml file)")
            return True

        definition = load_subagent_definition(
            Path(f"{agent_name}/{agent_name}_subagent.yaml"),
            agents_dir,
        )

        prompt = definition.initial_context.system_prompt
        checks = [
            ("<task_description>", "<task_description> tag"),
            ("Always respond with a tool call", "tool-call directive"),
        ]

        for pattern, name in checks:
            if pattern not in prompt:
                print(f"  {agent_name}: FAIL - Missing {name}")
                return False

        if len(definition.tools) < 2:
            print(f"  {agent_name}: FAIL - Need at least 2 tools (including submit_result)")
            return False

        tool_names = [tool.tool_name for tool in definition.tools]
        if "submit_result" not in tool_names:
            print(f"  {agent_name}: FAIL - Missing submit_result tool")
            return False

        print(
            f"  {agent_name}: PASS ({len(definition.tools)} tools, max_turns={definition.max_turns})"
        )
        return True

    except Exception as e:
        print(f"  {agent_name}: FAIL - {e}")
        return False


async def main() -> int:
    print("Validating production agents...\n")

    config = load_config(None)
    config.agents_dir = "agents"
    agents_dir = Path(config.agents_dir)

    agents = ["harness", "docstring", "lint", "test", "sample_data"]
    results = []

    for agent in agents:
        result = await validate_agent(agent, agents_dir)
        results.append(result)

    print()
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"All {total} agents validated successfully!")
        return 0

    print(f"Validation failed: {passed}/{total} agents passed")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
