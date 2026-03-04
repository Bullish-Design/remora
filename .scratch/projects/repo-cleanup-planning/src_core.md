# src/remora/core/ — Shadow Tree Notes

## Status: KEEP (Phase 1 EventBased core) + MODIFY (pre-EventBased modules)

### Phase 1 EventBased (KEEP as-is):
- `agent_node.py` — AgentNode Pydantic model + ToolSchema. NEW. Phase 1.
- `events.py` — Unified event types (RemoraEvent hierarchy + re-exports). NEW. Phase 1.
- `event_store.py` — SQLite-backed EventStore. NEW. Phase 1.
- `projections.py` — NodeProjection (events → nodes table). NEW. Phase 1.

### Core infrastructure (KEEP, may need modification):
- `config.py` — Config loading (remora.yaml + bundle.yaml). Stable utility.
- `discovery.py` — TreeSitter-based CSTNode discovery. Core to EventBased.
- `errors.py` — Error hierarchy. Stable utility.
- `event_bus.py` — In-memory pub/sub. Used by reactive loop. Keep for now but may merge into EventStore per EventBased concept.
- `subscriptions.py` — SubscriptionRegistry for reactive event routing. Core to EventBased.

### Pre-EventBased modules (MODIFY or REMOVE during Option A):
- `agent_state.py` — Old AgentState dataclass (file-based persistence). Being replaced by EventStore nodes table.
- `agent_runner.py` — AgentRunner for reactive execution. Uses EventStore. KEEP but may need update.
- `cairn_bridge.py` — Cairn workspace bridge. Depends on cairn package. KEEP but evaluate cairn dependency.
- `cairn_externals.py` — Cairn external functions. Depends on cairn. Same as above.
- `chat.py` — Chat session wrapper. Uses old workspace pattern. MODIFY.
- `reconciler.py` — Startup reconciliation (discovery → agent state). MODIFY to use EventStore.
- `swarm_state.py` — SwarmState registry. Being replaced by EventStore. REMOVE after Option A.
- `swarm_executor.py` — SwarmExecutor. MODIFY to use AgentNode from EventStore.
- `vcs.py` — VCS adapter (jujutsu). Small utility. KEEP.
- `workspace.py` — AgentWorkspace. Depends on cairn. KEEP but evaluate.

### Subdirectory:
- `tools/` — grail.py, swarm.py — Grail tool discovery + swarm tools. KEEP but depends on grail.
