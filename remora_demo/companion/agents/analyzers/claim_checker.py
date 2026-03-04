"""Claim checker analyzer agent.

Subscribes to context changes and identifies prose assertions that lack
supporting sources. Only runs for markdown/prose content.

Writes UnsupportedClaim objects to /companion/analysis/unsupported_claims/*.

No LLM needed — uses simple heuristics: percentage patterns, superlatives,
authority appeals, and quantitative assertions.
"""

import re
import time
from dataclasses import dataclass
from typing import Any

from remora_demo.companion.agents.base import (
    AgentActivation,
    AgentBase,
    WorkspaceInterface,
    subscribe,
)
from remora_demo.companion.models.events import PathChanged
from remora_demo.companion.models.workspace import UnsupportedClaim

# Patterns that indicate an unsupported claim
_PERCENTAGE_RE = re.compile(r"\d+\s*%")
_MULTIPLIER_RE = re.compile(r"\d+x\b", re.IGNORECASE)

_SUPERLATIVES = [
    "fastest",
    "slowest",
    "best",
    "worst",
    "most",
    "least",
    "always",
    "never",
    "every",
    "all",
]

_AUTHORITY_PHRASES = [
    "studies show",
    "studies prove",
    "research shows",
    "research proves",
    "experts agree",
    "it is well known",
    "it is proven",
    "everyone knows",
    "science shows",
    "data shows",
    "benchmarks show",
]


@dataclass
class ClaimCheckerConfig:
    """Configuration for claim checker."""

    max_claims: int = 5


class ClaimChecker(AgentBase):
    """Identifies unsupported claims in prose/markdown content.

    Subscribes to: /companion/context/current_region (when content_type is markdown)
    Writes to: /companion/analysis/unsupported_claims/*
    """

    def __init__(
        self,
        workspace: WorkspaceInterface,
        config: ClaimCheckerConfig | None = None,
    ) -> None:
        super().__init__("claim_checker")
        self.workspace = workspace
        self.config = config or ClaimCheckerConfig()
        self._check_count = 0

    @subscribe("/companion/context/current_region")
    async def on_context_change(self, change: PathChanged) -> None:
        """Handle context region changes — check for unsupported claims."""
        activation = AgentActivation(
            id=f"claim_checker_{self._check_count}",
            agent_name=self.name,
            trigger=f"context_change:{change.path}",
            started_at=time.time(),
        )

        # Only run on markdown/prose content
        content_type = await self.workspace.read("/companion/context/content_type")
        if content_type != "markdown":
            # Clear any old claims and return
            await self._clear_claims()
            activation.ended_at = time.time()
            activation.status = "success"
            self._activations.append(activation)
            self._check_count += 1
            return

        file_path = await self.workspace.read("/companion/context/file_path") or "unknown"
        text = change.value if isinstance(change.value, str) else str(change.value)

        self.record_input("current_region", {"file": file_path, "text_len": len(text)})

        # Find unsupported claims
        claims = _find_claims(text, file_path)
        claims = claims[: self.config.max_claims]

        # Clear old claims
        await self._clear_claims()

        # Write new claims
        for i, claim in enumerate(claims):
            path = f"/companion/analysis/unsupported_claims/{i}"
            await self.workspace.write(path, claim)
            self.record_output(path)

        self._check_count += 1
        activation.ended_at = time.time()
        activation.status = "success"
        self._activations.append(activation)

    async def _clear_claims(self) -> None:
        """Remove all existing unsupported claim entries."""
        old_paths = await self.workspace.list("/companion/analysis/unsupported_claims/*")
        for path in old_paths:
            await self.workspace.delete(path)

    async def process(self, data: Any) -> None:
        """Process method for AgentBase compatibility."""
        if isinstance(data, PathChanged):
            await self.on_context_change(data)


def _find_claims(text: str, file_path: str) -> list[UnsupportedClaim]:
    """Identify assertion sentences that lack supporting sources.

    Uses heuristic pattern matching — no LLM required.
    """
    claims: list[UnsupportedClaim] = []
    sentences = _split_sentences(text)

    for sentence in sentences:
        sentence_stripped = sentence.strip()
        if not sentence_stripped:
            continue

        reason = _check_sentence(sentence_stripped)
        if reason:
            suggestions = _suggest_sources(reason)
            claims.append(
                UnsupportedClaim(
                    claim=sentence_stripped,
                    location=file_path,
                    suggestions=suggestions,
                )
            )

    return claims


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences (simple heuristic)."""
    # Split on sentence-ending punctuation followed by space or end of string
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def _check_sentence(sentence: str) -> str | None:
    """Check if a sentence contains an unsupported claim.

    Returns the reason string if it is a claim, None otherwise.
    """
    lower = sentence.lower()

    # Check for percentage claims
    if _PERCENTAGE_RE.search(sentence):
        return "percentage"

    # Check for multiplier claims (e.g., "3x faster")
    if _MULTIPLIER_RE.search(sentence):
        return "multiplier"

    # Check for authority appeals without citations
    for phrase in _AUTHORITY_PHRASES:
        if phrase in lower:
            return "authority"

    # Check for superlatives
    for word in _SUPERLATIVES:
        # Match whole words only
        if re.search(rf"\b{word}\b", lower):
            return "superlative"

    return None


def _suggest_sources(reason: str) -> list[str]:
    """Generate source suggestions based on claim type."""
    suggestions_map = {
        "percentage": ["Add a citation or link to the source of this statistic"],
        "multiplier": ["Add a citation or link to the benchmark/measurement"],
        "authority": ["Cite the specific study or research being referenced"],
        "superlative": ["Consider qualifying this claim or adding supporting evidence"],
    }
    return suggestions_map.get(reason, ["Consider adding a supporting source"])
