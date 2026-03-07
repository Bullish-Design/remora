from __future__ import annotations

import time
from remora.core.events.events import _FrozenEvent
from remora.companion.events import CompanionSidebarComposed
from remora.companion.handlers.base import CompanionHandlerBase
from remora.companion.state import CompanionState

class SidebarComposerHandler(CompanionHandlerBase):
    """Composes the final sidebar markdown from workspace state."""
    
    async def handle(self, event: _FrozenEvent, state: CompanionState) -> list[_FrozenEvent]:
        lines = []
        lines.append("# Companion Context\n")
        
        ctx = state.context
        if ctx:
            lines.append(f"> Tracking: `{ctx.file}:{ctx.line}`")
            lines.append("## What You're Looking At\n")
            lines.append(f"**{ctx.structure_type.title()}:** `{ctx.structure_name}`\n")
            lines.append(f"Content type: {ctx.content_type}\n")
            
        search_results = state.search_results
        if search_results and search_results.results:
            lines.append("---\n## Related Content\n")
            for r in search_results.results[:5]:
                score_pct = int(r.score * 100)
                snippet = r.chunk_text.replace("\n", " ").strip()
                if len(snippet) > 80: snippet = snippet[:80] + "..."
                lines.append(f"- **{r.file}** ({score_pct}% similar)\n  > {snippet}\n")
                
        conns = state.connections
        if conns and conns.connections:
            lines.append("---\n## Connections You Might Have Missed\n")
            for c in conns.connections[:5]:
                lines.append(f"`{c.source}` → `{c.target}` ({c.relationship})")
                
        task = state.task
        if task:
            lines.append(f"---\n## Current Task\n**{task.task_description}** ({int(task.confidence*100)}% confidence)")
            
        claims = state.claims
        if claims and claims.claims:
            unverified = [c for c in claims.claims if c.status == "unverified"]
            if unverified:
                lines.append("---\n## Unsupported Claims Detected\n")
                for c in unverified[:3]:
                    lines.append(f"> \"{c.claim_text}\"\n> Needs source.\n")
                    
        summary = state.edit_summary
        if summary:
            lines.append(f"---\n## Latest Activity\n{summary.summary}")

        markdown = "\n".join(lines)
        return [CompanionSidebarComposed(markdown=markdown, sections=())]
