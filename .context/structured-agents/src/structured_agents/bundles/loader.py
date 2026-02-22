from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

import yaml
from jinja2 import Environment, StrictUndefined

from structured_agents.backends.protocol import ToolBackend
from structured_agents.bundles.schema import (
    BundleManifest,
    RegistrySettings,
    ToolReference,
)
from structured_agents.exceptions import BundleError
from structured_agents.grammar.config import GrammarConfig
from structured_agents.plugins import ModelPlugin, get_plugin
from structured_agents.registries import (
    CompositeRegistry,
    GrailRegistry,
    GrailRegistryConfig,
    PythonRegistry,
    ToolRegistry,
)
from structured_agents.tool_sources import RegistryBackendToolSource, ToolSource
from structured_agents.types import Message, ToolSchema


class AgentBundle:
    """A loaded agent bundle with tools, prompts, and configuration."""

    def __init__(self, path: Path, manifest: BundleManifest) -> None:
        self.path = path
        self.manifest = manifest
        self._tool_schemas: list[ToolSchema] | None = None
        env = Environment(undefined=StrictUndefined)
        self._system_template = env.from_string(manifest.initial_context.system_prompt)
        self._user_template = env.from_string(manifest.initial_context.user_template)
        self._registries = self._build_registries()
        self._tool_registry = CompositeRegistry(list(self._registries.values()))

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def max_turns(self) -> int:
        return self.manifest.max_turns

    @property
    def termination_tool(self) -> str:
        return self.manifest.termination_tool

    def get_plugin(self, override_name: str | None = None) -> ModelPlugin:
        """Get the appropriate model plugin for this bundle.

        Args:
            override_name: Optional plugin name to use instead of the manifest.
        """
        plugin_name = override_name or self.manifest.model.plugin
        return get_plugin(plugin_name)

    def get_grammar_config(self) -> GrammarConfig:
        """Build GrammarConfig from bundle settings."""
        grammar = self.manifest.model.grammar
        return GrammarConfig(
            mode=cast(
                Literal["ebnf", "structural_tag", "json_schema"],
                grammar.mode,
            ),
            allow_parallel_calls=grammar.allow_parallel_calls,
            args_format=cast(
                Literal["permissive", "escaped_strings", "json"],
                grammar.args_format,
            ),
        )

    @property
    def tool_schemas(self) -> list[ToolSchema]:
        """Get tool schemas for this bundle."""
        if self._tool_schemas is None:
            self._tool_schemas = self._build_tool_schemas()
        return self._tool_schemas

    def build_tool_source(self, backend: ToolBackend) -> ToolSource:
        """Build a ToolSource from bundle registries and a backend."""
        return RegistryBackendToolSource(self._tool_registry, backend)

    def _build_registries(self) -> dict[str, ToolRegistry]:
        registries: dict[str, ToolRegistry] = {}

        for registry_settings in self.manifest.registries:
            registry = self._build_registry(registry_settings)
            registries[registry_settings.type.lower()] = registry

        return registries

    def _build_registry(self, settings: RegistrySettings) -> ToolRegistry:
        registry_type = settings.type.lower()
        config = dict(settings.config)

        if registry_type == "grail":
            agents_dir_value = config.pop("agents_dir", None)
            if agents_dir_value:
                agents_dir = Path(agents_dir_value)
                if not agents_dir.is_absolute():
                    agents_dir = self.path / agents_dir
            else:
                agents_dir = self.path / "tools"
                if not agents_dir.exists():
                    agents_dir = Path.cwd() / "agents"

            grail_config = GrailRegistryConfig(agents_dir=agents_dir, **config)
            return GrailRegistry(grail_config)

        if registry_type == "python":
            return PythonRegistry()

        raise BundleError(f"Unknown registry: {settings.type}")

    def _build_tool_schemas(self) -> list[ToolSchema]:
        schemas: list[ToolSchema] = []

        for tool_ref in self.manifest.tools:
            schema = self._resolve_tool(tool_ref)
            schemas.append(schema)

        return schemas

    def _resolve_tool(self, tool_ref: ToolReference) -> ToolSchema:
        registry_name = tool_ref.registry.lower()
        registry = self._registries.get(registry_name)

        if not registry:
            raise BundleError(f"Registry not configured: {tool_ref.registry}")

        schema = registry.resolve(tool_ref.name)
        if not schema:
            raise BundleError(f"Tool not found: {tool_ref.name}")

        description = (
            tool_ref.description
            if tool_ref.description is not None
            else schema.description
        )
        parameters = (
            tool_ref.inputs_override
            if tool_ref.inputs_override is not None
            else schema.parameters
        )

        if tool_ref.context_providers:
            context_providers = tuple(
                self.path / cp for cp in tool_ref.context_providers
            )
        else:
            context_providers = schema.context_providers

        return ToolSchema(
            name=schema.name,
            description=description,
            parameters=parameters,
            backend=schema.backend,
            script_path=schema.script_path,
            context_providers=context_providers,
        )

    def build_initial_messages(
        self,
        context: dict[str, Any] | None = None,
    ) -> list[Message]:
        """Build initial messages from templates.

        Args:
            context: Variables to render in templates.
                     Common variables: node_text, input, etc.
        """
        context = context or {}

        system_prompt = self._system_template.render(**context)
        user_message = self._user_template.render(**context)

        return [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_message),
        ]

    def get_system_prompt(self, context: dict[str, Any] | None = None) -> str:
        """Render the system prompt with context."""
        context = context or {}
        return self._system_template.render(**context)


def load_bundle(directory: str | Path) -> AgentBundle:
    """Load an agent bundle from a directory.

    Args:
        directory: Path to bundle directory containing bundle.yaml

    Returns:
        Loaded AgentBundle

    Raises:
        BundleError: If bundle is invalid or cannot be loaded
    """
    path = Path(directory)

    if not path.is_dir():
        raise BundleError(f"Bundle path is not a directory: {path}")

    manifest_path = path / "bundle.yaml"
    if not manifest_path.exists():
        manifest_path = path / "bundle.yml"
        if not manifest_path.exists():
            raise BundleError(f"Bundle manifest not found in {path}")

    try:
        with manifest_path.open("r", encoding="utf-8") as file_handle:
            data = yaml.safe_load(file_handle)
    except Exception as exc:
        raise BundleError(f"Failed to read bundle manifest: {exc}") from exc

    try:
        manifest = BundleManifest(**data)
    except Exception as exc:
        raise BundleError(f"Invalid bundle manifest: {exc}") from exc

    return AgentBundle(path, manifest)
