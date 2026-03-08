"""Runtime facade for bootstrap functionality.

This runtime treats Remora as a regular Python dependency and does not
rely on repo-level bundle YAML or Grail scripts.
"""

from __future__ import annotations

from dataclasses import dataclass

from remora.core.config import Config, load_config

from remora_bootstrap.bootstrap import build_default_registry
from remora_bootstrap.registry import BootstrapRegistry


@dataclass(slots=True)
class BootstrapRuntime:
    config: Config
    registry: BootstrapRegistry

    @classmethod
    def create(cls) -> "BootstrapRuntime":
        return cls(config=load_config(), registry=build_default_registry())

    def render_template(self, template_name: str, values: dict[str, str]) -> str:
        template = self.registry.templates[template_name]
        return template.body.format(**values)

    def call_tool(self, tool_name: str, payload: dict) -> dict:
        tool = self.registry.tools[tool_name]
        return tool.handler(payload)
