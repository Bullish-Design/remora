"""Core bootstrap agent definitions."""

from __future__ import annotations

from remora_bootstrap.contracts import BootstrapAgent


def default_agents() -> list[BootstrapAgent]:
    return [
        BootstrapAgent(
            name="bootstrap_orchestrator",
            description="Coordinates bootstrap workflows and task decomposition",
            node_types=("file", "function", "class", "method"),
            allowed_tools=("echo", "plan_stub"),
        ),
        BootstrapAgent(
            name="bootstrap_editor",
            description="Focuses on implementation and patch synthesis",
            node_types=("file", "function", "class", "method"),
            allowed_tools=("echo",),
        ),
    ]
