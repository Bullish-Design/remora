# ASSUMPTIONS — Scaffold Nodes

## Project Purpose

Add a "scaffold node" capability to Remora: nodes that are created empty (or near-empty) and self-initialize by gathering context from their parent, siblings, and project structure. This enables generative workflows where agents create new code by understanding what's needed rather than being told exactly what to write.

## Audience

- Developers using Remora as a reactive agent system
- Extension authors who want to define scaffold behaviors
- The demo project (`remora_demo/project/`) serves as the reference showcase

## Constraints

- **AgentNode is a single Pydantic BaseModel** — no subclasses. The `"scaffold"` status is just a new string value for the existing `status` field.
- **No new fields on AgentNode** — scaffold behavior is driven by the status value, a new event type, and extension configs. The model stays unchanged.
- **Extensions are pure data declarations** — scaffold extensions follow the same `matches()` + `get_extension_data()` pattern.
- **No core behavior changes for existing nodes** — adding scaffold support must not alter how existing idle/running/error nodes behave.
- **TDD** — every feature starts with a failing test.
- **NO SUBAGENTS** — all work done directly.

## Key Design Decisions

### 1. Scaffold is a status, not a type

`status = "scaffold"` on an existing `AgentNode`. This means:
- No schema migration needed
- Projection upsert already preserves status on updates
- Extensions can match on any node_type — the scaffold behavior is orthogonal to whether it's a class, function, or file

### 2. ScaffoldRequestEvent triggers initialization

A new `ScaffoldRequestEvent` is emitted when a scaffold node is created. It carries `node_id`, `node_type`, `parent_id`, and an optional `intent` string (human-provided hint like "HTTP client class" or "unit tests for parser"). Extensions subscribe to this event to drive the initialization cycle.

### 3. Three creation paths, one lifecycle

| Path | Trigger | Emitter |
|------|---------|---------|
| **User-triggered** | LSP code action / command | LSP handler emits `ScaffoldRequestEvent` |
| **Agent-triggered** | Parent calls `spawn_child()` tool | Tool implementation emits `NodeDiscoveredEvent` + `ScaffoldRequestEvent` |
| **Template-driven** | Empty file / stub detected on save | Watcher detects empty/stub → reconciler emits `ScaffoldRequestEvent` |

All three paths converge on the same lifecycle:
1. `NodeDiscoveredEvent` (source_code="" or stub) → projected with `status = "scaffold"`
2. `ScaffoldRequestEvent` → matched by subscription → triggers agent run
3. Agent gathers context (automatic in prompt) and calls `rewrite_self()`
4. `NodeDiscoveredEvent` re-emitted with real content → status transitions to `"idle"`

### 4. Context enrichment for scaffold nodes

When `_build_prompt()` in `swarm_executor.py` builds the prompt for a scaffold node, it includes:
- Parent node's source code and system prompt
- Sibling node names and types (other children of the same parent)
- The `intent` from `ScaffoldRequestEvent` (if any)
- File-level docstring/imports (if the scaffold is inside an existing file)

This is the "context inheritance" approach — the scaffold node automatically has enough information to make a reasonable first draft without needing explicit inter-agent messaging.

### 5. spawn_child tool design

Available to any agent (not just file-level). Parameters:
- `node_type: str` — "class", "function", "file"
- `name: str` — the name for the new node
- `intent: str` — what the child should do (becomes the prompt hint)
- `file_path: str | None` — where to create it (defaults to same file as parent for class/function, or generates a path for file)

The tool:
1. Writes a stub to disk (e.g., `class Foo: pass\n` or empty file)
2. Emits `NodeDiscoveredEvent` with the stub content and `status` hint
3. Emits `ScaffoldRequestEvent` with the intent
4. Returns the new node_id to the caller

### 6. Scaffold extension config

A new extension in `remora_demo/project/.remora/models/scaffold_initializer.py` demonstrates the pattern. It matches nodes where `source_code` is empty or a known stub pattern, and provides a system prompt that instructs the agent to examine its context and generate appropriate content.

### 7. Status transition rules

| Current Status | Event | New Status |
|---------------|-------|------------|
| (new node) | `NodeDiscoveredEvent` with empty source | `scaffold` |
| `scaffold` | `ScaffoldRequestEvent` → agent runs → `rewrite_self` | `idle` |
| `scaffold` | Agent fails | `error` |
| `idle` | Normal agent lifecycle | (unchanged) |

### 8. Phase 1 scope (this project)

Phase 1 focuses on the foundational mechanics:
- `ScaffoldRequestEvent` event type
- `"scaffold"` status recognition in projection
- Context-enriched prompt building for scaffold nodes
- `spawn_child` tool
- Scaffold extension config (demo)
- Detection of empty/stub nodes in watcher
- Unit + integration tests

Phase 1 does NOT include:
- Multi-round negotiation (Phase 2)
- LSP code actions for user-triggered scaffolds (Phase 2)
- Review loops where parent checks child's draft (Phase 3)

### 9. Stub detection heuristics

A node is considered a "stub" (and should get scaffold status) when:
- `source_code` is empty string
- `source_code` matches known stub patterns: `class Foo: pass`, `def foo(): pass`, `def foo(): ...`
- File is empty or contains only comments/docstrings

This detection happens in the projection layer when processing `NodeDiscoveredEvent`.

### 10. No changes to AgentExtension.matches() signature

The `matches()` method already accepts `node_type`, `name`, `file_path`, `source_code`. Extensions can detect scaffold-worthy nodes by checking `source_code` for stub patterns. No new parameters needed.
