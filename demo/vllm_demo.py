#!/usr/bin/env python3
"""vllm_demo.py - Demo that actually calls vLLM and writes results to workspace."""

import asyncio
import json
from pathlib import Path

from structured_agents import (
    AgentKernel,
    KernelConfig,
    Message,
    QwenPlugin,
    GrailBackend,
    GrailBackendConfig,
    PythonBackend,
)
from structured_agents.grammar.config import GrammarConfig


VLLM_URL = "http://localhost:8000/v1"
MODEL = "Qwen/Qwen3-4B-Instruct-2507-FP8"


async def main():
    print("=" * 60)
    print("🔧 REMORA vLLM INTEGRATION DEMO")
    print("=" * 60)

    # Setup
    workspace_dir = Path("demo_workspaces/vllm_demo")
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Create kernel config for vLLM
    config = KernelConfig(
        base_url=VLLM_URL,
        model=MODEL,
        temperature=0.1,
        max_tokens=512,
    )

    # Use Python backend (simpler, no grail tools needed)
    backend = PythonBackend()

    # Qwen plugin with grammar
    plugin = QwenPlugin()
    grammar_config = GrammarConfig(
        mode="ebnf",
        allow_parallel_calls=False,
    )

    # Create kernel
    kernel = AgentKernel(
        config=config,
        plugin=plugin,
        tool_source=backend,
        grammar_config=grammar_config,
    )

    # Target code to analyze
    target_code = """
def calculate_sum(a, b):
    result = a + b
    return result
"""

    # Build messages
    messages = [
        Message(role="system", content="You are a code analysis assistant. Provide brief summaries."),
        Message(role="user", content=f"Summarize this Python function in one sentence:\n{target_code}"),
    ]

    print(f"\n📤 Sending request to vLLM at {VLLM_URL}")
    print(f"   Model: {MODEL}")
    print(f"   Target code:\n{target_code}")

    # Run the kernel
    result = await kernel.run(
        initial_messages=messages,
        tools=[],  # No tools, just text completion
        max_turns=1,
    )

    summary = result.final_message.content
    print(f"\n📥 Received response from vLLM:")
    print(f"   {summary[:200]}...")

    # Write result to workspace
    output_file = workspace_dir / "analysis_result.txt"
    output_file.write_text(f"""# Code Analysis Result

## Original Code:
{target_code}

## Summary:
{summary}

## Metadata:
- Model: {MODEL}
- vLLM URL: {VLLM_URL}
- Tokens used: {result.usage.total_tokens if result.usage else "N/A"}
""")

    print(f"\n💾 Wrote result to workspace: {output_file}")

    # Also write as JSON for programmatic access
    json_file = workspace_dir / "analysis_result.json"
    json_file.write_text(
        json.dumps(
            {
                "original_code": target_code,
                "summary": summary,
                "model": MODEL,
                "tokens_used": result.usage.total_tokens if result.usage else None,
            },
            indent=2,
        )
    )

    print(f"   Wrote JSON to: {json_file}")

    await kernel.close()

    print("\n" + "=" * 60)
    print("✅ vLLM DEMO COMPLETE")
    print("=" * 60)

    # Read back and print
    print(f"\n📄 Contents of {output_file}:")
    print("-" * 40)
    print(output_file.read_text())


if __name__ == "__main__":
    asyncio.run(main())
