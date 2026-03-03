"""Sidebar composer agent.

Composes the final sidebar markdown from workspace state.
Writes to /companion/output/sidebar.md
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from remora_demo.companion.agents.base import AgentBase, WorkspaceInterface, subscribe
from remora_demo.companion.models.events import PathChanged
from remora_demo.companion.models.workspace import (
    Connection,
    CursorPosition,
    Definition,
    Question,
    SimilarResult,
    Structure,
    TaskInference,
    UnsupportedClaim,
    VaultLink,
)


@dataclass
class SidebarComposerConfig:
    """Configuration for sidebar composer."""

    debounce_ms: int = 100  # Debounce rapid updates
    max_similar_results: int = 5
    max_definitions: int = 5
    max_questions: int = 5
    max_connections: int = 5


class SidebarComposer(AgentBase):
    """Composes the sidebar markdown from workspace state.

    Subscribes to: /companion/context/*, /companion/search/*, /companion/analysis/*
    Writes to: /companion/output/sidebar.md, /companion/output/sidebar_updated_at
    """

    def __init__(
        self,
        workspace: WorkspaceInterface,
        config: SidebarComposerConfig | None = None,
    ) -> None:
        super().__init__("sidebar_composer")
        self.workspace = workspace
        self.config = config or SidebarComposerConfig()

    @subscribe("/companion/context/*", debounce_ms=100)
    async def on_context_change(self, change: PathChanged) -> None:
        """Handle context changes."""
        await self.compose()

    @subscribe("/companion/search/*", debounce_ms=100)
    async def on_search_change(self, change: PathChanged) -> None:
        """Handle search result changes."""
        await self.compose()

    @subscribe("/companion/analysis/*", debounce_ms=100)
    async def on_analysis_change(self, change: PathChanged) -> None:
        """Handle analysis changes."""
        await self.compose()

    async def compose(self) -> str:
        """Compose the sidebar markdown and write to workspace."""
        # Read all context
        file_path = await self.workspace.read("/companion/context/file_path")
        cursor_pos: CursorPosition | None = await self.workspace.read("/companion/context/cursor_position")
        content_type = await self.workspace.read("/companion/context/content_type")
        structure: Structure | None = await self.workspace.read("/companion/context/structure")

        # Read search results
        similar_paths = await self.workspace.list("/companion/search/similar/*")
        similar_results: list[SimilarResult] = []
        for path in similar_paths[: self.config.max_similar_results]:
            result = await self.workspace.read(path)
            if result:
                similar_results.append(result)

        # Read definitions
        def_paths = await self.workspace.list("/companion/search/definitions/*")
        definitions: list[Definition] = []
        for path in def_paths[: self.config.max_definitions]:
            defn = await self.workspace.read(path)
            if defn:
                definitions.append(defn)

        # Read vault links
        vault_paths = await self.workspace.list("/companion/search/vault_links/*")
        vault_links: list[VaultLink] = []
        for path in vault_paths:
            link = await self.workspace.read(path)
            if link:
                vault_links.append(link)

        # Read analysis
        inferred_task: TaskInference | None = await self.workspace.read("/companion/analysis/inferred_task")
        connection_paths = await self.workspace.list("/companion/analysis/connections/*")
        connections: list[Connection] = []
        for path in connection_paths[: self.config.max_connections]:
            conn = await self.workspace.read(path)
            if conn:
                connections.append(conn)

        question_paths = await self.workspace.list("/companion/analysis/questions/*")
        questions: list[Question] = []
        for path in question_paths[: self.config.max_questions]:
            q = await self.workspace.read(path)
            if q:
                questions.append(q)

        claim_paths = await self.workspace.list("/companion/analysis/unsupported_claims/*")
        claims: list[UnsupportedClaim] = []
        for path in claim_paths:
            claim = await self.workspace.read(path)
            if claim:
                claims.append(claim)

        # Compose markdown
        lines = []

        # Header
        lines.append("# Companion Context\n")

        if file_path and cursor_pos:
            lines.append(f"> Tracking: `{file_path}:{cursor_pos.line}`")
        lines.append(f"> Updated: {datetime.now().strftime('%H:%M:%S')}\n")
        lines.append("---\n")

        # What you're looking at
        lines.append("## What You're Looking At\n")
        if structure:
            lines.append(f"**{structure.structure_type.title()}:** `{structure.name}`")
            if structure.parent:
                lines.append(f"in `{structure.parent}`")
            lines.append("")
        if content_type:
            lines.append(f"Content type: {content_type}\n")

        # Related content
        if similar_results:
            lines.append("---\n")
            lines.append("## Related Content\n")
            for r in similar_results:
                score_pct = int(r.score * 100)
                lines.append(f"- **{r.file}** ({score_pct}% similar)")
                # Clean up snippet for display
                snippet = r.snippet.replace("\n", " ").strip()
                if len(snippet) > 100:
                    snippet = snippet[:100] + "..."
                lines.append(f"  > {snippet}\n")

        # Vault links
        if vault_links:
            lines.append("### From Your Notes\n")
            for link in vault_links:
                lines.append(f"- [[{link.note}]] — {link.excerpt[:50]}...\n")

        # Definitions
        if definitions:
            lines.append("---\n")
            lines.append("## Definitions\n")
            for defn in definitions:
                lines.append(f"**{defn.term}:** {defn.definition}")
                lines.append(f"<small>Source: {defn.source}</small>\n")

        # Connections
        if connections:
            lines.append("---\n")
            lines.append("## Connections You Might Have Missed\n")
            for conn in connections:
                lines.append(f"### {conn.insight}")
                lines.append(f"`{conn.from_file}` → `{conn.to_file}`")
                lines.append(f"Type: {conn.connection_type}\n")

        # Questions
        if questions:
            lines.append("---\n")
            lines.append("## Questions Worth Considering\n")
            for q in questions:
                lines.append(f"- {q.question}")
            lines.append("")

        # Inferred task
        if inferred_task:
            lines.append("---\n")
            lines.append("## Current Task\n")
            lines.append(f"**{inferred_task.description}**")
            lines.append(f"Confidence: {int(inferred_task.confidence * 100)}%\n")
            if inferred_task.evidence:
                lines.append("Evidence:")
                for ev in inferred_task.evidence:
                    lines.append(f"- {ev}")
            lines.append("")

        # Unsupported claims
        if claims:
            lines.append("---\n")
            lines.append("## Review Needed\n")
            for claim in claims:
                lines.append(f'> "{claim.claim}"')
                lines.append("> ")
                lines.append("> No supporting source found. Consider:")
                for sug in claim.suggestions:
                    lines.append(f"> - {sug}")
                lines.append("")

        # Footer
        lines.append("---\n")
        lines.append(f"<small>Updated: {datetime.now().isoformat()}</small>")

        markdown = "\n".join(lines)

        # Write to workspace
        await self.workspace.write("/companion/output/sidebar.md", markdown)
        self.record_output("/companion/output/sidebar.md")

        await self.workspace.write("/companion/output/sidebar_updated_at", datetime.now().isoformat())
        self.record_output("/companion/output/sidebar_updated_at")

        return markdown

    async def process(self, data: Any) -> None:
        """Process method for AgentBase compatibility."""
        await self.compose()
