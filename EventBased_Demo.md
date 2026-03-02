# EventBased Demo: Brainstorming Document

> **Purpose:** Explore what the demos need to accomplish, what exists already, where the gaps are, and brainstorm creative approaches for demonstrating the EventBased architecture to a single person running locally.

---

## 1. What Are We Demoing?

The EventBased architecture has one core thesis: **the EventLog is the single source of truth, and everything else is a projection**. Agents don't exist as processes or objects — they exist as patterns in the event stream. The swarm isn't orchestrated — it emerges from subscriptions.

A demo needs to make this *visible*. The challenge is that most of the architecture's power is invisible by design — events flow, projections update, subscriptions trigger. There's no "main loop" to watch. The demo has to surface the invisible.

### What Must Be Felt

1. **Reactivity** — Save a file, see agents wake up. Not "press a button to run." The swarm reacts.
2. **Emergence** — Agents trigger other agents. A single edit cascades into a chain of autonomous activity. The developer didn't orchestrate this.
3. **Visibility** — The EventLog should be observable in real-time. You should *see* events flowing, subscriptions matching, agents activating.
4. **Agency** — Individual agents have identity, memory, tools. You can talk to a specific function. It knows its own source code, its callers, its callees.
5. **The Graph** — The swarm has structure. Files contain classes contain methods. Functions call functions. This graph is alive — nodes glow when active, edges pulse when messages flow.

### What Must Be Understood

1. **EventLog as source of truth** — Everything that happens is an event. The nodes table, the graph, the agent status — all derived.
2. **Subscriptions drive reactivity** — No polling, no orchestration. Agents declare what they care about. The system matches.
3. **AgentNode is data, not code** — Same Pydantic model, same table, same methods. A test function agent and a route handler agent differ in *field values*, not in *class hierarchy*.
4. **Extensions specialize via data** — `.remora/models/` configs turn generic function agents into test runners, API route guards, config validators — by injecting system prompts, tools, and subscriptions.
5. **LSP is the spine** — Neovim connects via standard protocol. Code lenses, hover, code actions — all driven by `AgentNode.to_*()` methods reading from the projected `nodes` table.

---

## 2. What Exists Already

### V1 Demos (archived in `.v1/`)

**What they accomplished:**
- `api_demo.py`: Proved fire-and-forget HTTP execution with SSE event streaming works. Showed that you can trigger graph execution from a web client and watch events arrive in real-time.
- `component_demo/app.py`: Built a full Starlette + Datastar web UI with Dashboard, Component Lab, Tool Call Observatory, and Playback Studio. Proved the UI component system works (Card, Grid, Button, etc.) and that Datastar SSE morphing can drive real-time updates.
- `one_stop_shop/run_demo.py`: Proved the full pipeline end-to-end: Meridian app -> Remora discovery -> graph build -> GraphExecutor with real vLLM -> Cairn workspace inspection -> JSONL event logging.

**Their limitations:**
- All used the old HTTP Hub architecture — a centralized server orchestrating agent execution. This is the opposite of the EventBased vision.
- The component demo's web UI was beautiful but disconnected from the editor. It was a standalone dashboard, not a companion to Neovim.
- The one-stop-shop was a batch pipeline, not reactive. Run it, wait, see results. No interactivity.
- None demonstrated subscriptions, reactive cascading, or the EventLog as source of truth.

### V2 Demo (current, LSP-based)

**What it accomplishes:**
- Full LSP integration with Neovim via pygls stdio.
- Tree-sitter AST watching with ID injection (`rm_a1b2c3d4` comments).
- Code lenses showing agent status inline above functions/classes.
- Hover cards showing agent details (ID, type, status, graph context).
- Code actions menu (Chat, Rewrite, Message).
- Nui-based side panel with: agent header, collapsible tools, chat history with per-event-type rendering, input buffer, debounced cursor-driven refresh.
- AgentRunner with trigger queue, activation chain (depth=10, cycle detection), LLM tool loop (5 rounds max), tool handlers (rewrite_self, message_node, read_node).
- Extension loading from `.remora/models/`.
- MockLLMClient for demo without real vLLM.
- LazyGraph using rustworkx for on-demand neighborhood loading.
- Proposal system: agents propose rewrites -> diagnostics with diff -> human approve/reject.

**Its limitations:**
- Uses its own `ASTAgentNode` + `RemoraDB` instead of the core `AgentNode` + `EventStore`. Two parallel node lifecycles exist.
- No web graph viewer — the graph is invisible. You can only see one agent at a time (the one at cursor).
- No reactive cascading visible. The activation chain works internally but the user can't see the ripple effect across the codebase.
- The Nui panel shows events for one agent. There's no swarm-wide event stream view.
- Cursor tracking writes to `cursor_focus` table but nothing reads it (no graph viewer yet).
- No demonstration of subscriptions or subscription matching.

### Phase 1 Core (implemented)

