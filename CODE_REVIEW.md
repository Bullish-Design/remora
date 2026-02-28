# Remora Ground-Up Refactor: Detailed Code Review

## 1. Executive Summary

This code review assesses the Remora library's ground-up refactoring. The goal of the refactoring was to execute a conceptual unification mapping the Concrete Syntax Tree (CST) to persistent, autonomous agents coordinated asynchronously through reactive event routing and message passing, as outlined in `NVIM_DEMO_CONCEPT.md`, `REMORA_CST_DEMO_ANALYSIS.md`, and `REMORA_SIMPLIFICATION_IDEAS.md`.

### Verdict: **Partially Complete with Critical Gaps**

The new architecture presents a massive upgrade to elegance and clarity. The abstractions created—`AgentRunner`, `SwarmState`, `EventStore` with trigger queues, `SubscriptionRegistry`, and `NvimServer`—correctly establish the scaffolding for the reactive swarm architecture. The "dormant by default, triggered by subscription" model is beautifully established. 

However, several critical integrations were either omitted or only partially implemented, preventing the reactive mechanism from functioning holistically. Right now, agents can be instantiated and mapped to the CST, but they cannot talk to each other, they mismanage long-term state, and they lack intended source control (Jujutsu) overlay sync mechanisms. The legacy graphing mechanisms remain partially entwined where they should have been fully superseded or simplified.

## 2. Overview of Implemented Functionality & Successes

The codebase successfully implements the core structure of the new Reactive concept.

*   **The EventStore as the Message Bus**: `src/remora/core/event_store.py` has been correctly updated to include `from_agent`, `to_agent`, `correlation_id`, and `tags` columns. It implements the reactive triggering correctly: upon appending an event, it queries the `SubscriptionRegistry` and pushes matching `(agent_id, event_id, event)` tuples onto a local `asyncio.Queue`.
*   **SubscriptionRegistry**: Pattern matching across various fields (event type, sender, recipient, path, and tags) provides excellent routing granularity. Tracking `is_default` helps ensure baseline awareness per agent.
*   **The Neovim RPC Server**: `nvim/server.py` efficiently handles RPC inputs from the editor and acts as a generic UI subscriber, accurately mapping `swarm.emit`, `agent.select`, and `agent.chat` commands. 
*   **Decoupled Agent States**: By moving `AgentState` isolation out of the runtime, maintaining `sqlite` workspace dbs alongside `state.jsonl`, agents have true persistent capabilities separate from process life-cycles.
*   **Cascade Management Strategy**: `agent_runner.py` enforces a `correlation_id` cascade limit (`max_trigger_depth`) and a `trigger_cooldown_ms` limit preventing rapid re-triggering, creating a stable asynchronous swarm.

## 3. Discrepancies and Issues Identified

Despite the excellent structural work, a thorough audit reveals severe adherence flaws against the outlined refactor goals. We do not care about backwards compatibility—so any legacy systems persisting in spite of new conceptual guidelines are marked as errors.

### Issue 1: Missing Swarm Communication Capability (Critical)
The documents rely heavily on agents talking to each other, and specify `send_message.py` and `subscribe.py` tools. Neither of these tools exists within `src/remora/core/tools/`. Additionally, the `SwarmExecutor` (`swarm_executor.py`) lacks the required external hooks (e.g., an `emit_event` callback) to allow these tools to inject events into the `EventStore`. As a result, agents are effectively muted; they cannot coordinate with parent/children or subscribe to events at runtime.

### Issue 2: `AgentRunner` Ignores Outgoing Events and Tool States (Critical)
According to `REMORA_CST_DEMO_ANALYSIS.md` (1.7/2.2), after the `AgentKernel` completes a turn, either the tool execution directly pushes the `AgentMessageEvent` into the store, or the runner inspects `tool_calls` and emits it. This mechanism is missing. Furthermore, while the runner does execute the turn, it misses preserving critical execution outputs into `AgentState.chat_history` for multi-turn conversational agents.

### Issue 3: Incomplete Content Diffing in `reconciler.py` (High)
`REMORA_CST_DEMO_ANALYSIS.md` (1.8) specifies that `reconciler.py` must track files changed while the daemon was down. Currently, `reconciler_on_startup` only diffs the existence of `node_id` constraints (new vs. deleted). It misses the critical `content_changed(current_nodes[node_id], saved_agents[node_id])` check. If an agent's code changed while stopped, it enters an invalid state unaware of the manual text change.

### Issue 4: `FileSavedEvent` Triggers `ValueError` in RPC Bridge (High)
In `nvim/server.py`, `_handle_swarm_emit` allows generic events to be piped gracefully into the `EventStore`. Yet, it uses a manual `if/elif` that only permits `AgentMessageEvent` and `ContentChangedEvent`. The `buffer.lua` file sends `FileSavedEvent` every time a buffer is saved, meaning the RPC bridge crashes/throws a `ValueError` out of the gate, breaking Neovim synchronization.

### Issue 5: Vestigial `tool_registry.py` and `context.py` Modules (Medium)
`REMORA_SIMPLIFICATION_IDEAS.md` (Sections 3.4 & 3.6) calls explicitly for deleting `tool_registry.py` and migrating `context.py` entirely into `AgentState`. 
*   `tool_registry.py` remains.
*   `context.py` remains and uses its legacy "sliding window/since_id" memory builder internally inside `swarm_executor.py`, contradicting the reactive paradigm where events provide contextual history. 

### Issue 6: Unimplemented Jujutsu (VCS) Synchronization (Medium)
Section 1.10 of the `REMORA_CST_DEMO_ANALYSIS.md` defines Jujutsu for tracking file modifications over time with no overlay complexity ("One-way sync: Remora → Jujutsu"). Currently, there is absolutely no logic hooked into agent execution completion, workspace write hooks, or file savers that calls `jj commit` when agents alter standard source files.

### Issue 7: `AgentState` Does Not Include Context Tracking (Medium)
Because `context.py` wasn't fully merged, `AgentState` fails to natively retain its own memory timeline inside its JSONL storage. If an agent is preempted, it simply loses its sliding-window Short Track memory. The system must merge `chat_history` logic tightly with LLM context framing, completely internalizing memory into `AgentState`.

### Issue 8: Vestigial Modules Left in Scope (Low)
There are multiple modules spanning the codebase that should have been entirely deprecated to avoid confusion:
*   `executor.py` (legacy graph execution) is loosely coupled and overlaps with the concept of synchronous agent triggers. The reactive `AgentRunner` replaces graph topological sorts with subscriptions. If graph batches are explicitly still needed, they must be stripped to minimum viable.
*   `remora.ui.projector` dependencies and logic look to handle streaming sync legacy states rather than true reactive data representation.

## 4. Conclusion

The Remora repository stands exactly in the middle of a major paradigm shift. The core data structures and asynchronous primitives required to enable an AST Swarm are accurately installed. However, because agents lack `send_message` and `subscribe` tools, and because the `SwarmExecutor` (`swarm_executor.py`) lacks standard `EventStore` emitters, the reactive swarm is essentially "read-only" at runtime. Furthermore, incomplete implementations in startup diffing (`reconciler.py`) and Jujutsu source control syncing prevent the daemon from operating as a persistent, reliable orchestrator.

A complete refactoring must prioritize giving the agents dynamic operational access to the `EventStore` and fixing the lifecycle/persistence loops (startup diffs, neovim file save events, and jj overlay check-ins).
