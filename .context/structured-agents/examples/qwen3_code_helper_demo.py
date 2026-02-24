#!/usr/bin/env python3
"""Demo script for Qwen3 with code analysis.

This demo uses the Qwen plugin to summarize random files from the src/ directory.
It sends requests concurrently to test vLLM batched inference.

Run with: python examples/qwen3_code_helper_demo.py --files 10
"""

import argparse
import asyncio
import random
from pathlib import Path
from typing import Any

from structured_agents import KernelConfig, Message, QwenPlugin
from structured_agents.client.factory import build_client
from structured_agents.tool_sources.protocol import ToolSource


class NoOpToolSource(ToolSource):
    """A tool source that does nothing - for text-only demos."""

    async def execute(
        self, tool_call: Any, tool_schema: Any, context: dict[str, Any]
    ) -> Any:
        raise NotImplementedError("No tools available")

    def list_tools(self) -> list[str]:
        return []

    def resolve(self, tool_name: str) -> Any:
        return None

    def resolve_all(self, tool_names: list[str]) -> list[Any]:
        return []

    def context_providers(self) -> list[Any]:
        return []


def get_random_files(num_files: int) -> list[tuple[Path, str]]:
    """Get random Python files from src/ directory."""
    src_dir = Path(__file__).parent.parent / "src"

    py_files = list(src_dir.rglob("*.py"))

    selected = random.sample(py_files, min(num_files, len(py_files)))

    files_with_content = []
    for f in selected:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            if len(content) > 100:
                files_with_content.append((f.relative_to(src_dir), content[:3000]))
        except Exception:
            pass

    return files_with_content[:num_files]


async def summarize_file(
    client: Any,
    plugin: QwenPlugin,
    file_path: Path,
    code: str,
) -> tuple[Path, str]:
    """Summarize a single file."""
    user_content = f"Summarize this code in 2-3 sentences:\n\n```{code}```"

    messages = [
        Message(
            role="developer",
            content="You are a code analysis assistant. Provide brief summaries.",
        ),
        Message(role="user", content=user_content),
    ]

    formatted = plugin.format_messages(messages, [])

    response = await client.chat_completion(
        messages=formatted,
        tools=None,
        tool_choice="none",
    )

    return (file_path, response.content or "")


async def run_demo(
    base_url: str,
    model: str,
    num_files: int,
) -> None:
    """Run the demo with concurrent file summaries."""
    print(f"Getting {num_files} random files from src/...")
    files = get_random_files(num_files)
    print(f"Selected {len(files)} files:")
    for f, _ in files:
        print(f"  - {f}")

    config = KernelConfig(
        base_url=base_url,
        model=model,
        temperature=0.1,
        max_tokens=256,
        tool_choice="none",
    )

    plugin = QwenPlugin()
    client = build_client(config)

    print(f"\nSending {len(files)} concurrent requests...")

    tasks = [
        summarize_file(client, plugin, file_path, code) for file_path, code in files
    ]

    results = await asyncio.gather(*tasks)

    print("\n=== Results ===")
    for file_path, summary in results:
        print(f"\n--- {file_path} ---")
        print(summary[:300] + "..." if len(summary) > 300 else summary)

    await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen3 code analysis demo")
    parser.add_argument(
        "--url",
        default="http://remora-server:8000/v1",
        help="vLLM server URL",
    )
    parser.add_argument(
        "--model",
        default="Qwen/Qwen3-4B-Instruct-2507-FP8",
        help="Model name",
    )
    parser.add_argument(
        "--files",
        type=int,
        default=10,
        help="Number of files to summarize",
    )
    args = parser.parse_args()

    asyncio.run(run_demo(args.url, args.model, args.files))


if __name__ == "__main__":
    main()