**What exists:**
- `AgentNode` Pydantic model with `from_row()`, `to_row()`, `to_system_prompt()`, `to_code_lens()`, `to_hover()`, `to_code_actions()`, `to_document_symbol()`.
- `ToolSchema` dataclass with `to_llm_tool()` and `to_code_action()`.
- `AgentExtension` base class + mtime-cached loader from `.remora/models/`.
- `EventStore` with `events` + `nodes` tables, WAL mode, async append.
- `NodeProjection` that processes `NodeDiscoveredEvent`, `NodeRemovedEvent`, `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent` -> updates `nodes` table.
- Full event hierarchy: lifecycle events, human-in-loop events, reactive events, kernel events, node lifecycle events.
- `SubscriptionPattern` with 5-dimensional matching (event_types, from_agents, to_agent, path_glob, tags).
- 120 tests passing across unit + integration.

**What's missing from Phase 1:**
- Reconciler (detects removed/moved nodes).
- Agent runner rewrite (to use EventStore instead of RemoraDB).
- Swarm executor rewrite.
- LSP handler migration (the Option A plan in `.scratch/option-a-plan.md`).
- Subscription registry + matching engine.

### Graph Viewer Designs (documented but not built)

Two design docs exist:
- `docs/plans/2026-03-01-web-graph-view-design.md` — V1 scope: hierarchical tree layout, Datastar SSE, server-computed layout, read-only.
- `docs/plans/2026-03-01-graph-viewer-v2-design.md` — V2 scope: d3-force layout, SVG rendering, bidirectional interaction via `command_queue` table, agent chat from web UI.

Neither has been implemented. The v2 design is more aligned with the EventBased vision (d3-force, interactive, command queue for web->LSP communication).

---

## 3. Gap Analysis: Vision vs. Reality

### The EventBased_Concept.md envisions:

| Capability | Concept Doc Section | Current State |
|---|---|---|
| EventLog as single source of truth | Section 1.1-1.3 | EventStore exists but LSP still uses RemoraDB in parallel |
| SubscriptionPattern 5-dim matching | Section 1.4 | Data model exists, no matching engine |
| NodeDiscoveredEvent -> projection -> nodes table | Section 1.5-1.6 | Works in core, not wired to LSP watcher |
| AgentNode unified model (DB/prompt/LSP) | Section 1.7 | Model exists with all conversions, LSP still uses ASTAgentNode |
| Extensions via data fields | Section 3 | Core AgentExtension exists, LSP still uses ExtensionNode |
| Agent communication (direct/broadcast/implicit) | Section 4 | message_node tool exists in runner, no broadcast, no implicit observation |
| Reactive cascading (save file -> chain of agents) | Section 5 | Activation chain works but driven by internal queue, not EventLog subscriptions |
| Web graph viewer (d3 force-directed) | Section 2 | Design docs exist, nothing built |
| Cursor tracking -> graph highlight | Section 7 | CursorHold -> cursor_focus table works, nothing reads it |
| LSP code lens/hover/actions from AgentNode | Section 7 | AgentNode has methods, LSP handlers still use ASTAgentNode |

### The Gap Summary

The core primitives exist (EventStore, AgentNode, events, projections) but the LSP layer hasn't been migrated. And the most visually impressive piece — the graph viewer — hasn't been built at all. The demo has two jobs:

1. **Complete the migration** enough that the EventLog is actually driving the system (not just recording to it as a sidecar).
2. **Build the graph viewer** so the EventLog's activity is visible.

---

## 4. Brainstorming: Demo Scenarios

### Scenario A: "The Awakening"

**Setup:** Open a Python project in Neovim. The project has 5-10 files with functions, classes, tests. Extension configs in `.remora/models/` specialize test functions and maybe an API route.

**Flow:**
1. Open a file. Tree-sitter discovers functions. Code lenses appear above each one (idle status).
2. Graph viewer (browser tab) shows nodes appearing in real-time as files are opened. Force-directed layout settles.
3. Edit a function and save. A `ContentChangedEvent` flows through the EventLog.
4. The function's agent activates (code lens changes to "running"). It examines its own diff.
5. The agent notices the function's return type changed. It calls `message_node` to notify a test function.
6. The test agent activates. Chain visible in the graph viewer — edges pulse.
7. The test agent proposes a rewrite to update the test assertion. Diagnostic appears in Neovim.
8. The developer reviews the proposal in the panel, approves it. `workspace/applyEdit` applies the change.

**What this demonstrates:** Reactivity, cascading, agency, proposals, the graph as a living organism.

### Scenario B: "The Inspector"

**Setup:** Same project. Focus on demonstrating the EventLog and subscriptions.

**Flow:**
1. Open the graph viewer. Click on a node. Sidebar shows: agent identity, extension config, active subscriptions, recent events.
2. In Neovim, hover over a function. Hover card shows the same information — agent ID, status, graph context, recent events.
3. Chat with an agent via `:RemoraChat`. Ask it "what do you do?" It responds based on its system prompt (generated from AgentNode fields).
4. Watch the EventLog panel in the graph viewer — every message, every model request/response is a visible event.
5. Open a subscription inspector view — show which agents are subscribed to what, and when a new event arrives, which subscriptions match.

