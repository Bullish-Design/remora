from __future__ import annotations

import time
from pydantic import Field

from remora.core.events.events import _FrozenEvent

# ============================================================================
# Source Events
# ============================================================================
class CompanionSessionTick(_FrozenEvent):
    elapsed_ms: int
    tick_number: int
    timestamp: float = Field(default_factory=time.time)

# ============================================================================
# Stage 1 Output Events
# ============================================================================
class CompanionContextExtracted(_FrozenEvent):
    file: str
    line: int
    structure_type: str       # "function", "class", "module", "section"
    structure_name: str
    content_type: str         # "python", "markdown", "toml", etc.
    surrounding_code: str
    scope_path: tuple[str, ...]
    timestamp: float = Field(default_factory=time.time)

class CompanionEditSummary(_FrozenEvent):
    file: str
    summary: str
    edit_count: int
    lines_changed: int
    timestamp: float = Field(default_factory=time.time)

# ============================================================================
# Stage 2 Output Events
# ============================================================================
class CompanionSearchResult(_FrozenEvent):
    file: str
    chunk_text: str
    score: float
    content_type: str | None = None
    chunk_type: str | None = None
    start_line: int = 0
    end_line: int = 0
    name: str | None = None

class CompanionSearchCompleted(_FrozenEvent):
    query: str
    results: tuple[CompanionSearchResult, ...]
    search_type: str           # "vector", "fulltext", "hybrid"
    timestamp: float = Field(default_factory=time.time)

class CompanionIndexUpdated(_FrozenEvent):
    file: str
    chunks_stored: int
    chunks_skipped: int
    chunks_created: int
    timestamp: float = Field(default_factory=time.time)

# ============================================================================
# Stage 3 Output Events
# ============================================================================
class CompanionConnection(_FrozenEvent):
    source: str
    target: str
    relationship: str         # "calls", "imports", "similar_to", "shares_pattern"
    confidence: float

class CompanionConnectionsFound(_FrozenEvent):
    connections: tuple[CompanionConnection, ...]
    timestamp: float = Field(default_factory=time.time)

class CompanionTaskInferred(_FrozenEvent):
    task_description: str
    confidence: float
    evidence: tuple[str, ...]
    timestamp: float = Field(default_factory=time.time)

class CompanionClaim(_FrozenEvent):
    claim_text: str
    status: str               # "verified", "unverified", "contradicted"
    evidence: str

class CompanionClaimsChecked(_FrozenEvent):
    claims: tuple[CompanionClaim, ...]
    timestamp: float = Field(default_factory=time.time)

# ============================================================================
# Stage 4 (Sink) Events
# ============================================================================
class CompanionSidebarComposed(_FrozenEvent):
    markdown: str
    sections: tuple[str, ...]
    timestamp: float = Field(default_factory=time.time)

# ============================================================================
# Swarm Request Events (Future Interface)
# ============================================================================
class CompanionSwarmRequest(_FrozenEvent):
    requesting_handler: str
    analysis_type: str        # "task_inference", "claim_verification", etc.
    context: str
    target_workspace: str     # Cairn workspace path for results
    timestamp: float = Field(default_factory=time.time)

class CompanionSwarmResult(_FrozenEvent):
    requesting_handler: str
    analysis_type: str
    summary: str
    timestamp: float = Field(default_factory=time.time)

CompanionEvent = (
    CompanionSessionTick | CompanionContextExtracted | CompanionEditSummary
    | CompanionSearchCompleted | CompanionIndexUpdated | CompanionConnectionsFound
    | CompanionTaskInferred | CompanionClaimsChecked | CompanionSidebarComposed
    | CompanionSwarmRequest | CompanionSwarmResult
)
