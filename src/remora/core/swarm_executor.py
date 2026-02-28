"""Swarm executor for reactive agent execution.

This module provides SwarmExecutor which runs single agent turns
in response to events from the EventStore trigger queue.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from structured_agents.agent import get_response_parser, load_manifest
from structured_agents.client import build_client
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.kernel import AgentKernel
from structured_agents.models.adapter import ModelAdapter
from structured_agents.types import Message

from remora.core.agent_state import AgentState
from remora.core.context import ContextBuilder
from remora.core.discovery import CSTNode
from remora.core.event_store import EventSourcedBus, EventStore
from remora.core.tools.grail import build_virtual_fs, discover_grail_tools
from remora.core.workspace import CairnDataProvider
from remora.core.cairn_bridge import CairnWorkspaceService
from remora.utils import PathLike, PathResolver, truncate

if TYPE_CHECKING:
    from remora.core.config import RemoraConfig, WorkspaceConfig
    from remora.core.event_bus import EventBus

logger = logging.getLogger(__name__)


class SwarmExecutor:
    """Executor for single agent turns in reactive swarm mode."""

    def __init__(
        self,
        config: "RemoraConfig",
        event_bus: "EventBus | None",
        event_store: EventStore,
        swarm_id: str,
        project_root: Path,
    ):
        self.config = config
        self._event_bus = event_bus
        self._event_store = event_store
        self._swarm_id = swarm_id
        self._project_root = project_root
        self._path_resolver = PathResolver(project_root)
        self._context_builder = ContextBuilder()
        if event_bus is not None:
            event_bus.subscribe_all(self._context_builder.handle)

        workspace_config = config.workspace
        self._workspace_service = CairnWorkspaceService(
            config=workspace_config,
            graph_id=swarm_id,
            project_root=project_root,
        )

    async def run_agent(self, state: AgentState, trigger_event: Any = None) -> str:
        """Run a single agent turn.

        Args:
            state: The agent state to run
            trigger_event: The event that triggered this agent (optional)

        Returns:
            The agent's response as a string
        """
        bundle_path = self._resolve_bundle_path(state)
        manifest = load_manifest(bundle_path)

        await self._workspace_service.initialize()
        workspace = await self._workspace_service.get_agent_workspace(state.agent_id)
        externals = self._workspace_service.get_externals(state.agent_id, workspace)

        data_provider = CairnDataProvider(workspace, self._path_resolver)
        node = _state_to_cst_node(state)
        files = await data_provider.load_files(node)

        prompt = self._build_prompt(
            state,
            node,
            files,
            trigger_event=trigger_event,
            requires_context=getattr(manifest, "requires_context", True),
        )

        async def files_provider() -> dict[str, str | bytes]:
            current_files = await data_provider.load_files(node)
            return dict(build_virtual_fs(current_files))

        tools = discover_grail_tools(
            manifest.agents_dir,
            externals=externals,
            files_provider=files_provider,
        )

        model_name = self._resolve_model_name(bundle_path, manifest)
        result = await self._run_kernel(manifest, prompt, tools, model_name=model_name)

        return truncate(str(result), max_len=self.config.execution.truncation_limit)

    def _resolve_bundle_path(self, state: AgentState) -> Path:
        bundle_root = Path(self.config.bundles.path)
        mapping = self.config.bundles.mapping
        if state.node_type not in mapping:
            logger.warning(f"No bundle mapping for node_type: {state.node_type}, using default")
            return bundle_root
        return bundle_root / mapping[state.node_type]

    def _resolve_model_name(self, bundle_path: Path, manifest: Any) -> str:
        path = bundle_path / "bundle.yaml" if bundle_path.is_dir() else bundle_path
        override = None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            model_data = data.get("model")
            if isinstance(model_data, dict):
                override = model_data.get("id") or model_data.get("name") or model_data.get("model")
        except Exception:
            override = None
        if override:
            return str(override)
        return self.config.model.default_model or getattr(manifest, "model", "")

    async def _run_kernel(self, manifest: Any, prompt: str, tools: list[Any], *, model_name: str) -> Any:
        parser = get_response_parser(manifest.model)
        pipeline = ConstraintPipeline(manifest.grammar_config) if manifest.grammar_config else None
        adapter = ModelAdapter(name=manifest.model, response_parser=parser, constraint_pipeline=pipeline)
        client = build_client(
            {
                "base_url": self.config.model.base_url,
                "api_key": self.config.model.api_key or "EMPTY",
                "model": model_name,
                "timeout": self.config.execution.timeout,
            }
        )
        event_sourced_bus = EventSourcedBus(self._event_bus, self._event_store, self._swarm_id)
        kernel = AgentKernel(client=client, adapter=adapter, tools=tools, observer=event_sourced_bus)
        try:
            messages = [
                Message(role="system", content=manifest.system_prompt),
                Message(role="user", content=prompt),
            ]
            tool_schemas = [tool.schema for tool in tools]
            if manifest.grammar_config and not manifest.grammar_config.send_tools_to_api:
                tool_schemas = []
            max_turns = getattr(manifest, "max_turns", None) or self.config.execution.max_turns
            return await kernel.run(messages, tool_schemas, max_turns=max_turns)
        finally:
            await kernel.close()

    def _build_prompt(
        self,
        state: AgentState,
        node: CSTNode,
        files: dict[str, Any],
        *,
        trigger_event: Any = None,
        requires_context: bool = True,
    ) -> str:
        sections: list[str] = []
        sections.append(f"# Target: {state.full_name or state.agent_id}")
        sections.append(f"File: {state.file_path}")
        if state.range:
            sections.append(f"Lines: {state.range[0]}-{state.range[1]}")
        code = files.get(self._path_resolver.to_workspace_path(state.file_path)) or files.get(state.file_path)
        if code is not None:
            sections.append("")
            sections.append("## Code")
            sections.append("```")
            sections.append(code.decode() if isinstance(code, bytes) else code)
            sections.append("```")
        if trigger_event is not None:
            sections.append("")
            sections.append("## Trigger Event")
            sections.append(f"Type: {type(trigger_event).__name__}")
            event_content = getattr(trigger_event, "content", str(trigger_event))
            if event_content:
                sections.append(f"Content: {event_content}")
        if requires_context:
            context = self._context_builder.build_context_for(node)
            if context:
                sections.append(context)
        return "\n".join(sections)


def _state_to_cst_node(state: AgentState) -> CSTNode:
    start_line = state.range[0] if state.range else 1
    end_line = state.range[1] if state.range else 1
    return CSTNode(
        node_id=state.agent_id,
        node_type=state.node_type,
        name=state.name or "",
        full_name=state.full_name or "",
        file_path=state.file_path,
        text="",
        start_line=start_line,
        end_line=end_line,
        start_byte=0,
        end_byte=0,
    )


__all__ = ["SwarmExecutor"]