**What this demonstrates:** The EventLog as the single source of truth, subscription matching, the AgentNode as the bridge between all views.

### Scenario C: "The Scaffold"

**Setup:** Inspired by Section 6 (Perspective 5) of the concept doc. Empty-ish project with a SPEC.md.

**Flow:**
1. Developer writes a spec in `src/SPEC.md`.
2. Scaffold agent reads the spec and creates file stubs.
3. Interface agent defines type signatures.
4. Implementation agent fills in function bodies.
5. Test agent generates tests.
6. Validation agent runs tests.
7. Each step visible as a cascade in the graph viewer. New nodes appear as files are created. Agents chain automatically via subscriptions.

**What this demonstrates:** The full power of subscription-driven cascading. But this is the hardest to demo because it requires working LLM integration and multiple bundle configs.

### Scenario D: "The Minimum Viable Magic"

**Setup:** Smallest possible demo that still shows the architecture's power.

**Flow:**
1. Single Python file with 3 functions. One calls the other two.
2. Open in Neovim. Three agents appear. Graph viewer shows the triangle.
3. Edit the "leaf" function. Its agent activates and examines the change.
4. The agent sends a message to its caller. The caller agent activates.
5. Two-step cascade visible in graph viewer. Events visible in panel.
6. Developer chats with the caller agent about the change.

**What this demonstrates:** Core reactivity in the simplest possible context. This is the realistic MVP demo.

---

## 5. Brainstorming: The Graph Viewer

### Approach 1: Pure Datastar SSE (Server-Rendered Everything)

As described in `2026-03-01-web-graph-view-design.md`. Server computes layout, renders HTML divs for nodes, streams via SSE. Browser just morphs DOM.

**Pros:** Zero client-side JS framework. Consistent with Datastar philosophy. Layout is deterministic and reproducible.
**Cons:** No smooth animation. Node positions jump on re-layout. Doesn't feel alive. Hierarchical tree looks like a file browser, not a living swarm.

### Approach 2: D3-Force Client-Side (Hybrid Datastar)

As described in `2026-03-01-graph-viewer-v2-design.md`. Server sends graph data as JSON signals. Client runs d3-force simulation and renders SVG.

**Pros:** Smooth physics-based animation. Nodes drift and settle. Feels alive. D3-force is battle-tested.
**Cons:** Hybrid model — Datastar for sidebar/event stream, custom JS for the graph. Two rendering paradigms. More client code.

### Approach 3: Terminal-Based Graph (No Browser)

Use a terminal UI (textual, rich, or even raw ANSI) to render the graph in a terminal split alongside Neovim.

**Pros:** No browser needed. Everything in the terminal. Fits the "one person, locally" requirement perfectly. Looks hacker-cool.
**Cons:** Terminal graph rendering is primitive. Can't do force-directed layout well. Text-mode nodes look ugly at scale. Limited interactivity.

### Approach 4: Neovim-Native Graph (Nui Buffer)

Render the graph inside Neovim itself using a special buffer with virtual text, extmarks, and Nui components.

**Pros:** Single application. No context switching. Deepest integration possible.
**Cons:** Neovim's rendering model is line-based. Graphs need 2D positioning. Would require ASCII art or heavy hackery. Doesn't scale past ~20 nodes.

### Approach 5: Lightweight HTML + WebSocket (No Framework)

Skip Datastar entirely. Serve a single HTML page with inline `<script>`. Open a WebSocket to the server. Server pushes events as JSON. Client renders with vanilla JS + SVG.

**Pros:** Maximum simplicity. One HTML file. No build step. No framework. Direct mapping from EventLog events to visual updates.
**Cons:** Loses consistency with existing Datastar infrastructure. More client-side code to write. No HTML fragment streaming.

### Recommended: Approach 2 (D3-Force Hybrid) with simplification

The d3-force approach is the best fit because:
1. It makes the graph feel **alive** — nodes drift, settle, repel, attract. This directly embodies the "living swarm" concept.
2. The physics simulation provides **implicit animation** — when a new node appears or an edge is added, the simulation adjusts naturally. No animation code needed.
3. D3-force is loaded from CDN — **zero build step**. One `<script src="...">` tag.
4. The **sidebar can still be Datastar SSE** — HTML fragments for agent details, event stream, subscription inspector. Best of both worlds.
5. For a local demo, performance is not a concern. 50-100 nodes with d3-force is trivial.

Simplification from the v2 design doc:
- Skip the full Datastar signal pipeline for graph data. Just use SSE `event: graph` with JSON payloads. Client JS updates d3-force directly.
- Sidebar HTML fragments via Datastar SSE `patch_elements` as planned.
- Command queue for web -> LSP interaction (chat, approve proposal, trigger agent).

---

## 6. Brainstorming: The Bridge (Neovim <-> Graph Viewer)

The most compelling part of the demo is when Neovim and the graph viewer are side by side and they're clearly connected — the same EventLog driving both views.

### Cursor Tracking (Neovim -> Graph)

