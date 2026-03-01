# Neovim Demo V2: Architecture & Concept

This document details the refined V2 architecture for the Remora Neovim integration. It expands upon the persistent node IDs and fundamentally rethinks how Neovim communicates with the Remora Swarm, utilizing the Language Server Protocol (LSP) and modern reactive UI libraries.

## 1. Extreme Detail: The LSP Integration Strategy

Instead of maintaining a custom JSON-RPC implementation over raw Unix sockets, the Remora Daemon should expose itself as a **Language Server**. Neovim inherently knows how to talk to LSPs, meaning we can offload 90% of the editor state tracking to Neovim's built-in LSP client.

### How it maps to LSP specs:

- **`initialize` / `initialized`:**
  Neovim connects to the Remora LSP server (running on a local TCP port or via standard input/output). The server parses the project and reconciles `# remora-id: xyz` annotations.

- **`textDocument/hover`:**
  When the user hovers (`K`) over a function name (or the `# remora-id` comment), Neovim sends a hover request.
  **Remora responds:** A markdown-formatted string showing the agent's current state, last run time, and active subscriptions. No custom Lua floating window needed for basic inspection; the native LSP hover window handles it.

- **`textDocument/codeAction`:**
  When a user brings up code actions (`<leader>ca`) on a node, Remora provides:
  - `Remora: Open Agent UI`
  - `Remora: Trigger Agent Walkthrough`
  - `Remora: Subscribe to changes`
  
- **`textDocument/publishDiagnostics`:**
  This is where the swarm becomes incredibly powerful. If a background agent (like a linter, tester, or reviewer agent) evaluates the file and finds an issue, the Remora LSP instantly pushes a diagnostic to Neovim. The user sees errors/warnings in the gutter and inline virtual text natively.

- **`workspace/executeCommand`:**
  For Remora-specific actions (like sending a chat message to an agent), Neovim sends a custom workspace command. The server processes the chat and triggers the swarm.

- **Background Synchronization:**
  By using standard `textDocument/didOpen`, `textDocument/didChange`, and `textDocument/didSave`, Remora always has the exact, up-to-date state of the code being edited without needing a custom `Buffer Sync` Lua module.

### Why this is a game-changer:
It allows Remora to feel like a native part of the developer toolchain. VSCode, Cursor, and Neovim all speak LSP. By building an LSP, you get cross-editor compatibility for free.

---

## 2. Next-Gen UI with `nui-components.nvim`

[nui-components.nvim](https://nui-components.grapp.dev/) is built on top of `nui.nvim` and provides a React-like component model, Flexbox layouts, and a Signal-based reactivity system completely independent of Neovim's standard buffer APIs. This makes it the *perfect* tool for building the Remora Swarm sidepanel.

### Conceptualizing the UI

**1. The Collapsible Sidebar:**
Using the Flexbox engine, the UI can be structured to have multiple states:
- **Collapsed (Narrow Mode):** A 3-4 column wide vertical strip on the far right. It uses a `Tree` or vertically stacked `Text` components to show single character icons (e.g., `[D]` dormant, `[A]` active, `[!]` triggered).
- **Expanded (Chat/Info Mode):** When a user executes the Code Action to "Open Agent UI", the Flexbox layout smoothly expands to 40 columns wide, revealing tabs for `State`, `Subscriptions`, and an `Input` component for Chat.

**2. Reactivity with Signals (The "Grail Trigger"):**
`nui-components` uses a `Signal` API for state. 
- The Neovim plugin subscribes to the Remora HTTP SSE `/stream-events` endpoint in the background.
- When an event arrives (e.g., `ModelResponseEvent` marked with a "grail_trigger" tag), the Lua client updates a local signal: `signal.agent_status = "grail_triggered"`.
- Because the component tree is bound to that signal, it instantly re-renders. We can bind the **highlight group** of the window border or the text component directly to this signal. 

**Example Flow for a Grail Trigger:**
1. Background Agent completes a massive refactor (Grail event).
2. SSE pushes event to Neovim.
3. Lua client parses event, updates `nui-components` Signal object.
4. The narrow sidebar instantly changes its border color from standard `#444444` grey to a pulsing `#FFD700` (Gold) or `#8A2BE2` (Purple).
5. The user notices the color change, clicks the Code Action (or hits a keybind), expanding the sidebar to see the agent's output.

### Synergy: LSP + Nui-Components
The two technologies work in perfect harmony:
- **LSP** handles the heavy lifting of code synchronization, background diagnostics, and lightweight hover states.
- **Nui-Components** handles the heavy, application-like workflow: chatting with the agent, rendering complex subscription trees, and providing a visually stunning, reactive interface that responds to swarm activity via SSE.
- **Node IDs** provide the stable anchor linking the hovering cursor in the LSP to the specific agent state rendered in the Nui Component.
