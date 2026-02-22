"""Main analyzer interface for Remora."""

from __future__ import annotations

import asyncio
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
                    workspace_id = f"{op_name}-{node.node_id}"
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
            # Call Cairn CLI to merge workspace
            await self._cairn_merge(info.workspace_id)
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
            # Call Cairn CLI to discard workspace
            await self._cairn_discard(info.workspace_id)
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

    def _workspace_db_path(self, workspace_id: str) -> Path:
        cache_root = self.config.cairn.home or (Path.home() / ".cache" / "remora")
        return cache_root / "workspaces" / workspace_id / "workspace.db"

    def _workspace_root(self, workspace_id: str) -> Path:
        return self._workspace_db_path(workspace_id).parent

    def _project_root(self) -> Path:
        return self.config.agents_dir.parent.resolve()

    @staticmethod
    def _write_workspace_file(target_path: Path, content: bytes | str) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target_path.write_bytes(content)
        else:
            target_path.write_text(content, encoding="utf-8")

    @staticmethod
    def _remove_workspace_dir(workspace_root: Path) -> None:
        if workspace_root.exists():
            shutil.rmtree(workspace_root)

    async def _cairn_merge(self, workspace_id: str) -> None:
        """Merge a workspace into stable."""
        workspace_db = self._workspace_db_path(workspace_id)
        if not workspace_db.exists():
            raise FileNotFoundError(f"Workspace database not found: {workspace_db}")

        project_root = self._project_root()
        async with self._workspace_manager.open_workspace(workspace_db) as workspace:
            changed_paths = await workspace.overlay.list_changes("/")
            for overlay_path in changed_paths:
                relative_path = overlay_path.lstrip("/")
                target_path = (project_root / relative_path).resolve()
                if project_root not in target_path.parents and target_path != project_root:
                    raise ValueError(f"Refusing to write outside project root: {target_path}")
                content = await workspace.files.read(overlay_path, mode="binary", encoding=None)
                await asyncio.to_thread(self._write_workspace_file, target_path, content)

            await workspace.overlay.reset()

        await asyncio.to_thread(self._remove_workspace_dir, self._workspace_root(workspace_id))

    async def _cairn_discard(self, workspace_id: str) -> None:
        """Discard a workspace."""
        workspace_db = self._workspace_db_path(workspace_id)
        if not workspace_db.exists():
            raise FileNotFoundError(f"Workspace database not found: {workspace_db}")

        async with self._workspace_manager.open_workspace(workspace_db) as workspace:
            await workspace.overlay.reset()

        await asyncio.to_thread(self._remove_workspace_dir, self._workspace_root(workspace_id))

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


class ResultPresenter:
    """Presents analysis results in various formats."""

    def __init__(self, format_type: str = "table"):
        """Initialize presenter.

        Args:
            format_type: Output format - "table", "json", or "interactive"
        """
        self.format_type = format_type.lower()
        self.console = Console()

    def display(self, results: AnalysisResults) -> None:
        """Display results in the configured format."""
        if self.format_type == "table":
            self._display_table(results)
        elif self.format_type == "json":
            self._display_json(results)
        elif self.format_type == "interactive":
            self._display_interactive(results)
        else:
            raise ValueError(f"Unknown format: {self.format_type}")

    def _display_table(self, results: AnalysisResults) -> None:
        """Display results as a table."""
        # Summary
        self.console.print(f"\n[bold]Remora Analysis Results[/bold]")
        self.console.print(f"Total nodes: {results.total_nodes}")
        self.console.print(f"Successful: {results.successful_operations}")
        self.console.print(f"Failed: {results.failed_operations}")
        self.console.print(f"Skipped: {results.skipped_operations}\n")

        # Build operation columns
        all_operations: set[str] = set()
        for node in results.nodes:
            all_operations.update(node.operations.keys())
        operations = sorted(all_operations)

        if not operations:
            self.console.print("[yellow]No operations run[/yellow]")
            return

        # Create table
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Node", style="cyan", no_wrap=True)
        for op in operations:
            table.add_column(op, justify="center")

        # Add rows
        for node in results.nodes:
            row = [f"{node.file_path.name}::{node.node_name}"]
            for op in operations:
                if op in node.operations:
                    result = node.operations[op]
                    if result.status == AgentStatus.SUCCESS:
                        symbol = "[green]✓[/green]"
                    elif result.status == AgentStatus.FAILED:
                        symbol = "[red]✗[/red]"
                    else:
                        symbol = "[yellow]-[/yellow]"
                else:
                    symbol = "[dim]-[/dim]"
                row.append(symbol)
            table.add_row(*row)

        self.console.print(table)

    def _display_json(self, results: AnalysisResults) -> None:
        """Display results as JSON."""
        import json

        self.console.print(json.dumps(results.model_dump(mode="json"), indent=2))

    def _display_interactive(self, results: AnalysisResults) -> None:
        """Display results interactively."""
        self._display_table(results)

    async def interactive_review(
        self,
        analyzer: RemoraAnalyzer,
        results: AnalysisResults,
    ) -> None:
        """Run interactive review session.

        Args:
            analyzer: RemoraAnalyzer instance
            results: Analysis results to review
        """
        self.console.print("\n[bold]Interactive Review Mode[/bold]\n")
        self.console.print("Commands: [a]ccept, [r]eject, [s]kip, [d]iff, [q]uit\n")

        for node in results.nodes:
            for op_name, result in node.operations.items():
                if result.status != AgentStatus.SUCCESS:
                    continue

                self.console.print(f"\n[cyan]{node.file_path.name}::{node.node_name}[/cyan]")
                self.console.print(f"  {op_name}: {result.summary}")

                while True:
                    choice = input("  [a/r/s/d/q]? ").lower().strip()

                    if choice == "a":
                        await analyzer.accept(node.node_id, op_name)
                        self.console.print("  [green]✓ Accepted[/green]")
                        break
                    elif choice == "r":
                        await analyzer.reject(node.node_id, op_name)
                        self.console.print("  [red]✓ Rejected[/red]")
                        break
                    elif choice == "s":
                        self.console.print("  [yellow]Skipped[/yellow]")
                        break
                    elif choice == "d":
                        self.console.print("  [dim]Changes in workspace:[/dim]")
                        workspace_id = analyzer._get_workspace_id(node.node_id, op_name)
                        workspace_db = analyzer._workspace_db_path(workspace_id)
                        if not workspace_db.exists():
                            self.console.print("  [yellow]No workspace database found.[/yellow]")
                            continue
                        
                        async def _show_changes() -> None:
                            async with analyzer._workspace_manager.open_workspace(workspace_db) as workspace:
                                changed_paths = await workspace.overlay.list_changes("/")
                                for path in changed_paths:
                                    self.console.print(f"    [green]modified/new:[/green] {path}")
                                if not changed_paths:
                                    self.console.print("    [yellow]No changes detected.[/yellow]")
                        
                        await _show_changes()
                    elif choice == "q":
                        return
                    else:
                        self.console.print("  [yellow]Invalid choice[/yellow]")