Already designed and partially implemented:
1. Neovim `CursorHold` fires.
2. `$/remora/cursorMoved` notification sent to LSP server.
3. LSP handler resolves agent_id from position, writes to `cursor_focus` table.
4. Graph viewer SSE detects `cursor_focus` change, highlights the node.

**Visual:** The node under the cursor glows/pulses in the graph. As you navigate code, the graph follows you. This is the "zoom to cursor" effect — the graph viewport pans to keep the focused node centered.

### Agent Activation (Visible in Both)

When an agent activates:
1. Code lens in Neovim changes from idle icon to running icon.
2. Graph viewer node changes color/animation (pulsing glow).
3. When the agent completes, both revert.
4. If the agent produces a proposal, Neovim shows a diagnostic; graph viewer shows the proposal in the sidebar.

### Web -> Neovim (Graph -> Editor)

Via the `command_queue` table:
1. Click a node in the graph viewer -> write `{"command": "focus", "agent_id": "..."}` to command_queue.
2. LSP server polls command_queue, sends `$/remora/agentSelected` notification to Neovim.
3. Neovim jumps to the agent's source location.

Or for chat:
1. Type a message in the graph viewer sidebar input.
2. Write `{"command": "chat", "agent_id": "...", "message": "..."}` to command_queue.
3. LSP server processes it exactly like a `$/remora/submitInput` notification.
4. Response appears in both the Neovim panel and the graph viewer sidebar.

### Event Stream (Shared)

Both the Neovim panel and the graph viewer sidebar show the same events, because they both read from the same EventLog. The Neovim panel shows events for the focused agent. The graph viewer can show the global event stream, or filter to the selected agent.

---

## 7. Brainstorming: Mock LLM Strategy

For a local demo, we need the LLM to behave convincingly without requiring a real vLLM instance (or at minimum, making it optional).

### Option 1: Enhanced MockLLMClient (Scripted Responses)

The current `MockLLMClient` exists in `tests/fixtures/mock_llm.py`. Extend it to handle specific demo scenarios:

- If the trigger is a `ContentChangedEvent` and the agent is a function: respond with analysis of the diff + optionally call `message_node` to notify callers.
- If the trigger is an `AgentMessageEvent`: respond with acknowledgment + optionally propose a rewrite.
- If the trigger is a `HumanChatEvent`: respond with a description of the agent's role based on its system prompt.

**Pros:** Deterministic, reproducible, instant. No hardware requirements.
**Cons:** Feels scripted. Can't handle unexpected inputs. Limited to pre-programmed scenarios.

### Option 2: Small Local Model (Qwen3-0.6B or similar)

Run a tiny model via vLLM or llama.cpp. Small enough to run on CPU.

**Pros:** Real LLM responses. Handles any input. Genuinely autonomous behavior.
**Cons:** Slow on CPU (seconds per response). Requires model download. Small models produce mediocre code analysis. Adds setup complexity.

### Option 3: Hybrid (Mock with LLM Fallback)

Use the mock for the scripted demo flow. If a real vLLM endpoint is available (env var or config), use it instead. The demo works either way but is more impressive with a real model.

**Recommended:** Option 3. The mock makes the demo reliable and reproducible. The real LLM makes it impressive when available. The `__main__.py` entry point already injects the LLM client — just make it check for `REMORA_LLM_URL` env var.

---

## 8. Brainstorming: Demo Project Content

What Python project should the demo use? It needs to be:
- Small enough to understand in 30 seconds.
- Complex enough to have interesting graph relationships (calls, parent/child, tests).
- Domain-agnostic (not tied to web frameworks, data science, etc.).

### Option A: Calculator Library

```
src/
    calc.py         # add(), subtract(), multiply(), divide()
    converter.py    # celsius_to_fahrenheit(), kg_to_pounds()
    validator.py    # is_positive(), is_in_range()
tests/
    test_calc.py    # test_add(), test_divide_by_zero()
    test_converter.py
```

**Pros:** Universal, obvious, no domain knowledge needed.
**Cons:** Boring. Doesn't motivate why you'd want AI agents.

### Option B: Config Library (from concept doc Section 6)

```
src/configlib/
    __init__.py
    loader.py       # load_config(), detect_format()
    schema.py       # validate(), SchemaError
    merge.py        # deep_merge()
    interpolate.py  # resolve_env_vars()
tests/
    test_loader.py
    test_merge.py
```

**Pros:** Directly references the concept doc example. More realistic. Has natural dependencies (loader calls schema, merge, interpolate).
**Cons:** Slightly more cognitive load.

### Option C: Minimal Interconnected Functions

```
src/
    pipeline.py     # process(), transform(), validate(), report()
```

A single file with 4 functions that call each other in a chain. Simplest possible graph with visible edges.

**Pros:** Absolute minimum. One file, one graph, obvious flow.
**Cons:** Too simple to show extension configs, testing patterns.

### Recommended: Option B (Config Library)

It references the concept doc directly, has natural graph structure (loader->schema, loader->merge, tests->each module), and is complex enough to demonstrate extensions (test functions get TestFunction extension, __init__.py gets DirectoryManager extension) without being overwhelming.

---

