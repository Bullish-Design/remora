"""Bootstrap turn executor.

Parallel to v1's execute_agent_turn(). Uses schema.yaml instead of manifest.yaml.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from structured_agents import Message, build_client

from remora.bootstrap.schema_loader import TurnSchema, load_schema, resolve_context_vars
from remora.core.agents.cairn_externals import CairnExternals
from remora.core.agents.kernel_factory import create_kernel, extract_response_text

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    response_text: str
    context_values: dict[str, str] = field(default_factory=dict)


class TurnExecutor:
    def __init__(
        self,
        *,
        agent_id: str,
        cairn_externals: CairnExternals,
        tools: list[Any],
        node_attrs: dict[str, Any],
        config: Any,
        system_agents_dir: Path | None = None,
        client: Any | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._cairn_externals = cairn_externals
        self._tools = tools
        self._node_attrs = node_attrs
        self._config = config
        self._system_agents_dir = system_agents_dir
        self._client = client

    async def run(self, activation_event: Any = None) -> TurnResult:
        schema = await load_schema(
            self._cairn_externals,
            system_agents_dir=self._system_agents_dir,
        )

        context_values = await self._run_context_pipeline(schema)
        system_prompt = resolve_context_vars(
            self.resolve_node_vars(schema.system),
            context_values,
        )
        user_prompt = self._build_user_prompt(activation_event)

        tool_map = {tool.schema.name: tool for tool in self._tools}
        active_tools = [tool_map[name] for name in schema.tools if name in tool_map]
        tool_schemas = [tool.schema for tool in active_tools]

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        if self._client is None:
            self._client = build_client(
                {
                    "base_url": self._config.model_base_url,
                    "api_key": self._config.model_api_key or "EMPTY",
                    "model": self._config.model_default,
                    "timeout": self._config.timeout_s,
                }
            )

        kernel = create_kernel(
            model_name=self._config.model_default,
            base_url=self._config.model_base_url,
            api_key=self._config.model_api_key or "EMPTY",
            timeout=self._config.timeout_s,
            tools=active_tools,
            # Bootstrap turns are intentionally unobserved. We only persist the
            # surrounding bootstrap events, not per-tool/model trace events.
            observer=None,
            client=self._client,
        )

        try:
            result = await kernel.run(messages, tool_schemas, max_turns=schema.max_turns)
        finally:
            await kernel.close()

        return TurnResult(
            response_text=extract_response_text(result),
            context_values=context_values,
        )

    async def _run_context_pipeline(self, schema: TurnSchema) -> dict[str, str]:
        values: dict[str, str] = {}
        tool_map = {tool.schema.name: tool for tool in self._tools}

        for step in schema.context:
            tool = tool_map.get(step.tool)
            if tool is None:
                if not step.optional:
                    logger.warning("Context step %r: tool %r not found", step.name, step.tool)
                values[step.name] = ""
                continue

            resolved_args = {
                key: self.resolve_node_vars(str(value)) if isinstance(value, str) else value
                for key, value in step.args.items()
            }

            try:
                result = await tool.execute(resolved_args, context=None)
                values[step.name] = result.output if not result.is_error else ""
            except Exception:
                if not step.optional:
                    logger.warning("Context step %r failed", step.name, exc_info=True)
                values[step.name] = ""

        return values

    def resolve_node_vars(self, text: str) -> str:
        """Resolve {node.attr} references from current node attrs."""

        def replacer(match: re.Match[str]) -> str:
            return str(self._node_attrs.get(match.group(1), match.group(0)))

        return re.sub(r"\{node\.([^}]+)\}", replacer, text)

    def _build_user_prompt(self, activation_event: Any) -> str:
        if activation_event is None:
            return "Begin your turn."

        event_type = getattr(activation_event, "event_type", type(activation_event).__name__)
        node_id = getattr(activation_event, "node_id", None)
        parts = [f"Activation event: {event_type}"]
        if node_id:
            parts.append(f"Node: {node_id}")
        return "\n".join(parts)

__all__ = ["TurnExecutor", "TurnResult"]
