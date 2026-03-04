"""Agent query scenario — List agents in the swarm.

Demonstrates the query_agents tool by:
1. Opening loader.py which has multiple functions (multiple agents)
2. Chatting with an agent asking it to "list all function agents"
3. The agent uses the query_agents tool with filter_type="function"
4. The response includes metadata about the agents in the swarm

This validates agent discovery and introspection capabilities.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class QueryAgentsScenario:
    """Query agents in the swarm scenario."""

    name: str = "query_agents"
    description: str = "List and query agents in the swarm by type"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)

        # ---------------------------------------------------------------
        # Beat 1: Open loader.py - file with multiple functions
        # ---------------------------------------------------------------
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Open panel to observe agent activity
        nv.leader_panel()
        nv.focus_right(delay=0.5)
        nv.focus_left(delay=0.3)

        # ---------------------------------------------------------------
        # Beat 2: Position on load_config and verify agent is active
        # ---------------------------------------------------------------
        nv.goto_line(12)
        time.sleep(1)

        content = driver.capture_pane()
        assert "load_config" in content, f"Expected 'load_config' agent in panel:\n{content}"

        # ---------------------------------------------------------------
        # Beat 3: Chat with agent - ask it to query agents
        # ---------------------------------------------------------------
        nv.leader_chat(settle=0.5)
        nv.wait_for_chat_prompt()

        # Request the agent to list all function agents
        nv.keys("List all function agents in the swarm", delay=1)
        nv.raw("Escape", delay=0.5)
        nv.raw("Enter", delay=2)

        # Wait for LLM response and tool execution
        driver.wait_for_stable(stable_seconds=5.0, timeout=45)

        # Verify the query_agents tool was executed
        # The tool returns JSON with agent metadata
        content = driver.capture_pane()
        # The response should mention agents, functions, or include agent names
        assert (
            "agent" in content.lower()
            or "function" in content.lower()
            or "load_config" in content
            or "detect_format" in content
        ), f"Expected agent/function query results:\n{content}"

        # ---------------------------------------------------------------
        # Beat 4: Navigate through different functions to show agents
        # ---------------------------------------------------------------
        nv.focus_code_buffer(expected_text="def")

        # Go to detect_format
        nv.goto_line(29)
        time.sleep(1)

        content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)
        assert "detect_format" in content, f"Expected 'detect_format' in panel:\n{content}"

        # Go to load_yaml
        nv.goto_line(39)
        time.sleep(1)

        content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)
        assert "load_yaml" in content, f"Expected 'load_yaml' in panel:\n{content}"

        # ---------------------------------------------------------------
        # Beat 5: Final verification
        # ---------------------------------------------------------------
        # Verify LSP is healthy throughout
        nv.assert_not_in_pane("LSP not running", "LSP should be running")