## 9. Brainstorming: What "Looks Good" Means

The user said: "Its got to look good while running for one person, locally."

### Visual Identity

- **Graph viewer:** Dark background. Nodes as circles with subtle glow effects. Edges as thin lines. Active nodes pulse. Focused node has bright highlight ring. Smooth d3-force physics.
- **Color scheme:** Cool/dark base. Agent status colors: idle=dim grey/blue, running=bright green pulse, error=red, pending_approval=amber.
- **Typography:** Monospace for code/IDs. Clean sans-serif for labels.
- **Animations:** Nodes smoothly drift into position. Status changes trigger a brief flash/pulse. New nodes fade in. Removed nodes fade out.

### Layout for Demo

Split screen:
```
+----------------------------+--------------------+
|                            |                    |
|      NEOVIM                |   GRAPH VIEWER     |
|      (terminal)            |   (browser)        |
|                            |                    |
|  [code with lenses]        |  [force graph]     |
|  [panel on right]          |  [event stream]    |
|                            |                    |
+----------------------------+--------------------+
```

Or vertical:
```
+-------------------------------------------+
|              NEOVIM (top half)             |
|  [code with lenses]  |  [panel]           |
+-------------------------------------------+
|          GRAPH VIEWER (bottom half)        |
|  [force graph]        |  [sidebar]        |
+-------------------------------------------+
```

The side-by-side horizontal split is more natural for a widescreen monitor. Neovim on the left (60% width), graph viewer on the right (40% width).

### Key Visual Moments

1. **First open:** Files load, tree-sitter discovers nodes, code lenses appear one by one, graph viewer populates with nodes that drift into a stable layout. The swarm is born.
2. **Edit + save:** Node lights up in graph. Code lens changes. Panel shows activity. Chain ripples through connected nodes.
3. **Proposal arrives:** Neovim shows diagnostic squiggle. Graph viewer node turns amber. Click it to see the diff.
4. **Chat:** Type a message in the panel. See the model thinking (running status). Response streams in. Event appears in graph viewer's event stream.

---

## 10. Open Questions and Trade-offs

### Q1: How much of the Option A migration is needed for the demo?

The full 16-task Option A plan migrates everything to EventStore. But for a demo, we might not need all of it. The minimum for a coherent demo:
- EventStore must be the source of truth for node state (tasks 1-8 of Phase 1, already done).
- LSP handlers must read AgentNode from EventStore (Option A tasks 5-6).
- The runner must emit events to EventStore (partially done — `emit_event` in server.py already bridges to EventStore).

**Trade-off:** Do the minimum migration for the demo, or complete Option A first? Completing Option A makes the demo architecturally honest. Doing the minimum gets us to a visual demo faster.

### Q2: Datastar or plain SSE for graph data?

Datastar is great for HTML fragment streaming (sidebar content). For graph data (node positions, status updates, edges), it's awkward — we're sending structured data, not HTML. Plain SSE with `event: type` and `data: {...json...}` is simpler and more natural for the d3 client.

**Trade-off:** Pure Datastar (consistent with project patterns) vs. hybrid (Datastar for HTML, plain SSE for graph data). The hybrid is better for the graph viewer specifically.

### Q3: Single process or two processes?

The LSP server runs as a stdio process attached to Neovim. The graph viewer needs to serve HTTP. Options:
- **Two processes:** LSP server (stdio) + graph viewer web server (HTTP). Both read/write the same SQLite DB. Already the assumed architecture.
- **Single process with embedded HTTP:** The LSP server spawns an asyncio HTTP server internally. One process, shared memory. But pygls's event loop might conflict.

**Recommendation:** Two processes. SQLite WAL mode handles concurrent access. The `command_queue` table is the communication channel. This is simpler, more robust, and already designed.

### Q4: How to handle the graph viewer reading EventStore vs. RemoraDB?

Currently, RemoraDB has: nodes, edges, events, proposals, cursor_focus, command_queue, activation_chain.
EventStore has: events, nodes.

The graph viewer needs: nodes (for graph layout), cursor_focus (for highlighting), events (for event stream), and eventually command_queue (for interactions).

**Options:**
- Graph viewer reads from RemoraDB (the LSP-side database). Works today without migration.
- Graph viewer reads from EventStore (the core database). Requires completing enough of Option A.
- Graph viewer reads from both databases. Ugly but pragmatic.

**Recommendation for demo MVP:** Read from RemoraDB. It has everything the graph viewer needs today. When Option A is complete, switch to EventStore (which will have absorbed all the data).

---

## 11. Synthesis: The Demo Vision

### The "Golden Path" Demo Flow

A single person sits at their desk. Terminal with Neovim on the left. Browser with graph viewer on the right.

1. **Launch:** `nv2` starts Neovim with remora plugin. `python -m remora_demo.web` starts the graph viewer. Both connect to the same `.remora/indexer.db`.

2. **Discovery:** Open `src/configlib/loader.py`. Tree-sitter parses it. Three functions discovered. Code lenses appear: `● rm_a1b2c3d4 idle` above each function. Graph viewer shows three new nodes drifting into position. They're children of a file node.

