"""Validate all production agents after refactoring."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from remora.backend import BackendDependencyMissing, require_backend_extra
from remora.config import load_config

try:
    _structured_agents = require_backend_extra()
except BackendDependencyMissing as exc:
    print(exc)
    raise SystemExit(1)

load_bundle = _structured_agents.load_bundle


async def validate_agent(agent_name: str, agents_dir: Path) -> bool:
    """Validate an agent loads correctly and has proper configuration."""
    try:
        bundle_path = agents_dir / agent_name
        yaml_path = bundle_path / "bundle.yaml"
        if not yaml_path.exists():
            print(f"  {agent_name}: SKIP (no bundle.yaml)")
            return True

        bundle = load_bundle(bundle_path)

        prompt = bundle.manifest.initial_context.system_prompt
        checks = [
            ("<task_description>", "<task_description> tag"),
            ("Always respond with a tool call", "tool-call directive"),
        ]

        for pattern, name in checks:
            if pattern not in prompt:
                print(f"  {agent_name}: FAIL - Missing {name}")
                return False

        if len(bundle.manifest.tools) < 2:
            print(f"  {agent_name}: FAIL - Need at least 2 tools (including submit_result)")
            return False

        tool_names = [tool.name for tool in bundle.manifest.tools]
        if "submit_result" not in tool_names:
            print(f"  {agent_name}: FAIL - Missing submit_result tool")
            return False

        print(f"  {agent_name}: PASS ({len(bundle.manifest.tools)} tools, max_turns={bundle.max_turns})")
        return True

    except Exception as e:
        print(f"  {agent_name}: FAIL - {e}")
        return False


async def main() -> int:
    print("Validating production agents...\n")

    config = load_config(None)
    config.agents_dir = Path("agents")
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
