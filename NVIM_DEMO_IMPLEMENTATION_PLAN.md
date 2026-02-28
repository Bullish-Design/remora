# Neovim & Web UI Demo Implementation Plan

## Executive Summary
This document outlines the MVP implementation for the Remora Agent Swarm Neovim plugin and its companion real-time Datastar Web UI. The goal is to quickly achieve a "wow" factor by demonstrating a live agent swarm that correlates to the Neovim editor's state and file structure. 

## Scope & Constraints (MVP)
*   **Web Server:** FastAPI with the `datastar_py` SDK.
*   **Web UI:** A real-time nested filesystem tree showing active agent state and logs, capable of expanding nodes to view detailed internal states, rather than a node graph.
*   **LLMs:** Real LLM integration using vLLM hosted at `remora-server:8000`.
*   **Neovim Plugin:** Focused strictly on tree-sitter based agent selection (cursor tracking) and displaying the sidepanel. Complex features like real-time multi-agent chat and immediate file saves will be pushed to Phase 2.
*   **Plugin Location:** Developed inside the `remora` root directory (`/lua/` and `/plugin/` folders) and loaded into the user's Neovim config as a local plugin.

---

## Architecture Overview

1.  **Remora Daemon (Python):** 
    *   Runs the `remora` core agent logic and orchestrates the swarm.
    *   Hosts a **FastAPI** application serving the Datastar Web UI.
    *   Hosts a **Unix Domain Socket** JSON-RPC server for the Neovim plugin to connect to.
    *   Sends real-time updates to Neovim (via RPC notifications) and the Web UI (via Datastar Server-Sent Events).
2.  **Web UI (HTML/JS + Datastar):**
    *   Displays an expandable filesystem tree.
    *   Receives HTML fragments from the FastAPI server to update agent states, logs, and triggers in real time.
3.  **Neovim Plugin (Lua):**
    *   Uses Neovim's `treesitter` to determine which AST node (agent) the cursor is currently on.
    *   Sends `agent.select` JSON-RPC messages to the Daemon.
    *   Displays the returned agent state in a dedicated vertical split (Sidepanel).

---

## Phase 1: Preparation & Scaffolding

### 1.1 Plugin Project Structure
Create the Neovim plugin directory structure within the `remora` repository:
```text
remora/
├── lua/
│   └── remora_nvim/
│       ├── init.lua
│       ├── bridge.lua       # JSON-RPC communication
│       ├── navigation.lua   # Treesitter cursor tracking
│       └── sidepanel.lua    # UI rendering for the vertical split
├── plugin/
│   └── remora_nvim.lua      # Plugin entrypoint / commands
```

### 1.2 Python Server Scaffolding
Set up the unified FastAPI server that will handle both the Web UI and the JSON-RPC local socket:
*   Create `src/remora/demo/nvim_server.py`.
*   Integrate `datastar_py` for SSE streaming.
*   Setup a background task or secondary loop to run the standard JSON-RPC socket server for Neovim alongside ASGI.

---

## Phase 2: The Datastar Web UI (The "Wow" Factor)

### 2.1 The Dashboard Layout
*   Serve an `index.html` featuring a two-pane layout (or flexible flexbox layout).
*   **Left Pane:** The AST / Filesystem Agent Tree.
*   **Right Pane / Overlay:** A live log of Swarm events across all agents.

### 2.2 Datastar Integration & SSE
*   Use `datastar_py`'s `sse` response generation to stream updates dynamically.
*   Whenever the `EventStore` receives a new event, broadcast a Datastar SSE event that replaces/updates the HTML fragment representing the specific Agent's node in the tree.
*   **Expandable Tree:** When a user clicks a node in the UI, it sends a Datastar event to the server to fetch and render the interior state (recent prompts, internal scratchpad, active goals) of that agent.

---

## Phase 3: The Neovim Plugin MVP

### 3.1 JSON-RPC Bridge (`bridge.lua`)
*   Implement a simple `vim.loop.new_pipe(false)` connection to the Remora Unix Socket.
*   Allow sending async JSON requests (`{"jsonrpc": "2.0", "method": "agent.select", "params": {"id": "..."}}`).

### 3.2 Treesitter Tracking (`navigation.lua`)
*   Bind to `CursorMoved` autocmd.
*   Use `vim.treesitter.get_node()` to ascend the syntax tree and find the nearest "agent-capable" construct (e.g., function definition, class, module).
*   Compute a determinist Agent ID (e.g., `file_path:line_number`).
*   Send an `agent.select` RPC call to the Daemon as the cursor moves across node boundaries.

### 3.3 The Sidepanel (`sidepanel.lua`)
*   Create an unlisted, unmodifiable vertically split buffer (`vsplit`).
*   When the JSON-RPC response returns the agent's state, format it nicely.
*   Show properties like: `Agent ID`, `Type`, `Status`, `Current Task`, and `Recent Triggers`.

---

## Phase 4: Integration & Real LLM Execution

### 4.1 Wiring to vLLM
*   Ensure the Remora daemon is configured to point its OpenAI compatible client at `http://remora-server:8000/v1`.
*   Set the model identifier string appropriately for the hosted vLLM instance.

### 4.2 Dummy Tasks & Live Validation
*   To prove the system works, write a script that submits a real task to the swarm. 
*   E.g., "Refactor all `datetime` imports to use absolute paths."
*   Watch the Web UI light up as different agents wake up, process the event, make their LLM calls, and go back to sleep.
*   Verify the cursor tracking in Neovim accurately syncs the sidepanel to the node being viewed.

---

## Next Steps (Phase 2 - Post MVP)
After the MVP is successful, the following features from the concept doc will be implemented:
1.  **In-Editor Chat:** Allowing the user to hit `<leader>rc` to open a chat buffer addressed to the currently selected agent.
2.  **Save-Triggers:** Adding the `BufWritePost` hook to emit `FileSaved` events directly from Neovim.
3.  **Inline Indicators:** Using Neovim `extmarks` to draw `[3]` indicators next to functions that were recently triggered.