3. **Open more files.** `schema.py`, `merge.py`, `test_loader.py`. The graph grows. Edges form — loader calls schema, loader calls merge, test_loader tests loader. The graph settles into a beautiful force-directed layout.

4. **Navigate.** Move the cursor to `load_config()`. The graph viewer highlights that node — a bright ring appears, the viewport smoothly pans to center it. The sidebar shows: agent details, subscriptions, last 5 events (all `NodeDiscoveredEvent`).

5. **Chat.** `:RemoraChat` and type "what do you do?" The agent responds (mock or real LLM) based on its system prompt. The exchange appears in both the Neovim panel and the graph viewer event stream.

6. **Edit.** Modify `load_config()` — add a parameter. Save. A `ContentChangedEvent` fires. The agent activates (code lens: `▶ running`, graph node: green pulse). The agent examines the diff and notices the API change. It calls `message_node` to notify `test_load_yaml` in `test_loader.py`.

7. **Cascade.** `test_load_yaml` agent activates. Its code lens changes. Its graph node pulses. The edge between `load_config` and `test_load_yaml` briefly glows. The test agent proposes updating the test to include the new parameter.

8. **Proposal.** Neovim shows a diagnostic squiggle on the test function. The graph node turns amber. The panel shows the proposed diff. Developer reads it, types `:RemoraAccept`. The edit is applied. Both the Neovim buffer and the graph viewer update.

9. **Reflection.** Open the EventLog view in the graph viewer. See the complete event chain: ContentChangedEvent -> AgentStartEvent -> ModelRequestEvent -> ModelResponseEvent -> AgentMessageEvent -> AgentStartEvent -> ... -> RewriteAppliedEvent. Every step auditable.

### Two Deliverables

**Deliverable 1: Enhanced Neovim Demo**
- Complete enough of Option A that the LSP reads AgentNode from EventStore.
- MockLLMClient enhanced for the golden path scenario.
- Demo project (configlib) with extension configs.
- Existing panel, code lens, hover, actions all working.

**Deliverable 2: Graph Viewer**
- Starlette + d3-force web app in `remora_demo/graph/` (or `remora_demo/web/`).
- Force-directed SVG graph with real-time updates via SSE.
- Cursor tracking (node highlight follows Neovim cursor).
- Event stream sidebar (global or per-agent filtered).
- Agent detail sidebar on node click.
- Command queue for web -> LSP interaction (chat, focus, approve).
- Dark theme, smooth animations, looks impressive.

### What Makes It "Look Good"

The magic is in the synchronization. When you save a file in Neovim and simultaneously see:
- Code lenses change
- Panel shows activity
- Graph viewer nodes pulse
- Event stream scrolls
- Edges glow

All driven by the same EventLog. That's the demo. That's the architecture made visible.

---

## 12. Leaning Into Stario/Datastar: Why Server-Owns-Everything Is The Right Architecture

### The Stario Philosophy

After studying Stario's source code, docs, and the chat example app, it's clear that Stario embodies a philosophy that maps almost perfectly onto what the graph viewer needs. The core principle is: **the server owns all state, and the browser is a thin rendering layer that receives HTML fragments and signal updates over SSE.**

This isn't just a technical choice — it's an architectural stance. Stario rejects the SPA model (client-side state, client-side routing, client-side rendering) in favor of:

1. **Server-rendered HTML** — Every visual update is an HTML fragment rendered on the server using Python functions (`Div({"id": "x"}, "content")`), not a JSON payload interpreted by client JavaScript.
2. **Datastar for DOM morphing** — The browser runs a tiny JS library (Datastar) that receives SSE events and morphs the DOM. No React, no Vue, no client-side framework.
3. **Signals for client state** — Minimal client-side state (form inputs, UI toggles) lives in "signals" — reactive key-value pairs that Datastar manages. The server can read signals from requests (`c.signals()`) and push signal updates (`w.sync()`).
4. **The Storyboard Approach** — Each SSE patch sends the *complete snapshot* of a component, not an incremental diff. Datastar handles the diffing. This means view functions are pure: `f(state) -> HTML`. No tracking what changed.

### Why This Is Better Than D3-Force Hybrid

Section 5 of this document recommended Approach 2 (D3-Force Hybrid): Datastar for the sidebar, but custom client-side JavaScript with d3-force for the graph SVG. After studying Stario, I'm revising that recommendation. Here's why:

**The hybrid approach has a fundamental split-brain problem.** It requires two rendering paradigms: server-rendered HTML for the sidebar (managed by Datastar), and client-rendered SVG for the graph (managed by custom JS reading JSON signals). This means:
- Two state management systems (Datastar signals for sidebar, JS variables for d3-force).
- Two update paths (SSE `patch_elements` for sidebar, SSE `event: graph` JSON for d3 simulation).
- The sidebar and graph can get out of sync.
- More client-side code = more bugs, harder to debug.

