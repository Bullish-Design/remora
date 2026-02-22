"""Main analyzer interface for Remora."""

from __future__ import annotations

import asyncio
import inspect
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.table import Table

from cairn.runtime.workspace_manager import WorkspaceManager
from remora.config import RemoraConfig
from remora.discovery import CSTNode, TreeSitterDiscoverer
from remora.events import EventEmitter, EventName, EventStatus, JsonlEventEmitter, NullEventEmitter
from remora.orchestrator import Coordinator
from remora.results import AgentResult, AgentStatus, AnalysisResults, NodeResult
from remora.workspace_bridge import CairnWorkspaceBridge


class WorkspaceState(Enum):
    """State of a workspace for a node/operation pair."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RETRYING = "retrying"


@dataclass
class WorkspaceInfo:
    """Information about a workspace."""

    workspace_id: str
    node_id: str
    operation: str
    state: WorkspaceState = WorkspaceState.PENDING
    result: AgentResult | None = None


class RemoraAnalyzer:
    """Main interface for programmatic analysis."""

    def __init__(
        self,
        config: RemoraConfig,
        event_emitter: EventEmitter | None = None,
        workspace_manager: WorkspaceManager | None = None,
        discoverer_factory: Callable[..., TreeSitterDiscoverer] | None = None,
        coordinator_cls: type[Coordinator] = Coordinator,
    ):
        """Initialize analyzer.

        Args:
            config: Remora configuration
            event_emitter: Optional event emitter for progress tracking
        """
        self.config = config

        self._event_emitter = event_emitter or NullEventEmitter()
        self._results: AnalysisResults | None = None
        self._nodes: list[CSTNode] = []
        self._workspaces: dict[tuple[str, str], WorkspaceInfo] = {}
        self._workspace_manager = workspace_manager or WorkspaceManager()
        self._discoverer_factory = discoverer_factory or TreeSitterDiscoverer
        self._coordinator_cls = coordinator_cls
        
        cache_root = self.config.cairn.home or (Path.home() / ".cache" / "remora")
        self._bridge = CairnWorkspaceBridge(
            workspace_manager=self._workspace_manager,
            project_root=self.config.agents_dir.parent.resolve(),
            cache_root=cache_root
        )

    async def analyze(
        self,
        paths: list[Path],
        operations: list[str] | None = None,
    ) -> AnalysisResults:
        """Run analysis on all nodes.

        Args:
            paths: Paths to analyze (files or directories)
            operations: List of operations to run (defaults to all enabled)

        Returns:
            AnalysisResults containing results for all nodes
        """
        # Determine which operations to run
        if operations is None:
            operations = [name for name, op_config in self.config.operations.items() if op_config.enabled]

        # Discover nodes using tree-sitter
        discoverer = self._discoverer_factory(
            root_dirs=paths,
            language=self.config.discovery.language,
            query_pack=self.config.discovery.query_pack,
            query_dir=self.config.discovery.query_dir,
            event_emitter=self._event_emitter,
        )
        self._nodes = await asyncio.to_thread(discoverer.discover)

        # Run analysis through coordinator
        async with self._coordinator_cls(
            config=self.config,
            event_stream_enabled=self.config.event_stream.enabled,
            event_stream_output=self.config.event_stream.output,
        ) as coordinator:
            node_results: list[NodeResult] = []
            for node in self._nodes:
                node_result = await coordinator.process_node(node, operations)
                node_results.append(node_result)

                # Track workspaces
                for op_name, op_result in node_result.operations.items():
                    workspace_id = op_result.workspace_id or f"{op_name}-{node.node_id}"
                    self._workspaces[(node.node_id, op_name)] = WorkspaceInfo(
                        workspace_id=workspace_id,
                        node_id=node.node_id,
                        operation=op_name,
                        state=WorkspaceState.PENDING,
                        result=op_result,
                    )

        self._results = AnalysisResults.from_node_results(node_results)
        return self._results

    def get_results(self) -> AnalysisResults | None:
        """Get cached results from last analysis."""
        return self._results

    def _get_workspace_id(self, node_id: str, operation: str) -> str:
        """Get workspace ID for a node/operation pair."""
        key = (node_id, operation)
        if key in self._workspaces:
            return self._workspaces[key].workspace_id
        return f"{operation}-{node_id}"

    def _get_node(self, node_id: str) -> CSTNode:
        """Get node by ID."""
        for node in self._nodes:
            if node.node_id == node_id:
                return node
        raise ValueError(f"Node not found: {node_id}")

    async def accept(self, node_id: str | None = None, operation: str | None = None) -> None:
        """Accept changes and merge workspace into stable.

        Args:
            node_id: Specific node to accept (None = all pending nodes)
            operation: Specific operation to accept (None = all operations)
        """
        targets = self._filter_workspaces(node_id, operation, WorkspaceState.PENDING)

        for key, info in targets:
            # Call bridge to merge workspace
            await self._bridge.merge(info.workspace_id)
            info.state = WorkspaceState.ACCEPTED
            self._event_emitter.emit(
                {
                    "event": EventName.WORKSPACE_ACCEPTED,
                    "workspace_id": info.workspace_id,
                    "node_id": info.node_id,
                    "operation": info.operation,
                    "status": EventStatus.OK,
                }
            )

    async def reject(self, node_id: str | None = None, operation: str | None = None) -> None:
        """Reject changes and discard workspace.

        Args:
            node_id: Specific node to reject (None = all pending nodes)
            operation: Specific operation to reject (None = all operations)
        """
        targets = self._filter_workspaces(node_id, operation, WorkspaceState.PENDING)

        for key, info in targets:
            # Call bridge to discard workspace
            await self._bridge.discard(info.workspace_id)
            info.state = WorkspaceState.REJECTED
            self._event_emitter.emit(
                {
                    "event": EventName.WORKSPACE_REJECTED,
                    "workspace_id": info.workspace_id,
                    "node_id": info.node_id,
                    "operation": info.operation,
                    "status": EventStatus.OK,
                }
            )

    async def retry(
        self,
        node_id: str,
        operation: str,
        config_override: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Retry a failed/rejected operation with optional config override.

        Args:
            node_id: Node to retry
            operation: Operation to retry
            config_override: Optional config overrides for this retry

        Returns:
            New AgentResult for the retry attempt
        """
        key = (node_id, operation)
        if key not in self._workspaces:
            raise ValueError(f"No workspace found for {node_id}/{operation}")

        info = self._workspaces[key]

        # Discard existing workspace
        if info.state != WorkspaceState.REJECTED:
            await self.reject(node_id, operation)

        info.state = WorkspaceState.RETRYING

        # Get the node
        node = self._get_node(node_id)

        # Build overridden config
        config = self.config
        if config_override:
            config = self._apply_config_override(config_override)

        # Re-run the operation
        async with self._coordinator_cls(
            config=config,
            event_stream_enabled=config.event_stream.enabled,
            event_stream_output=config.event_stream.output,
        ) as coordinator:
            node_result = await coordinator.process_node(node, [operation])

        # Update workspace info
        if operation in node_result.operations:
            new_result = node_result.operations[operation]
            info.result = new_result
            info.state = WorkspaceState.PENDING

            # Update results
            if self._results:
                for i, nr in enumerate(self._results.nodes):
                    if nr.node_id == node_id:
                        self._results.nodes[i].operations[operation] = new_result

            return new_result

        raise RuntimeError(f"Operation {operation} did not produce a result")

    async def bulk_accept(
        self,
        node_id: str | None = None,
        operations: list[str] | None = None,
    ) -> None:
        """Accept all pending workspaces matching filters.

        Args:
            node_id: Filter by specific node (None = all nodes)
            operations: Filter by specific operations (None = all operations)
        """
        await self.accept(node_id, operations[0] if operations and len(operations) == 1 else None)

    async def bulk_reject(
        self,
        node_id: str | None = None,
        operations: list[str] | None = None,
    ) -> None:
        """Reject all pending workspaces matching filters.

        Args:
            node_id: Filter by specific node (None = all nodes)
            operations: Filter by specific operations (None = all operations)
        """
        await self.reject(node_id, operations[0] if operations and len(operations) == 1 else None)

    def _filter_workspaces(
        self,
        node_id: str | None,
        operation: str | None,
        state: WorkspaceState | None,
    ) -> list[tuple[tuple[str, str], WorkspaceInfo]]:
        """Filter workspaces by criteria."""
        results: list[tuple[tuple[str, str], WorkspaceInfo]] = []
        for key, info in self._workspaces.items():
            if node_id is not None and info.node_id != node_id:
                continue
            if operation is not None and info.operation != operation:
                continue
            if state is not None and info.state != state:
                continue
            results.append((key, info))
        return results

    def _apply_config_override(self, overrides: dict[str, Any]) -> RemoraConfig:
        """Apply config overrides and return new config."""
        # Serialize current config
        data = self.config.model_dump(mode="json")
        # Apply overrides
        for key, value in overrides.items():
            if "." in key:
                parts = key.split(".")
                target = data
                for part in parts[:-1]:
                    if part not in target:
                        target[part] = {}
                    target = target[part]
                target[parts[-1]] = value
            else:
                data[key] = value
        # Return new config
        return RemoraConfig.model_validate(data)


