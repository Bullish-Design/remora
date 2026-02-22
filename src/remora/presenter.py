# src/remora/presenter.py
"""Presentation layer for analysis results."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

from remora.results import AgentStatus, AnalysisResults

if TYPE_CHECKING:
    from remora.analyzer import RemoraAnalyzer


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
                        # The presenter now delegates workspace details to the analyzer bridge
                        workspace_id = analyzer._get_workspace_id(node.node_id, op_name)
                        
                        # Use bridge properties, assume _bridge encapsulates CAIRN workspace interactions
                        if not hasattr(analyzer, '_bridge'):
                            self.console.print("  [yellow]Analyzer is missing bridge connection.[/yellow]")
                            continue
                            
                        workspace_db = analyzer._bridge.get_workspace_db_path(workspace_id)
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
