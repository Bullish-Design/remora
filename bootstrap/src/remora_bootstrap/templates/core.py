"""Core bootstrap prompt templates."""

from __future__ import annotations

from remora_bootstrap.contracts import BootstrapTemplate


def default_templates() -> list[BootstrapTemplate]:
    return [
        BootstrapTemplate(
            name="phase2_system",
            description="System guidance for Phase 2 bootstrap agents",
            body=(
                "You are operating in Remora Phase 2 bootstrap mode. "
                "Use only bootstrap-native tools/templates and Remora library APIs."
            ),
        ),
        BootstrapTemplate(
            name="task_intake",
            description="Task intake prompt for bootstrap planning",
            body=(
                "Objective: {objective}\n"
                "Constraints: {constraints}\n"
                "Return: concise plan with risks and first implementation step."
            ),
        ),
    ]
