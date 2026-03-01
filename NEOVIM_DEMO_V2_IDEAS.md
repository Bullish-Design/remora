# Neovim Demo V2: Conceptual Brainstorming

The current Remora AST Swarm concept proposes that *every* syntactic element (function, class, file) is an agent. While theoretically profound, it runs into severe practical bottlenecks: workspace bloat, line-number hash fragility, and massive initialization overhead. 

Here are ideas and conceptual simplifications, heavily utilizing your idea of persistent Node IDs, to build "V2" of the Neovim Demo.

---

## 1. Persistent Node IDs (The "Anchor" Concept)

**The Idea:**
Instead of dynamically deriving an agent ID from fragile metadata like line numbers, we inject a unique hash directly into the source code as a comment (e.g., `# remora-id: 8f3a9b`). 

**How it works seamlessly:**
1. **First Parse:** Treesitter finds a function without an ID comment.
2. **Generation:** Remora creates a new Agent, generates ID `abc123`, and *modifies the source file* appending `# remora-id: xyz` right-aligned at the top/end of the node's block.
3. **Neovim `conceal`:** To prevent polluting the user's view, the Lua plugin uses Neovim's built-in `conceal` syntax or `extmarks`. 
   ```vim
   " Hides the ID comment entirely from the buffer 
   syntax match RemoraIdComment "\s*# remora-id: [a-zA-Z0-9_-]\+" conceal
   set conceallevel=2
   ```
   *Alternative:* Use virtual text to style it faintly against the background.

**Benefits:**
- **Zero Workspace Bloat:** Moving a function down 10 lines doesn't change the ID. No exponentially growing orphaned workspaces across sessions.
- **Concrete Graph Edges:** Because IDs never unexpectedly rotate, we can finally build actual graph operations (tracking caller/callee relationships, imports) robustly in `workspace.db`.

---

## 2. Lazy "Agentification" (Opt-in Swarms)

**The Problem:**
If a user opens a 10,000-line single-file Python script, the current architecture immediately provisions hundreds of full agent configurations, SQLite rows, and default subscriptions.

**The Fix:**
Agents should be **virtual and stateless** by default.
1. When a file is opened, Remora parses the AST and simply updates an in-memory or lightweight metadata index of what nodes exist. It does *not* create full agent states.
2. An agent is strictly "instantiated" (workspace created, subscriptions wired) only when:
   - The user opens the chat panel for that function.
   - The user explicitly flags it: `[t]rigger`.
   - Another agent specifically targets it.
   
This transforms the IDE from a "Heavy Daemon" into an "On-Demand Swarm."

---

## 3. The Protocol Shift: From Sockets to HTTP/SSE

**The Problem:**
Maintaining a custom JSON-RPC protocol over Unix Sockets presents cross-platform woes (especially on Windows) and requires tedious retry logic.

**The Fix:**
FastAPI is already running. The dashboard uses Server-Sent Events (SSE). **Neovim should just use HTTP and SSE.**
- **Requests:** Neovim's `plenary.curl` handles standard POST/GET to `http://127.0.0.1:8080/api/agent/...` for triggering tasks or chatting.
- **Push Notifications:** Neovim runs a background curl job attached to the `/stream-events` SSE endpoint to receive live updates, which are intercepted by Lua and update the sidepanel. 
- *Why?* This eliminates `src/remora/nvim/server.py` and the raw socket completely, unifying the Web UI and the Neovim UI onto the exact same HTTP API.

---

## 4. The LSP Disguise

**The Concept:**
Neovim is an inherently powerful LSP client. Instead of inventing custom Lua sidepanels and keybinds (`<leader>rc`), Remora's daemon could talk the standard **Language Server Protocol**.
- Hovering (`K`) over a function could request `textDocument/hover`, to which Remora returns the Agent's current Status, Subscriptions, and last Triggers as Markdown.
- Code Actions (`<leader>ca`) could expose "Remora: Chat with this node" or "Remora: Trigger Agent".
- Diagnostics could expose the Agent's internal warnings or linter suggestions natively in the gutter.

**Benefit:**
This radically reduces the amount of Lua code you need to maintain for the plugin. Most LSP integration behavior is native to Neovim.

---

## 5. File-Level vs Structure-Level Agents

**A mental model rethink:**
Do we really need the `format_date` function to be an autonomous decision-making agent? 
If you simplify conceptually:
- The **File** is the Agent. (`dates.py` is the agent)
- The **Functions/Classes** are just specific contexts (or "Tools") the File Agent can route between.
- The Persistent Node ID acts as a "Bookmark" for the file agent to attach sub-context to.

This significantly flattens the swarm hierarchy, making it easier for human developers to follow the trace, while still keeping the semantic "navigating code is navigating agents" feel.
