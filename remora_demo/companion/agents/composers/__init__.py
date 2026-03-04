"""Composer agents: generate output artifacts."""

from remora_demo.companion.agents.composers.session_summarizer import (
    SessionSummarizer,
    SessionSummarizerConfig,
)
from remora_demo.companion.agents.composers.sidebar_composer import (
    SidebarComposer,
    SidebarComposerConfig,
)

__all__ = [
    "SessionSummarizer",
    "SessionSummarizerConfig",
    "SidebarComposer",
    "SidebarComposerConfig",
]
