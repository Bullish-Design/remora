#!/usr/bin/env python3
"""Migrate old subagent YAML files to new bundle.yaml format."""

from __future__ import annotations

from pathlib import Path

import yaml


def migrate_subagent(old_path: Path) -> dict:
    """Convert old subagent YAML to new bundle format."""
    with open(old_path, "r", encoding="utf-8") as handle:
        old = yaml.safe_load(handle)

    new = {
        "name": old.get("name", f"{old_path.parent.name}_agent"),
        "version": "1.0",
        "model": {
            "plugin": "function_gemma",
            "adapter": old.get("model_id", "google/functiongemma-270m-it"),
            "grammar": {
                "mode": "ebnf",
                "allow_parallel_calls": True,
                "args_format": "permissive",
            },
        },
        "initial_context": {
            "system_prompt": old.get("initial_context", {}).get("system_prompt", ""),
            "user_template": old.get("initial_context", {}).get("node_context", "{{ node_text }}"),
        },
        "max_turns": old.get("max_turns", 20),
        "termination_tool": "submit_result",
        "tools": [],
        "registries": [
            {
                "type": "grail",
                "config": {
                    "agents_dir": "tools",
                },
            }
        ],
    }

    for tool in old.get("tools", []):
        new_tool = {
            "name": tool.get("tool_name"),
            "registry": "grail",
            "description": tool.get("tool_description", ""),
        }

        if "inputs_override" in tool:
            new_tool["inputs_override"] = {}
            for name, override in tool["inputs_override"].items():
                override_type = override.get("type")
                if override_type is None and name == "changed_files":
                    override_type = "array"
                new_tool["inputs_override"][name] = {
                    "type": override_type or "string",
                    "description": override.get("description", ""),
                }

        if "context_providers" in tool:
            new_tool["context_providers"] = [
                cp.replace(f"{old_path.parent.name}/", "") for cp in tool["context_providers"]
            ]

        new["tools"].append(new_tool)

    return new


def main() -> None:
    agents_dir = Path("agents")

    for subagent_file in agents_dir.glob("*/*_subagent.yaml"):
        print(f"Migrating: {subagent_file}")

        new_data = migrate_subagent(subagent_file)
        new_path = subagent_file.parent / "bundle.yaml"

        with open(new_path, "w", encoding="utf-8") as handle:
            yaml.dump(new_data, handle, default_flow_style=False, sort_keys=False)

        print(f"  -> Created: {new_path}")

        backup_path = subagent_file.with_suffix(".yaml.old")
        subagent_file.rename(backup_path)
        print(f"  -> Backed up: {backup_path}")


if __name__ == "__main__":
    main()
