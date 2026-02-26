"""Agent - high-level entry point for structured-agents."""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field
import yaml

from structured_agents.client import build_client
from structured_agents.events.observer import NullObserver, Observer
from structured_agents.grammar.config import DecodingConstraint
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.kernel import AgentKernel
from structured_agents.models.adapter import ModelAdapter
from structured_agents.models.parsers import QwenResponseParser, ResponseParser
from structured_agents.tools.grail import discover_tools
from structured_agents.types import Message, RunResult


_ADAPTER_REGISTRY: dict[str, type[ResponseParser]] = {
    "qwen": QwenResponseParser,
    "function_gemma": QwenResponseParser,
}


def get_response_parser(model_name: str) -> ResponseParser:
    """Look up the response parser for a model family."""
    parser_cls = _ADAPTER_REGISTRY.get(model_name)
    if parser_cls is None:
        parser_cls = QwenResponseParser
    return parser_cls()


@dataclass
class AgentManifest:
    """Loaded bundle manifest."""

    name: str
    system_prompt: str
    agents_dir: Path
    limits: dict[str, Any] | None = None
    model: str = "qwen"
    grammar_config: DecodingConstraint | None = None
    max_turns: int = 20


def load_manifest(bundle_path: str | Path) -> AgentManifest:
    """Load a bundle manifest from a YAML file."""
    path = Path(bundle_path)
    if path.is_dir():
        path = path / "bundle.yaml"

    with open(path) as f:
        data = yaml.safe_load(f)

    bundle_dir = path.parent

    initial_context = data.get("initial_context", {})

    model_config = data.get("model", "qwen")
    if isinstance(model_config, dict):
        model_name = model_config.get("plugin", "qwen")
    else:
        model_name = model_config

    grammar_data = data.get("grammar", {})
    grammar_config = None
    if grammar_data:
        grammar_config = DecodingConstraint(
            strategy=grammar_data.get("strategy", "ebnf"),
            allow_parallel_calls=grammar_data.get("allow_parallel_calls", False),
            send_tools_to_api=grammar_data.get("send_tools_to_api", False),
        )

    return AgentManifest(
        name=data.get("name", "unnamed"),
        system_prompt=initial_context.get("system_prompt", ""),
        agents_dir=bundle_dir / data.get("agents_dir", "agents"),
        limits=data.get("limits"),
        model=model_name,
        grammar_config=grammar_config,
        max_turns=data.get("max_turns", 20),
    )


class Agent:
    """A ready-to-run agent. The top-level user-facing API."""

    def __init__(
        self,
        kernel: AgentKernel,
        manifest: AgentManifest,
        observer: Observer | None = None,
    ):
        self.kernel = kernel
        self.manifest = manifest
        self.observer = observer or NullObserver()

    @classmethod
    async def from_bundle(
        cls, path: str | Path, observer: Observer | None = None, **overrides
    ) -> "Agent":
        """Load a bundle and construct a fully wired agent."""
        manifest = load_manifest(path)

        for key, value in overrides.items():
            if hasattr(manifest, key):
                object.__setattr__(manifest, key, value)

        tools = discover_tools(str(manifest.agents_dir))

        parser = get_response_parser(manifest.model)

        pipeline = (
            ConstraintPipeline(manifest.grammar_config)
            if manifest.grammar_config
            else None
        )

        adapter = ModelAdapter(
            name=manifest.model,
            response_parser=parser,
            constraint_pipeline=pipeline,
        )

        base_url = os.environ.get(
            "STRUCTURED_AGENTS_BASE_URL", "http://localhost:8000/v1"
        )
        api_key = os.environ.get("STRUCTURED_AGENTS_API_KEY", "EMPTY")

        client = build_client(
            {
                "model": manifest.model,
                "base_url": base_url,
                "api_key": api_key,
            }
        )

        obs = observer or NullObserver()
        kernel = AgentKernel(
            client=client,
            adapter=adapter,
            tools=tools,  # type: ignore[arg-type]
            observer=obs,
        )

        return cls(kernel, manifest, observer=obs)

    async def run(self, user_input: str, **kwargs) -> RunResult:
        """Run the agent with a user message."""
        messages = [
            Message(role="system", content=self.manifest.system_prompt),
            Message(role="user", content=user_input),
        ]

        tool_schemas = [t.schema for t in self.kernel.tools]

        return await self.kernel.run(
            messages,
            tool_schemas,
            max_turns=kwargs.get("max_turns", self.manifest.max_turns),
        )

    async def close(self) -> None:
        await self.kernel.close()
