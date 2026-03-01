#!/usr/bin/env python3
"""Demo script that uses structured-agents to call vLLM and write results to workspace."""

import asyncio
import json
from pathlib import Path
import uuid

from structured_agents import (
    AgentKernel,
    KernelConfig,
    Message,
    QwenPlugin,
    GrailBackend,
    GrailBackendConfig,
    RegistryBackendToolSource,
)
from structured_agents.registries import GrailRegistry, GrailRegistryConfig
from structured_agents.grammar.config import GrammarConfig


async def main():
    # Configuration for vLLM
    config = KernelConfig(
        base_url="http://remora-server:8000/v1",
        model="Qwen/Qwen3-4B-Instruct-2507-FP8",
        temperature=0.1,
        max_tokens=512,
        tool_choice="auto",
    )

    # Create a workspace for this run
    run_id = uuid.uuid4().hex[:8]
    workspace_path = Path(f"demo_workspaces/{run_id}")
    workspace_path.mkdir(parents=True, exist_ok=True)

    print(f"🚀 Running agent in workspace: {workspace_path}")

    # Setup Grail backend and registry
    agents_dir = Path(__file__).parent / "agents" / "simple_analyzer" / "tools"

    registry = GrailRegistry(GrailRegistryConfig(agents_dir=agents_dir))
    backend = GrailBackend(GrailBackendConfig(grail_dir=agents_dir))
    tool_source = RegistryBackendToolSource(registry, backend)

    # Create kernel with Qwen plugin and grammar config
    plugin = QwenPlugin()
    grammar_config = GrammarConfig(
        mode="ebnf",
        allow_parallel_calls=False,
    )

    kernel = AgentKernel(
        config=config,
        plugin=plugin,
        tool_source=tool_source,
        grammar_config=grammar_config,
    )

    # The code to analyze
    code_to_analyze = """
def calculate_sum(a, b):
    result = a + b
    return result
"""

    # Build initial messages
    messages = [
        Message(
            role="system",
            content="""You are a code analyzer. Your ONLY task is to call the write_result tool with your analysis.

When you have completed your analysis, you MUST call write_result with:
- analysis: your brief summary of the code

That's the ONLY tool you should call. Nothing else.""",
        ),
        Message(
            role="user",
            content=f"""Analyze this code and call write_result with your analysis:

{code_to_analyze}

Remember: ONLY call write_result with the 'analysis' parameter.""",
        ),
    ]

    # Run the kernel
    print("📡 Calling vLLM...")

    # Context provider to pass workspace path to tools
    async def provide_context():
        return {
            "workspace_path": str(workspace_path),
        }

    result = await kernel.run(
        messages,
        tools=["write_result"],
        max_turns=10,
        context_provider=provide_context,
    )

    print(f"✅ Agent completed!")
    print(f"   Termination reason: {result.termination_reason}")
    print(f"   Turns: {result.turn_count}")

    # Extract the analysis from the tool result in history
    analysis_result = None
    for msg in result.history:
        if msg.role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                print(f"   Tool call: {tc.name} -> {tc.arguments}")
        if msg.role == "tool":
            try:
                import json

                if msg.content:
                    tool_output = json.loads(msg.content)
                    if "analysis" in tool_output:
                        analysis_result = tool_output["analysis"]
                        break
            except:
                pass

    if analysis_result:
        print(f"\n📝 Analysis result:\n{analysis_result}")

        # Write to local file
        output_file = Path("demo_output.txt")
        output_file.write_text(analysis_result)
        print(f"\n💾 Written to: {output_file}")
    else:
        print(f"⚠️ No analysis found in results")
        print(f"   Final message: {result.final_message.content}")

    await kernel.close()


if __name__ == "__main__":
    asyncio.run(main())
