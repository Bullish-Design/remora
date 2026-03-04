"""E2E scenarios package — collects all scenario implementations."""

from __future__ import annotations

from e2e.scenarios.startup import StartupScenario
from e2e.scenarios.chat import ChatScenario
from e2e.scenarios.rewrite import RewriteScenario
from e2e.scenarios.proposal import ProposalScenario
from e2e.scenarios.cascade import CascadeScenario
from e2e.scenarios.golden_path import GoldenPathScenario
from e2e.scenarios.reject import RejectScenario
from e2e.scenarios.multi_file import MultiFileScenario
from e2e.scenarios.panel_nav import PanelNavScenario
from e2e.scenarios.ext_discovery import ExtDiscoveryScenario
from e2e.scenarios.ext_multi_file import ExtMultiFileScenario
from e2e.scenarios.ext_edit_cascade import ExtEditCascadeScenario

# Agent-agent communication scenarios
from e2e.scenarios.agent_message import AgentMessageScenario
from e2e.scenarios.agent_broadcast import AgentBroadcastScenario
from e2e.scenarios.agent_subscribe import AgentSubscriptionScenario
from e2e.scenarios.swarm_monitor import SwarmMonitorScenario
from e2e.scenarios.query_agents import QueryAgentsScenario

# Companion demo scenarios
from e2e.scenarios.companion_sidebar import CompanionSidebarScenario
from e2e.scenarios.companion_connections import CompanionConnectionsScenario
from e2e.scenarios.companion_pipeline import CompanionPipelineScenario

ALL_SCENARIOS: dict[str, type] = {
    "startup": StartupScenario,
    "chat": ChatScenario,
    "rewrite": RewriteScenario,
    "proposal": ProposalScenario,
    "cascade": CascadeScenario,
    "golden_path": GoldenPathScenario,
    "reject": RejectScenario,
    "multi_file": MultiFileScenario,
    "panel_nav": PanelNavScenario,
    "ext_discovery": ExtDiscoveryScenario,
    "ext_multi_file": ExtMultiFileScenario,
    "ext_edit_cascade": ExtEditCascadeScenario,
    # Agent-agent communication
    "agent_message": AgentMessageScenario,
    "agent_broadcast": AgentBroadcastScenario,
    "agent_subscribe": AgentSubscriptionScenario,
    "swarm_monitor": SwarmMonitorScenario,
    "query_agents": QueryAgentsScenario,
    # Companion demo
    "companion_sidebar": CompanionSidebarScenario,
    "companion_connections": CompanionConnectionsScenario,
    "companion_pipeline": CompanionPipelineScenario,
}

__all__ = [
    "ALL_SCENARIOS",
    "StartupScenario",
    "ChatScenario",
    "RewriteScenario",
    "ProposalScenario",
    "CascadeScenario",
    "GoldenPathScenario",
    "RejectScenario",
    "MultiFileScenario",
    "PanelNavScenario",
    "ExtDiscoveryScenario",
    "ExtMultiFileScenario",
    "ExtEditCascadeScenario",
    # Agent-agent communication
    "AgentMessageScenario",
    "AgentBroadcastScenario",
    "AgentSubscriptionScenario",
    "SwarmMonitorScenario",
    "QueryAgentsScenario",
    # Companion demo
    "CompanionSidebarScenario",
    "CompanionConnectionsScenario",
    "CompanionPipelineScenario",
]
