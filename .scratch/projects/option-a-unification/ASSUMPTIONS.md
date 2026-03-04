# Option A: LSP→EventStore Unification — Assumptions

## Project audience
- Single developer (project author) working on Remora, a reactive agent swarm system.
- Agents are code nodes (functions, classes, methods, files) that communicate via events.

## Core architectural invariant
- The EventLog (EventStore) is the single source of truth for all node state.
- Every state change is an event. In-process subscribers get instant notification.
- No parallel node state systems — one canonical path from discovery to query.

## AgentNode constraints
- Single Pydantic BaseModel. No subclasses anywhere.
- Specialization via data fields (extension_name, extra_tools, etc.), not inheritance.

## RemoraDB role
- LSP-specific operational state only: proposals, cursor_focus, command_queue, events, activation_chain, edges.
- Not a source of truth for node identity or status.

## Backward compatibility
- The `remora_demo` web viewer has its own `remora_id` data contract — separate from the LSP subsystem.
- Migrating `remora_demo` is a separate project if desired.
