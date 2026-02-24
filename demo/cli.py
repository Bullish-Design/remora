"""CLI entry points for AST Summary demo."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from cairn.runtime.workspace_manager import WorkspaceManager

from demo import engine, events
from demo import parser as ast_parser
from demo.config import DemoConfig, load_demo_config
from demo.models import AstNode
from demo.tui import AstDashboardApp

SUPPORTED_EXTENSIONS = {".py", ".md", ".toml"}


def _run_summary(filepath: Path, config: DemoConfig) -> None:
    """Parse a file and generate recursive summaries."""
    events.set_event_file(config.event_file)
    events.clear_events()

    root_node, _ = ast_parser.parse_file(filepath)

    all_nodes = root_node.flatten()
    events.emit_event("parsed", "AST", "System", f"Discovered {len(all_nodes)} nodes. Initiating workspaces.")

    config.cache_dir.mkdir(parents=True, exist_ok=True)
    workspace_manager = WorkspaceManager()

    output_root = Path(__file__).parent / "output" / datetime.now().strftime("%Y%m%d_%H%M%S")
    asyncio.run(engine.process_node(root_node, workspace_manager, config.cache_dir, config, output_root=output_root))

    events.emit_event("complete", "System", "System", "AST Summary Rollup Complete.")
    typer.echo(f"Done! Output saved to {output_root}/")

    typer.echo("\n--- Final Aggregated Summaries ---")
    _display_tree(root_node)


def _run_summary_for_file(filepath: Path, config: DemoConfig, output_root: Path) -> AstNode:
    """Parse and summarize a single file."""
    events.set_event_file(config.event_file)

    root_node, _ = ast_parser.parse_file(filepath)
    all_nodes = root_node.flatten()
    events.emit_event("parsed", "AST", filepath.name, f"Discovered {len(all_nodes)} nodes.")

    workspace_manager = WorkspaceManager()
    asyncio.run(
        engine.process_node(
            root_node, workspace_manager, config.cache_dir, config, output_root=output_root / filepath.stem
        )
    )

    return root_node


def _collect_files(directory: Path) -> list[Path]:
    """Recursively collect all supported files from a directory."""
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(directory.rglob(f"*{ext}"))
    return sorted(files)


def _format_node_block(node: AstNode, depth: int = 0) -> list[str]:
    """Format a node and its children into indented lines."""
    indent = "    " * depth
    lines = [f"{indent}- {node.node_type}: {node.name}"]
    summary = node.summary or "No summary generated"
    lines.append(f"{indent}    Summary:")
    for line in summary.splitlines() or [summary]:
        text = line.strip()
        lines.append(f"{indent}        {text}")
    for child in node.children:
        lines.extend(_format_node_block(child, depth + 1))
    return lines


def _render_summary_lines(summary: str, indent_level: int = 1) -> list[str]:
    """Render multi-line summary with indentation."""
    indent = "    " * indent_level
    lines = summary.splitlines()
    if not lines:
        lines = ["No summary generated"]
    return [(f"{indent}{line}" if line else indent) for line in lines]


def _display_tree(node: AstNode, indent: int = 0) -> None:
    """Print the final tree to stdout."""
    prefix = "  " * indent
    typer.echo(f"{prefix}- {node.node_type}: {node.name}")
    typer.echo(f"{prefix}  Summary: {node.summary}")
    for child in node.children:
        _display_tree(child, indent + 1)


def _launch_ui(event_file: Path) -> None:
    """Launch the Rich dashboard."""
    events.set_event_file(event_file)
    app = AstDashboardApp(event_file)
    app.run()


app = typer.Typer(help="AST Summary Demo - Recursive Documentation & Review")


@app.command()
def run(
    filepath: Path = typer.Argument(..., help="Path to the file or directory to summarize"),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-f",
        help="Path to config file",
    ),
    cache: Path | None = typer.Option(
        None,
        "--cache",
        "-c",
        help="Cache directory for workspaces",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model to use for summarization",
    ),
    base_url: str | None = typer.Option(
        None,
        "--url",
        "-u",
        help="vLLM server base URL",
    ),
    concurrency: int = typer.Option(
        4,
        "--concurrency",
        "-n",
        help="Number of files to process concurrently",
    ),
) -> None:
    """Parse a file or directory and generate recursive summaries."""
    config = load_demo_config(config_path)

    if cache:
        config.cache_dir = cache
    if model:
        config.model = model
    if base_url:
        config.base_url = base_url

    if filepath.is_dir():
        files = _collect_files(filepath)
        if not files:
            typer.echo(f"No supported files (.py, .md, .toml) found in {filepath}")
            return

        typer.echo(f"Found {len(files)} files to process concurrently...")
        output_root = Path(__file__).parent / "output" / datetime.now().strftime("%Y%m%d_%H%M%S")

        config.cache_dir.mkdir(parents=True, exist_ok=True)

        def process_file(file_path: Path) -> dict[str, Any]:
            try:
                root = _run_summary_for_file(file_path, config, output_root / file_path.stem)
                return {"file": file_path.name, "status": "success", "root": root}
            except Exception as e:
                return {"file": file_path.name, "status": "error", "error": str(e)}

        with typer.progressbar(length=len(files), label="Processing files") as progress:
            with asyncio.Runner() as runner:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                    futures = [executor.submit(process_file, f) for f in files]
                    results = []
                    for future in concurrent.futures.as_completed(futures):
                        result = future.result()
                        results.append(result)
                        progress.update(1)

        typer.echo(f"\nDone! Output saved to {output_root}/")

        success_count = sum(1 for r in results if r["status"] == "success")
        error_count = sum(1 for r in results if r["status"] == "error")
        typer.echo(f"\n--- Summary ---")
        typer.echo(f"Successful: {success_count}, Errors: {error_count}")

        final_sections: list[str] = []
        for r in results:
            final_sections.append(f"## {r['file']}")
            final_sections.append("")
            if r["status"] == "success" and r.get("root"):
                root = r["root"]
                final_sections.append("### File Summary")
                final_sections.append("")
                final_sections.extend(_render_summary_lines(root.summary or "No summary generated", 1))
                final_sections.append("")
                final_sections.append("### Nodes")
                final_sections.append("")
                final_sections.extend(_format_node_block(root))
            else:
                final_sections.append("**Error:**")
                final_sections.append("")
                final_sections.append(f"    {r.get('error', 'Unknown error')}")
            final_sections.append("")

        final_sections.append("### Final Overview")
        final_sections.append("")
        final_sections.append(f"Successful: {success_count}")
        final_sections.append(f"Errors: {error_count}")

        final_summaries_md = output_root / "final_summaries.md"
        final_summaries_md.write_text("\n".join(final_sections), encoding="utf-8")
        typer.echo(f"Final summaries written to {final_summaries_md}")
    else:
        _run_summary(filepath, config)


@app.command()
def ui(
    event_file: Path = typer.Option(
        Path(".ast_summary_events.jsonl"),
        "--events",
        "-e",
        help="Path to the events JSONL file",
    ),
) -> None:
    """Launch the live dashboard."""
    _launch_ui(event_file)


if __name__ == "__main__":
    app()
