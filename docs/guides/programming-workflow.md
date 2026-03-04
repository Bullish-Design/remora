# Programming Workflow

> Using Remora as an AI-assisted coding environment in Neovim.

## Table of Contents

1. [Overview](#overview) -- What the coding experience looks like
2. [What You See in the Editor](#what-you-see-in-the-editor) -- Diagnostics, code actions, and the agent panel
3. [Keybindings Reference](#keybindings-reference) -- Default keymaps for all Remora actions
4. [Chatting with an Agent](#chatting-with-an-agent) -- Asking questions about code at your cursor
5. [Requesting a Rewrite](#requesting-a-rewrite) -- Telling an agent to change its code
6. [Reviewing Proposals](#reviewing-proposals) -- Accepting or rejecting agent rewrites
7. [The Agent Panel](#the-agent-panel) -- The side panel for deeper agent interaction
8. [The Reactive Cascade](#the-reactive-cascade) -- How edits trigger agent reactions automatically
9. [Web Graph Viewer](#web-graph-viewer) -- Visualizing your agent swarm
10. [Example Workflow](#example-workflow) -- End-to-end walkthrough of a typical session

---

## Overview

Remora turns every code node in your project -- every function, class, and file -- into an autonomous AI agent. When you open a Python, Markdown, or TOML file in Neovim with the Remora LSP running, each node is backed by an agent that knows its own source code, its relationships to other nodes, and its history of changes.

Your normal coding workflow stays intact. You edit code the way you always do. What Remora adds:

- **Diagnostics** appear when an agent has a pending rewrite proposal for you to review.
- **Code actions** let you accept or reject proposals directly from the lightbulb menu.
- **Keybindings** give you quick access to chat, rewrite requests, and the agent panel.
- **Reactive cascades** mean that when you change a function, agents watching that function (its callers, its class, its file) can notice and respond automatically.

You stay in control. Agents propose changes; you decide whether to apply them.

---

## What You See in the Editor

### Diagnostics

When an agent produces a rewrite proposal, Remora publishes an LSP **diagnostic** on the affected line range. You will see it as an informational hint (not an error or warning):

```
Agent proposes rewrite: Refactored to reduce duplication in loop body
```

The diagnostic includes the `proposal_id` and a unified diff in its data payload, so tools that display diagnostic details can show exactly what the agent wants to change.

### Code Actions

On any line inside a discovered node (function, class, file scope), Remora provides code actions. When a proposal is pending, two additional actions appear:

- **Accept rewrite** -- applies the agent's proposed changes to your buffer via a workspace edit.
- **Reject with feedback** -- prompts you for feedback text, which is sent back to the agent so it can learn from your rejection.

These appear in the standard code action menu (`:lua vim.lsp.buf.code_action()` or your preferred code action picker).

### Hover and Status

The agent panel (described below) shows the agent's current status:

| Status | Meaning |
|--------|---------|
| `active` | Agent is idle and ready |
| `running` | Agent is currently processing (LLM call in flight) |
| `pending_approval` | Agent has a proposal waiting for your review |
| `orphaned` | The code node was removed; agent is no longer backed by source |

---

## Keybindings Reference

All keybindings use a configurable prefix (default: `<leader>r`). You can change this in your Neovim config:

```lua
require("remora").setup({
    prefix = "<leader>r",  -- change to any prefix you like
})
```

| Keybinding | Command | Description |
|------------|---------|-------------|
| `<leader>ra` | `RemoraTogglePanel` | Toggle the agent panel sidebar |
| `<leader>rc` | `RemoraChat` | Chat with the agent at your cursor |
| `<leader>rr` | `RemoraRewrite` | Request a rewrite from the agent at your cursor |
| `<leader>ry` | `RemoraAccept` | Accept the pending proposal at your cursor |
| `<leader>rn` | `RemoraReject` | Reject the pending proposal (prompts for feedback) |

All commands work by resolving which agent owns the code at your cursor position. If no agent is found (e.g., you are on a blank line outside any function), you will see a warning: "No agent found at cursor."

---

## Chatting with an Agent

Press `<leader>rc` to start a conversation with the agent at your cursor. Remora resolves which code node your cursor is inside, finds the corresponding agent, and opens an input prompt.

Type your message and press Enter. The message is sent to the agent as a `HumanChatEvent`. The agent processes it through its LLM kernel and responds. If the agent panel is open, you will see the conversation appear in real time.

Example uses:

- **"What does this function do?"** -- The agent has its own source code in context and can explain it.
- **"What calls this function?"** -- If other agents have communicated with this one, it knows about its callers.
- **"Can you add error handling for the case where the input is None?"** -- The agent may respond with a rewrite proposal.

Chat is not just a one-shot interaction. The agent retains its event history, so follow-up messages have context from previous exchanges.

---

## Requesting a Rewrite

Press `<leader>rr` to ask the agent to rewrite its code. You will be prompted: **"What should this code do?"**

Describe the change you want. The agent will:

1. Read its current source code.
2. Process your instruction through its LLM kernel.
3. Produce a `RewriteProposal` with the old source, new source, and its reasoning.
4. Publish the proposal as an LSP diagnostic on the affected lines.

The rewrite does not happen automatically. You must explicitly accept it (see next section).

---

## Reviewing Proposals

When an agent produces a rewrite proposal, you have two options:

### Accept (`<leader>ry`)

Applies the proposal as a workspace edit. The agent's new source replaces the old source in your buffer. The proposal is marked as accepted in Remora's database, and a `RewriteAppliedEvent` is emitted -- which other agents can observe and react to.

### Reject (`<leader>rn`)

Opens a feedback prompt: **"Feedback for agent:"**

Type your reason for rejecting (e.g., "Don't rename the variable, just fix the off-by-one error"). The feedback is sent back to the agent as a `RewriteRejectedEvent`. The agent can use this feedback in future interactions -- it becomes part of the agent's event history.

### Using Code Actions

You can also accept/reject proposals through the code action menu instead of keybindings. When your cursor is on a line with a pending proposal, run `:lua vim.lsp.buf.code_action()` and you will see:

- `Accept rewrite`
- `Reject with feedback`

This is useful if you prefer a picker-based workflow or want to see the diagnostic detail before deciding.

---

## The Agent Panel

Press `<leader>ra` to toggle the agent panel. It opens as a vertical split on the right side of your editor (approximately 25% of the window width).

### Layout

The panel has two parts:

1. **Chat area** (top) -- Shows the agent header, tools list, and conversation history.
2. **Input area** (bottom) -- A small buffer where you type messages to the agent.

### Agent Header

Displays:
- Agent name (e.g., the function name)
- Node type (function, class, file)
- Current status with a colored icon
- Line range in the source file

### Tools Section

Shows the Grail tools available to the current agent. Collapsed by default; press `t` in the chat buffer to expand. Each tool shows its name and description.

### Chat History

Displays the full event stream for the current agent, including:

| Event | Display |
|-------|---------|
| Your messages | Blue "You" header with your text |
| Agent responses | Green "Agent" header with response text |
| Rewrite proposals | Yellow header with unified diff (added lines in green, removed in red) |
| Tool calls | Grey, compact, showing tool name and result summary |
| Inter-agent messages | Shows direction (from/to) with the other agent's name |
| Errors | Red error indicator |

### Cursor Tracking

The panel automatically updates as you move your cursor. When you move to a different function, the panel switches to show that function's agent (with a 300ms debounce to avoid flicker). This means you can navigate your code normally and the panel follows you.

### Panel Keymaps

| Key | Action |
|-----|--------|
| `q` | Close the panel |
| `t` | Toggle the tools section |
| `<CR>` | Send the message in the input buffer (works in both normal and insert mode) |

---

## The Reactive Cascade

The most powerful aspect of Remora's programming workflow is the **reactive cascade**. This is what makes Remora different from a simple chat interface.

### How It Works

1. **You edit code.** Save a file or let the LSP detect buffer changes.
2. **Reconciliation runs.** Remora re-parses the file with tree-sitter, compares the new AST nodes to the previous ones, and detects which nodes changed.
3. **Events are emitted.** Changed nodes get `NodeUpdatedEvent`s in the event store.
4. **Subscribed agents react.** Any agent that subscribes to events from the changed node wakes up and processes the change through its LLM kernel.
5. **Proposals may appear.** Reacting agents may produce their own rewrite proposals, diagnostics, or messages.

### Example Cascade

Suppose you have:

```python
def calculate_total(items):
    return sum(item.price for item in items)

def format_receipt(items):
    total = calculate_total(items)
    return f"Total: ${total:.2f}"
```

If you change `calculate_total` to also apply a tax:

```python
def calculate_total(items, tax_rate=0.0):
    subtotal = sum(item.price for item in items)
    return subtotal * (1 + tax_rate)
```

The agent for `format_receipt` may notice that `calculate_total`'s signature changed and propose an update:

```python
def format_receipt(items, tax_rate=0.0):
    total = calculate_total(items, tax_rate)
    return f"Total: ${total:.2f}"
```

You review and accept (or reject with feedback). The cascade can continue: if another function calls `format_receipt`, its agent may react to *that* change in turn.

### What Triggers Reconciliation

- **File save** -- The LSP server watches for `textDocument/didSave` notifications.
- **`swarm reconcile` command** -- Run manually from the CLI to force a full re-scan.
- **Swarm loop** -- When running `swarm start`, reconciliation happens on a configurable interval.

---

## Web Graph Viewer

Remora includes a web-based graph viewer that visualizes your agent swarm as an interactive node graph. Start it with:

```bash
remora serve
```

This opens a web interface (default: `http://localhost:8420`) showing:

- **Nodes** for each discovered agent (functions, classes, files)
- **Edges** representing relationships and event subscriptions between agents
- **Status colors** matching the same scheme used in the Neovim panel

### Cursor Sync

When running with Neovim, the graph viewer highlights the node at your cursor in real time. As you move through your code, the graph zooms to and highlights the corresponding agent. This is powered by the `$/remora/cursorMoved` notification that the Neovim plugin sends on `CursorHold`.

---

## Example Workflow

Here is a complete walkthrough of a typical Remora-assisted coding session.

### 1. Start the System

```bash
# Terminal 1: Start your LLM backend
vllm serve Qwen/Qwen3-8B \
    --tool-call-parser qwen3_xml \
    --enable-auto-tool-choice

# Terminal 2: Start Remora with Neovim LSP
remora swarm start --lsp
```

Open Neovim. The Remora LSP client starts automatically for Python, Markdown, and TOML files.

### 2. Explore Your Agents

Press `<leader>ra` to open the agent panel. Navigate to a function -- the panel shows that function's agent, its tools, and any prior event history.

### 3. Ask a Question

Place your cursor inside a function and press `<leader>rc`. Type:

```
What edge cases should I handle in this function?
```

The agent responds in the panel with analysis based on the function's source code.

### 4. Request a Change

Press `<leader>rr`. When prompted, type:

```
Add input validation -- raise ValueError if items is empty
```

After a moment, a diagnostic appears on the function indicating a rewrite proposal is ready.

### 5. Review and Accept

Press `<leader>ry` to accept the proposal. The function is updated in your buffer with the new validation code.

### 6. Watch the Cascade

If other functions depend on the one you just changed, their agents may react. Check the agent panel by navigating to a caller -- you might see it has already proposed an update to handle the new `ValueError`.

### 7. Continue Coding

Edit code normally. The agents work in the background, reacting to your changes and producing proposals when they have something useful to suggest. You stay in control of what gets applied.
