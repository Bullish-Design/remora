"""Tests for the claim_checker analyzer agent.

The claim checker subscribes to context changes, identifies prose assertions
that lack supporting sources, and writes UnsupportedClaim objects to
/companion/analysis/unsupported_claims/*.
"""

from __future__ import annotations

import pytest

from remora_demo.companion.agents.base import InMemoryWorkspace
from remora_demo.companion.agents.analyzers.claim_checker import (
    ClaimChecker,
    ClaimCheckerConfig,
)
from remora_demo.companion.models.events import PathChanged
from remora_demo.companion.models.workspace import UnsupportedClaim


@pytest.fixture
def workspace() -> InMemoryWorkspace:
    return InMemoryWorkspace()


@pytest.fixture
def checker(workspace: InMemoryWorkspace) -> ClaimChecker:
    return ClaimChecker(workspace)


# -- Construction --


class TestClaimCheckerInit:
    def test_creates_with_defaults(self, workspace: InMemoryWorkspace) -> None:
        agent = ClaimChecker(workspace)
        assert agent.name == "claim_checker"

    def test_creates_with_custom_config(self, workspace: InMemoryWorkspace) -> None:
        cfg = ClaimCheckerConfig(max_claims=3)
        agent = ClaimChecker(workspace, config=cfg)
        assert agent.config.max_claims == 3

    def test_has_subscriptions(self, checker: ClaimChecker) -> None:
        # Should subscribe to context path changes
        assert len(checker.subscriptions) > 0


# -- Only runs on prose/markdown --


class TestContentTypeFilter:
    async def test_skips_code_content(self, workspace: InMemoryWorkspace, checker: ClaimChecker) -> None:
        """Claim checker should not flag claims in code files."""
        await workspace.write("/companion/context/content_type", "code")
        await workspace.write("/companion/context/file_path", "src/main.py")
        await workspace.write(
            "/companion/context/current_region",
            "This is definitely faster than all other implementations.",
        )

        await checker.on_context_change(
            PathChanged(
                path="/companion/context/current_region",
                value="This is definitely faster than all other implementations.",
            )
        )

        paths = await workspace.list("/companion/analysis/unsupported_claims/*")
        assert len(paths) == 0

    async def test_runs_on_markdown_content(self, workspace: InMemoryWorkspace, checker: ClaimChecker) -> None:
        """Claim checker should process markdown files."""
        await workspace.write("/companion/context/content_type", "markdown")
        await workspace.write("/companion/context/file_path", "docs/architecture.md")
        await workspace.write(
            "/companion/context/current_region",
            "Studies show this approach reduces latency by 50%.",
        )

        await checker.on_context_change(
            PathChanged(
                path="/companion/context/current_region",
                value="Studies show this approach reduces latency by 50%.",
            )
        )

        paths = await workspace.list("/companion/analysis/unsupported_claims/*")
        assert len(paths) >= 1


# -- Claim detection --


class TestClaimDetection:
    async def test_detects_statistical_claim(self, workspace: InMemoryWorkspace, checker: ClaimChecker) -> None:
        await workspace.write("/companion/context/content_type", "markdown")
        await workspace.write("/companion/context/file_path", "notes/research.md")
        await workspace.write(
            "/companion/context/current_region",
            "Performance improved by 40% after the migration.",
        )

        await checker.on_context_change(
            PathChanged(
                path="/companion/context/current_region",
                value="Performance improved by 40% after the migration.",
            )
        )

        paths = await workspace.list("/companion/analysis/unsupported_claims/*")
        assert len(paths) >= 1
        claim: UnsupportedClaim = await workspace.read(paths[0])
        assert isinstance(claim, UnsupportedClaim)
        assert len(claim.claim) > 0

    async def test_detects_superlative_claim(self, workspace: InMemoryWorkspace, checker: ClaimChecker) -> None:
        await workspace.write("/companion/context/content_type", "markdown")
        await workspace.write("/companion/context/file_path", "docs/comparison.md")
        await workspace.write(
            "/companion/context/current_region",
            "This is the fastest implementation available.",
        )

        await checker.on_context_change(
            PathChanged(
                path="/companion/context/current_region",
                value="This is the fastest implementation available.",
            )
        )

        paths = await workspace.list("/companion/analysis/unsupported_claims/*")
        assert len(paths) >= 1

    async def test_does_not_flag_neutral_prose(self, workspace: InMemoryWorkspace, checker: ClaimChecker) -> None:
        """Neutral descriptive text should not be flagged."""
        await workspace.write("/companion/context/content_type", "markdown")
        await workspace.write("/companion/context/file_path", "docs/overview.md")
        await workspace.write(
            "/companion/context/current_region",
            "This module handles HTTP requests.",
        )

        await checker.on_context_change(
            PathChanged(
                path="/companion/context/current_region",
                value="This module handles HTTP requests.",
            )
        )

        paths = await workspace.list("/companion/analysis/unsupported_claims/*")
        assert len(paths) == 0

    async def test_detects_authority_claim(self, workspace: InMemoryWorkspace, checker: ClaimChecker) -> None:
        """Claims appealing to authority without citation should be flagged."""
        await workspace.write("/companion/context/content_type", "markdown")
        await workspace.write("/companion/context/file_path", "docs/design.md")
        await workspace.write(
            "/companion/context/current_region",
            "Research proves that microservices are always better than monoliths.",
        )

        await checker.on_context_change(
            PathChanged(
                path="/companion/context/current_region",
                value="Research proves that microservices are always better than monoliths.",
            )
        )

        paths = await workspace.list("/companion/analysis/unsupported_claims/*")
        assert len(paths) >= 1


