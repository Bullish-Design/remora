"""Registry for bootstrap primitives."""

from __future__ import annotations

from dataclasses import dataclass, field

from remora_bootstrap.contracts import BootstrapAgent, BootstrapTemplate, BootstrapTool


@dataclass(slots=True)
class BootstrapRegistry:
    """Holds bootstrap-native tools, agents, and templates."""

    tools: dict[str, BootstrapTool] = field(default_factory=dict)
    agents: dict[str, BootstrapAgent] = field(default_factory=dict)
    templates: dict[str, BootstrapTemplate] = field(default_factory=dict)

    def register_tool(self, tool: BootstrapTool) -> None:
        self.tools[tool.name] = tool

    def register_agent(self, agent: BootstrapAgent) -> None:
        self.agents[agent.name] = agent

    def register_template(self, template: BootstrapTemplate) -> None:
        self.templates[template.name] = template

    def summary(self) -> dict[str, list[str]]:
        return {
            "tools": sorted(self.tools.keys()),
            "agents": sorted(self.agents.keys()),
            "templates": sorted(self.templates.keys()),
        }
