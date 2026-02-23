"""Recursive generation engine for AST Summary."""

from __future__ import annotations

import asyncio
from pathlib import Path

from cairn.runtime.workspace_manager import WorkspaceManager

from demo.config import DemoConfig
from demo.events import emit_event
from demo.models import AstNode
from demo.summarizer import Summarizer


async def process_node(
    node: AstNode,
    workspace_manager: WorkspaceManager,
    cache_root: Path,
    config: DemoConfig | None = None,
    max_concurrency: int = 10,
) -> str:
    """Recursively process a node: spin up workspace, await children, summarize.

    Args:
        node: The AST node to process.
        workspace_manager: Cairn WorkspaceManager instance.
        cache_root: Root directory for workspace databases.
        config: Demo configuration.
        max_concurrency: Maximum concurrent workspace operations.

    Returns:
        The generated summary for this node.
    """
    config = config or DemoConfig()
    summarizer = Summarizer(config)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def process_with_semaphore(n: AstNode) -> str:
        async with semaphore:
            return await _process_single_node(n, workspace_manager, cache_root, summarizer)

    child_tasks = [process_with_semaphore(child) for child in node.children]
    child_summaries_raw = await asyncio.gather(*child_tasks, return_exceptions=True)

    valid_summaries: list[str] = []
    for summary in child_summaries_raw:
        if isinstance(summary, Exception):
            valid_summaries.append(f"[Error: {summary}]")
        elif isinstance(summary, str):
            valid_summaries.append(summary)

    return await _generate_in_workspace(node, valid_summaries, workspace_manager, cache_root, summarizer)


async def _process_single_node(
    node: AstNode,
    workspace_manager: WorkspaceManager,
    cache_root: Path,
    summarizer: Summarizer,
) -> str:
    """Process a single node (used for children)."""
    child_tasks = []
    for child in node.children:
        child_tasks.append(_process_single_node(child, workspace_manager, cache_root, summarizer))

    child_summaries_raw = await asyncio.gather(*child_tasks, return_exceptions=True)

    valid_summaries: list[str] = []
    for summary in child_summaries_raw:
        if isinstance(summary, Exception):
            valid_summaries.append(f"[Error: {summary}]")
        elif isinstance(summary, str):
            valid_summaries.append(summary)

    return await _generate_in_workspace(node, valid_summaries, workspace_manager, cache_root, summarizer)


async def _generate_in_workspace(
    node: AstNode,
    child_summaries: list[str],
    workspace_manager: WorkspaceManager,
    cache_root: Path,
    summarizer: Summarizer,
) -> str:
    """Generate summary inside a Cairn workspace."""
    workspace_id = f"summary-{id(node)}"
    workspace_db = cache_root / "workspaces" / workspace_id / "workspace.db"
    workspace_db.parent.mkdir(parents=True, exist_ok=True)

    emit_event("workspace_provision", node.name, node.node_type, "Provisioning Cairn workspace")

    async with workspace_manager.open_workspace(workspace_db) as workspace:
        await workspace.files.write("/node_source.txt", node.source_text)

        emit_event("summarizing", node.name, node.node_type, "Generating LLM summary")

        summary = await summarizer.summarize(node, child_summaries)
        node.summary = summary
        node.status = "done"

        await workspace.files.write("/summary.md", summary)

    emit_event("done", node.name, node.node_type, "Rollup complete", extra={"summary": summary})
    return summary