**A pure Stario approach eliminates the split.** Everything flows through one system:
- The server renders the graph as HTML (positioned `<div>`s or an `<svg>` built with the same Tag system).
- Datastar morphs the DOM on each SSE patch.
- Node positions, status colors, edge lines — all server-rendered.
- The sidebar, the event stream, the graph — all patched through the same `w.patch()` calls.

### But Wait — What About Smooth Animation?

This is the real concern. D3-force gives you physics-based animation: nodes drift, repel, settle. It *feels* alive. Can server-rendered positioned elements feel alive?

**Yes, with CSS transitions.** The key insight:
- Server computes layout (positions for all nodes) using a Python graph layout library (e.g., `igraph` or `networkx` spring layout, or even rustworkx's layout capabilities).
- Server renders each node as an absolutely-positioned `<div>` or SVG `<g>` with inline `style: {left: "123px", top: "456px"}`.
- CSS `transition: left 0.3s ease, top 0.3s ease` makes position changes animate smoothly.
- When a node moves (because the layout recalculated due to new nodes or edge changes), the browser smoothly animates it to the new position.
- Status changes (idle -> running -> error) use CSS `transition: background-color 0.2s`.

This won't be *identical* to d3-force's continuous physics simulation, but it achieves the same *effect* for a demo: nodes settle into positions, and changes animate smoothly. And it's dramatically simpler — zero client-side JS beyond Datastar.

### The Stario Relay = The EventLog Bridge

Stario's `Relay` class is a NATS-inspired in-process pub/sub system:

```python
relay = Relay()

# Publish (sync, fire-and-forget, thread-safe)
relay.publish("agent.rm_abc123.status", "running")

# Subscribe (async iterator, auto-cleanup)
async for subject, data in relay.subscribe("agent.*"):
    print(subject, data)
```

Key properties:
- **Subject-based routing** with wildcard patterns: `agent.*`, `event.*`, `*` (match everything).
- **Thread-safe publish** — can be called from any thread (important: the LSP server and graph viewer may share a process, or the LSP server might publish from background threads).
- **Async subscribe** — yields `(subject, data)` tuples. Used with `w.alive()` for SSE streaming.
- **Auto-cleanup** — when the async iterator exits (client disconnects), the subscription is removed.

This maps perfectly to our EventLog:
- When the EventStore appends an event, it publishes to the Relay: `relay.publish(f"event.{event.event_type}", event)`.
- When a node status changes, publish: `relay.publish(f"node.{node_id}.status", new_status)`.
- When cursor focus changes, publish: `relay.publish("cursor.focus", agent_id)`.
- The graph viewer's SSE handler subscribes: `async for subject, data in w.alive(relay.subscribe("*"))`.

No polling. No change detection. No DB polling loop. Events flow from EventLog -> Relay -> SSE -> Datastar -> DOM. Real-time, with zero latency.

### Stario Patterns For The Graph Viewer

Here's how specific Stario patterns map to graph viewer features:

#### Initial Page Load

```python
async def graph_home(c: Context, w: Writer) -> None:
    nodes = db.get_all_nodes()
    edges = db.get_all_edges()
    layout = compute_layout(nodes, edges)
    
    w.html(graph_page(
        nodes=nodes,
        edges=edges,
        layout=layout,
        cursor_focus=None,
        selected_node=None,
        events=[],
    ))
```

The initial page includes `data.init(at.get("/subscribe"))` which opens the SSE connection.

#### SSE Subscription (Real-Time Updates)

```python
def graph_subscribe(db, relay):
    async def handler(c: Context, w: Writer) -> None:
        # Send initial state
        nodes = db.get_all_nodes()
        edges = db.get_all_edges()
        layout = compute_layout(nodes, edges)
        
        w.patch(graph_view(nodes, edges, layout, cursor_focus=None))
        
        # Stream updates
        async for subject, data in w.alive(relay.subscribe("*")):
            # Re-render the full graph view on each event
            nodes = db.get_all_nodes()
            edges = db.get_all_edges()
            layout = compute_layout(nodes, edges)
            cursor = db.get_cursor_focus()
            
            w.patch(graph_view(nodes, edges, layout, cursor_focus=cursor))
            w.patch(event_stream_view(db.get_recent_events(limit=50)))
            
            # If a node is selected, update its detail sidebar
            signals = await c.signals(GraphSignals)
            if signals.selected_node:
                node = db.get_node(signals.selected_node)
                w.patch(node_detail_view(node))
    
    return handler
```

Note the Storyboard Approach: each patch sends the *complete* view of a component. No incremental diffing logic on the server. Datastar handles it.

#### Node Selection (Web -> Server -> Patch)

```python
def select_node(db):
    async def handler(c: Context, w: Writer) -> None:
        node_id = c.req.query.get("node")
        node = db.get_node(node_id)
        if node:
            w.patch(node_detail_view(node))
            w.sync({"selected_node": node_id})
    return handler
```

In the HTML:
```python
Div(
    {"id": f"node-{node.id}", "class": f"graph-node {node.status}"},
    data.on("click", at.get(f"/select?node={node.id}")),
    node.name,
)
```

Click a node -> `@get("/select?node=rm_abc123")` -> server fetches node data -> `w.patch()` updates the sidebar -> `w.sync()` updates the selected_node signal.

#### Cursor Focus (LSP -> Relay -> SSE -> Patch)

In the LSP server (when cursor moves):
```python
# In notifications.py, on cursor move:
relay.publish("cursor.focus", agent_id)
```

In the graph viewer SSE handler, the `relay.subscribe("*")` catches this. The handler re-reads cursor_focus and re-renders the graph with the highlighted node.

### What This Means For The Demo Plan

The graph viewer architecture in `EVENT_BASED_DEMO_PLAN.md` (Sections 5-7) needs to be rewritten:

1. **Section 5 (Architecture):** Replace "Starlette + SSE + d3-force + Datastar sidebar" with "Stario app + Relay + pure Datastar". Single rendering paradigm. No client-side JS framework.

2. **Section 6 (Server):** Replace Starlette routes/SSE endpoints with Stario handlers using `w.patch()`, `w.alive()`, and Relay subscriptions. Views are pure Python functions using Stario's HTML builder.

3. **Section 7 (Client):** Replace D3-force SVG + custom JS with server-rendered positioned elements + CSS transitions. The only client-side JS is Datastar (loaded from a `<script>` tag). No custom JavaScript.

4. **Graph Layout:** Use a Python layout algorithm (igraph's `layout_fruchterman_reingold()` or networkx's `spring_layout()`) to compute node positions server-side. Cache the layout and recompute only when the graph topology changes (node added/removed, edge added/removed).

5. **Process Model:** Two options now:
   - **Same process:** The graph viewer is a Stario app running in the same Python process as the LSP server. They share a `Relay` instance in memory. Instant event delivery, no DB polling. But: pygls's event loop and Stario's threading model might conflict.
   - **Separate process:** The graph viewer is a separate Stario process. Uses SQLite DB as the shared state (existing pattern). Polls DB or uses a separate IPC mechanism. Simpler isolation but adds latency.
   
   **Recommendation for demo:** Separate process. The LSP server writes events to SQLite. The graph viewer polls the DB at short intervals (200ms) and publishes changes to its own in-process Relay for SSE distribution. This is pragmatic and avoids any event loop conflicts. The polling latency (200ms) is imperceptible.

### The Philosophical Alignment

There's a deeper alignment between Stario's philosophy and the EventBased architecture:

| Stario Principle | EventBased Principle |
|---|---|
| Server owns all state | EventLog is the single source of truth |
| Browser is a thin rendering layer | Neovim/Graph viewer are projections of the EventLog |
| `w.patch(view(state))` — snapshot, not diff | NodeProjection rebuilds from events |
| Relay pub/sub for real-time | SubscriptionPattern for agent reactivity |
| Views are pure functions | `AgentNode.to_code_lens()`, `to_hover()` etc. are pure transforms |
| Factory functions inject dependencies | Extensions inject behavior via data |

Both architectures reject distributed client-side intelligence in favor of a centralized source of truth with thin projection layers. The graph viewer *is* a projection of the EventLog, just like the Neovim code lenses are. Building it with Stario makes this conceptual alignment manifest in the actual code.

### Remaining Open Question: Graph Rendering Strategy

Two viable approaches for the actual graph visuals:

**Option A: Absolutely-Positioned Divs**
```python
def node_view(node, x, y):
    return Div(
        {"id": f"node-{node.id}", 
         "class": f"node {node.status}",
         "style": {"position": "absolute", "left": f"{x}px", "top": f"{y}px"}},
        data.on("click", at.get(f"/select?node={node.id}")),
        Span({"class": "node-label"}, node.name),
    )
```
Pros: Pure HTML. CSS transitions work perfectly. Easy to style.
Cons: Edges (lines between nodes) are harder — need SVG overlay or CSS border tricks.

**Option B: Server-Rendered SVG**
```python
def graph_svg(nodes, edges, layout):
    return Svg(
        {"id": "graph", "viewBox": f"0 0 {width} {height}"},
        # Edges as lines
        *[Line({"x1": ..., "y1": ..., "x2": ..., "y2": ..., "class": "edge"}) for ...],
        # Nodes as circles + text
        *[G({"transform": f"translate({x},{y})", "class": f"node {n.status}"},
            Circle({"r": 20}),
            Text(n.name),
            data.on("click", at.get(f"/select?node={n.id}")),
          ) for ...],
    )
```
Pros: SVG is natural for graphs (lines, circles, transforms). CSS transitions work on SVG attributes.
Cons: Need to add SVG elements (Svg, Circle, Line, G, Text) to Stario's HTML builder (or use `SafeString`). Datastar morphing of SVG needs verification.

**Recommendation:** Option B (SVG). Edges are critical for a graph viewer, and SVG handles them naturally. Use `SafeString` for the SVG wrapper elements if Stario doesn't have them built-in — Stario's `Tag` class can construct any element, so `Svg = Tag("svg")`, `Circle = Tag("circle", self_closing=True)`, etc. CSS transitions on `transform`, `stroke`, `fill` etc. are well-supported in SVG.
