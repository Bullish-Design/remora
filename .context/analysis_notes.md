# Analysis Notes: FSdantic KV for Event Store + Further Simplifications

## FSdantic KV Store Assessment

### What FSdantic KV Provides
- Key-value store backed by AgentFS SDK (Turso/libsql under the hood)
- Namespace-based key scoping (`workspace.kv.namespace("events")`)
- Typed repositories via Pydantic models
- Batch operations (`get_many`, `set_many`, `delete_many`)
- Best-effort transactions
- Already a dependency of Remora (via Cairn)

### What EventStore Needs
1. Append-only sequential writes with auto-incrementing IDs
2. Time-range queries (since, until)
3. Replay with filtering (by event_type, graph_id, after_id)
4. Trigger queue (in-memory async queue for subscription matching)
5. Routing fields (from_agent, to_agent, correlation_id, tags)

### Verdict: Use FSdantic KV Selectively

The event store needs ordered sequences, range queries, and indexed filtering 
that a KV store doesn't naturally support. However, all OTHER state storage
(agent registry, subscriptions, agent state) maps perfectly to KV semantics.

**Best approach:**
1. Agent state → FSdantic KV ✅ (simple get/set per agent)
2. Subscriptions → FSdantic KV ✅ (keyed by agent_id, prefix listing)
3. Agent registry → FSdantic KV ✅ (keyed by agent_id)
4. Events → Keep as simplified SQLite ❌ (ordered sequences need SQL)

Use ONE FSdantic workspace's KV for #1-3. Keep a single SQLite for #4.

## Architecture: 2 Storage Concerns

```
Events (SQLite) → event_store.py (simplified, just append + replay + triggers)
Everything else (FSdantic KV) → One workspace with namespaced KV
Agent workspaces (FSdantic) → Per-agent CoW sandboxes (already exist)
```

## Additional Simplifications
1. Cairn Bridge → Use FSdantic.open() directly instead of low-level cairn.runtime
2. Remove EventSourcedBus wrapper (causes double-emit, unnecessary layer)
3. Merge EventBus into EventStore (in-memory pub/sub is just callbacks)
4. Simplify AgentWorkspace (FSdantic handles concurrency internally)
5. Flatten RemoraService → AgentRunner IS the API
6. Remove legacy files (executor.py, graph.py, context.py)
