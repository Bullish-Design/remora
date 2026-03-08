"""Bootstrap registry assembly."""

from __future__ import annotations

from remora_bootstrap.agents import default_agents
from remora_bootstrap.registry import BootstrapRegistry
from remora_bootstrap.templates import default_templates
from remora_bootstrap.tools import default_tools


def build_default_registry() -> BootstrapRegistry:
    registry = BootstrapRegistry()
    for tool in default_tools():
        registry.register_tool(tool)
    for agent in default_agents():
        registry.register_agent(agent)
    for template in default_templates():
        registry.register_template(template)
    return registry
