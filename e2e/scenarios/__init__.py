"""E2E scenarios package — collects all scenario implementations."""

from __future__ import annotations

from e2e.scenarios.startup import StartupScenario
from e2e.scenarios.chat import ChatScenario
from e2e.scenarios.rewrite import RewriteScenario
from e2e.scenarios.proposal import ProposalScenario
from e2e.scenarios.cascade import CascadeScenario
from e2e.scenarios.golden_path import GoldenPathScenario

ALL_SCENARIOS: dict[str, type] = {
    "startup": StartupScenario,
    "chat": ChatScenario,
    "rewrite": RewriteScenario,
    "proposal": ProposalScenario,
    "cascade": CascadeScenario,
    "golden_path": GoldenPathScenario,
}

__all__ = [
    "ALL_SCENARIOS",
    "StartupScenario",
    "ChatScenario",
    "RewriteScenario",
    "ProposalScenario",
    "CascadeScenario",
    "GoldenPathScenario",
]
