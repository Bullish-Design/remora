#!/usr/bin/env python3
"""setup_demo.py - Scaffolds the input environment for the Remora Demo."""

from pathlib import Path
import textwrap


def generate_file(path_str: str, content: str):
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(textwrap.dedent(content).strip() + "\n")
    print(f"✅ Created {path}")


def main():
    print("🚀 Scaffolding Remora Demo Environment...")

    generate_file(
        "demo_input/src/main.py",
        """
        import os
        import sys
        
        def calculate_sum(a, b):
            result = a + b
            return result
        """,
    )

    generate_file(
        "demo_input/src/utils/helpers.py",
        """
        def format_greeting(name: str) -> str:
            return f"Hello, {name}!"
        """,
    )

    generate_file(
        "demo_input/remora.yaml",
        """
        discovery:
          query_pack: remora_core
        server:
          base_url: http://localhost:8000/v1
          default_adapter: Qwen/Qwen3-4B-Instruct-2507-FP8
          default_plugin: function_gemma
        """,
    )

    Path("demo_workspaces").mkdir(exist_ok=True)
    print("\n🎉 Scaffolding complete. You are ready to start the server.")


if __name__ == "__main__":
    main()
