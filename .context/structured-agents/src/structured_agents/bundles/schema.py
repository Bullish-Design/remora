from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


def _default_registries() -> list["RegistrySettings"]:
    return [RegistrySettings(type="grail")]


class ToolReference(BaseModel):
    """Reference to a tool in a registry."""

    name: str
    registry: str = "grail"

    description: str | None = None
    inputs_override: dict[str, Any] | None = None
    context_providers: list[str] = Field(default_factory=list)


class RegistrySettings(BaseModel):
    """Registry configuration for bundle tool discovery."""

    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class GrammarSettings(BaseModel):
    """Grammar configuration for the bundle."""

    mode: str = "ebnf"
    allow_parallel_calls: bool = True
    args_format: str = "permissive"


class ModelSettings(BaseModel):
    """Model configuration in a bundle."""

    plugin: str = "function_gemma"
    adapter: str | None = None
    grammar: GrammarSettings = Field(default_factory=GrammarSettings)


class InitialContext(BaseModel):
    """Initial prompts for the agent."""

    system_prompt: str
    user_template: str = "{{ input }}"


class BundleManifest(BaseModel):
    """The bundle.yaml schema."""

    name: str
    version: str = "1.0"

    model: ModelSettings = Field(default_factory=ModelSettings)
    initial_context: InitialContext

    max_turns: int = 20
    termination_tool: str = "submit_result"

    tools: list[ToolReference]
    registries: list[RegistrySettings] = Field(default_factory=_default_registries)

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, tools: list[ToolReference]) -> list[ToolReference]:
        names = [tool.name for tool in tools]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate tool names in bundle")
        return tools