# -- Claim metadata --


class TestClaimMetadata:
    async def test_claim_has_location(self, workspace: InMemoryWorkspace, checker: ClaimChecker) -> None:
        await workspace.write("/companion/context/content_type", "markdown")
        await workspace.write("/companion/context/file_path", "docs/perf.md")
        await workspace.write(
            "/companion/context/current_region",
            "Latency dropped by 60% after switching to Rust.",
        )

        await checker.on_context_change(
            PathChanged(
                path="/companion/context/current_region",
                value="Latency dropped by 60% after switching to Rust.",
            )
        )

        paths = await workspace.list("/companion/analysis/unsupported_claims/*")
        claim: UnsupportedClaim = await workspace.read(paths[0])
        assert "docs/perf.md" in claim.location

    async def test_claim_has_suggestions(self, workspace: InMemoryWorkspace, checker: ClaimChecker) -> None:
        await workspace.write("/companion/context/content_type", "markdown")
        await workspace.write("/companion/context/file_path", "docs/perf.md")
        await workspace.write(
            "/companion/context/current_region",
            "Benchmarks show a 3x speedup compared to the previous version.",
        )

        await checker.on_context_change(
            PathChanged(
                path="/companion/context/current_region",
                value="Benchmarks show a 3x speedup compared to the previous version.",
            )
        )

        paths = await workspace.list("/companion/analysis/unsupported_claims/*")
        claim: UnsupportedClaim = await workspace.read(paths[0])
        assert len(claim.suggestions) > 0


# -- Multiple claims --


class TestMultipleClaims:
    async def test_clears_old_claims_on_new_analysis(self, workspace: InMemoryWorkspace, checker: ClaimChecker) -> None:
        """New analysis should replace old claims."""
        await workspace.write("/companion/context/content_type", "markdown")
        await workspace.write("/companion/context/file_path", "docs/a.md")

        # First analysis
        await workspace.write(
            "/companion/context/current_region",
            "This is 10x faster than alternatives.",
        )
        await checker.on_context_change(
            PathChanged(
                path="/companion/context/current_region",
                value="This is 10x faster than alternatives.",
            )
        )
        first_count = len(await workspace.list("/companion/analysis/unsupported_claims/*"))
        assert first_count >= 1

        # Second analysis with neutral text
        await workspace.write(
            "/companion/context/current_region",
            "This module handles routing.",
        )
        await checker.on_context_change(
            PathChanged(
                path="/companion/context/current_region",
                value="This module handles routing.",
            )
        )
        second_count = len(await workspace.list("/companion/analysis/unsupported_claims/*"))
        assert second_count == 0


# -- Activation tracking --


class TestActivationTracking:
    async def test_records_activation(self, workspace: InMemoryWorkspace, checker: ClaimChecker) -> None:
        await workspace.write("/companion/context/content_type", "markdown")
        await workspace.write("/companion/context/file_path", "docs/a.md")
        await workspace.write(
            "/companion/context/current_region",
            "Studies prove this is the best approach.",
        )

        await checker.on_context_change(
            PathChanged(
                path="/companion/context/current_region",
                value="Studies prove this is the best approach.",
            )
        )

        assert len(checker.activations) >= 1
        last = checker.activations[-1]
        assert last.agent_name == "claim_checker"
        assert last.status == "success"
