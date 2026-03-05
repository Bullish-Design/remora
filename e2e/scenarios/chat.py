"""Chat scenario — Chat with an agent.

Opens nv2 on the demo project, positions cursor on `load_config`,
sends a chat message via <leader>rc, verifies the chat panel opened,
then opens the Remora panel via <leader>ra and navigates into it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"
LOG_DIR = DEMO_PROJECT / ".remora" / "logs"

REQUIRED_SERVER_MARKERS = (
    "cmd_chat: requestInput sent",
    "on_input_submitted: params=",
    "execute_turn: START",
)


def _wait_for_server_markers(
    markers: tuple[str, ...],
    *,
    timeout: float = 15.0,
    poll: float = 0.25,
) -> tuple[Path, str]:
    """Wait until the latest server log includes all required markers."""
    deadline = time.monotonic() + timeout
    latest_log: Path | None = None
    latest_content = ""

    while time.monotonic() < deadline:
        logs = sorted(LOG_DIR.glob("server-*.log"), key=lambda path: path.stat().st_mtime)
        if logs:
            latest_log = logs[-1]
            latest_content = latest_log.read_text(encoding="utf-8", errors="replace")
            if all(marker in latest_content for marker in markers):
                return latest_log, latest_content
        time.sleep(poll)

    missing = [marker for marker in markers if marker not in latest_content]
    target = str(latest_log) if latest_log else f"{LOG_DIR}/server-*.log"
    raise AssertionError(
        f"Missing server marker(s) {missing} in latest log {target}.\n"
        f"This run did not submit chat deterministically."
    )


@dataclass
class ChatScenario:
    """Chat with an agent scenario."""

    name: str = "chat"
    description: str = "Chat with load_config agent, verify response in panel"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"

        # Launch nv2 on loader.py and wait for LSP
        nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Position cursor on load_config (line 13 in loader.py)
        nv.goto_line(13)

        # --- Test 1: Direct chat via <leader>rc ---
        nv.leader_chat()
        nv.submit_chat_message(
            "what do you do?",
            prompt_text="Message to agent:",
            prompt_timeout=20.0,
        )

        # Wait for the response to arrive (pane should stabilize)
        driver.wait_for_stable(stable_seconds=3.0, timeout=30)

        # Confirm server-side submit path ran end-to-end.
        _wait_for_server_markers(REQUIRED_SERVER_MARKERS, timeout=20.0)

        # --- Test 2: Open and verify agent panel after submit ---
        nv.leader_panel()
        nv.focus_right(delay=1.0)

        # Wait for panel to render
        content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)

        # Assert panel still shows agent info and message history state
        assert "load_config" in content, f"Expected 'load_config' in panel, got:\n{content}"
        assert "No messages yet." not in content, f"Expected chat history after submit, got:\n{content}"
