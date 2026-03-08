# Phase 2 Bootstrap v4: Workspace-First

> v4 distills v3 down to its absolute essence.
>
> The core insight: an agent needs exactly two built-in capabilities —
> **read its workspace** and **write its workspace** — plus one runtime
> convention: if `schema.yaml` exists in the workspace, use it as the
> turn definition.
>
> Everything else — graph access, event participation, tool synthesis,
> privileged operations — is earned through demonstrated behavior. The
> workspace IS the agent: its identity, its memory, and its self-definition,
> all in the same place, in plain text.

---

## Table of Contents

1. [The Core](#1-the-core)
   Two tools. One convention. One persistent store. The irreducible minimum
   that makes the bootstrapping loop close.

2. [The Workspace](#2-the-workspace)
   What lives in every agent's cairn workspace. Contractual files the runtime
   relies on. Conventional files the agent chooses to use. The workspace
   as the single source of truth.

3. [schema.yaml — The Turn Definition](#3-schemayaml--the-turn-definition)
   The agent's turn, described as a text file. Format, template variables,
   context steps, subscriptions. Composition via `extends`. How it replaces
   bundle.yaml and the Pydantic TurnSchema serialization problem.

4. [The Workspace as Memory](#4-the-workspace-as-memory)
   notes.md, log.jsonl, todo.md, working_memory.md. Persistent cross-activation
   memory that the agent owns, writes, and reads — all via the two core tools.

5. [The Capability Ladder](#5-the-capability-ladder)
   Core (all agents: read + write). Earned tiers above it: graph observation,
   event participation, graph authorship, tool creation, governance. How
   capabilities are declared, granted, and enforced.

6. [What Is Not Specified](#6-what-is-not-specified)
   Deliberate omissions: graph topology, edge semantics, protocol state
   machines, agent taxonomy. These emerge from what agents write, not from
   what this document prescribes.

7. [The Bootstrap Sequence](#7-the-bootstrap-sequence)
   From empty workspace to self-defining agent. How the two-tool core enables
   the full self-bootstrapping loop without any additional ceremony.

8. [Developer and Companion Visibility](#8-developer-and-companion-visibility)
   The companion sidebar as a workspace file viewer. Interactive todo.md.
   Developer correction via direct workspace edits. No special protocol.

9. [Delivery Plan](#9-delivery-plan)
   Milestones ordered by the core-first priority: workspace substrate before
   graph, graph before events, events before governance.

---

## 1. The Core

Every agent in the bootstrap system has exactly two built-in capabilities:

```
read_file(path)           → read any file in the agent's cairn workspace
write_file(path, content) → write any file in the agent's cairn workspace
```

And the runtime observes one convention:

```
If schema.yaml exists in the agent's workspace → use it as the turn definition.
If schema.yaml is absent                       → use DEFAULT_SCHEMA instead.
```

That is the complete core. No graph access, no event bus, no privileged
operations. Just two file operations and one file convention.

### Why this is sufficient

With `read_file` and `write_file`, an agent can:

- **Read its role** — `read_file("role.md")` → who it is, what it's for
- **Read the project source** — `read_file("{node.file_path}")` → the code it's responsible for (the stable workspace fallback makes project files available via the same call)
- **Read its own notes** — `read_file("notes.md")` → what it has learned across activations
- **Write its role** — `write_file("role.md", ...)` → define its own purpose
- **Write its notes** — `write_file("notes.md", ...)` → accumulate knowledge
- **Write its schema** — `write_file("schema.yaml", ...)` → redefine its own next turn

The last point closes the bootstrapping loop: an agent can change its own
behavior by writing `schema.yaml`. The runtime picks it up on the next
activation. No Python, no class hierarchy, no external registry.

### DEFAULT_SCHEMA

Every agent begins with a default turn that gives it the two core tools and
prompts it to populate its workspace:

```python
DEFAULT_SCHEMA = TurnSchema(
    system=Concat(parts=(
        "You are a Remora agent node responsible for: ",
        ToolRef("read_file", {"path": "role.md"}),
        "\n\nYour workspace is empty. This turn:\n"
        "1. Read your node's source to understand your responsibility\n"
        "2. Write role.md — clear prose describing your purpose\n"
        "3. Write notes.md — one initial note about what you're responsible for\n"
        "4. Write schema.yaml — your turn definition for future activations\n"
        "5. Write one line to log.jsonl recording this activation\n"
        "\nThe schema.yaml format is described in the write_file tool hints.",
    )),
    context=ContextPipeline(steps=(
        Step("role",   ToolRef("read_file", {"path": "role.md"})),
        Step("source", ToolRef("read_file", {"path": "{node.file_path}"})),
    )),
    tools=("read_file", "write_file"),
    max_turns=3,
    termination="done",
)
```

After one activation with DEFAULT_SCHEMA, the agent has a populated workspace
and a `schema.yaml` for subsequent turns. The loop closes in the very first
activation.

### The runtime agent model

The runtime representation of an agent is intentionally minimal:

```python
class BootstrapAgent(BaseModel):
    node_id: str
    capabilities: frozenset[Capability]
    status: str = "idle"
    subscriptions: list[SubscriptionPattern] = Field(default_factory=list)
```

No `schema` field — the schema is loaded from `schema.yaml` in the workspace
on each activation, not held in memory between activations. No `name` field —
the agent's name is in `role.md` and `schema.yaml`, readable from the workspace.
The runtime model carries only what the runtime needs between activations:
identity, capability grant, status, and subscriptions.

---

## 2. The Workspace

Each agent has a cairn workspace: a Cairn-backed key-value store that behaves
like a filesystem (paths → string content). Backed by a SQLite `.db` file at
`.remora/<swarm_id>/agents/<agent_id>/workspace.db`.

The workspace is persistent across activations. Whatever the agent writes
in activation 1 is there in activation 1000.

### 2.1 The stable workspace fallback

The project's source files live in the stable workspace
(`.remora/<swarm_id>/stable.db`). When an agent calls `read_file` with a path
that doesn't exist in its own workspace, the cairn layer falls back to the
stable workspace automatically. This means `read_file("{node.file_path}")` — a
path like `src/remora/core/events/events.py` — just works, with no special
external needed. The two core tools already reach the project source.

### 2.2 Workspace file layout

```
<agent workspace>

  role.md                 ← Who this agent is and what it's responsible for.
                            Written by the agent on first activation.

  schema.yaml             ← The agent's turn definition.
                            Written by the agent; loaded by runtime each activation.
                            If absent: DEFAULT_SCHEMA runs instead.

  capabilities.yaml       ← The agent's current capability grant.
                            Written and updated by the runtime only.
                            Agent reads this to understand what it has.

  notes.md                ← Accumulated knowledge across activations.

  log.jsonl               ← One JSON line per activation. Appended each turn.

  todo.md                 ← Pending tasks. Optional — agent creates if useful.

  working_memory.md       ← Per-turn scratchpad. Overwritten, not accumulated.

  tools/                  ← Agent-synthesized .pym tools (requires TOOL_SYNTHESIZE).
    *.pym
```

### 2.3 Two classes of files

**Contractual** — the runtime reads these to run the agent:

| File | Who writes | Runtime use |
|------|-----------|-------------|
| `role.md` | Agent | Included in system prompt (via `{{role}}` in schema.yaml) |
| `schema.yaml` | Agent | Loaded as the TurnSchema before each activation |
| `capabilities.yaml` | Runtime only | Read to build the externals dict |

**Conventional** — the agent creates these if and when useful:

| File | Purpose | Typical pattern |
|------|---------|----------------|
| `notes.md` | Accumulated knowledge | Appended each activation; agent manages growth |
| `log.jsonl` | Activation history | One appended JSON line per activation |
| `todo.md` | Pending work | Checkbox syntax; developer-interactive in sidebar |
| `working_memory.md` | Current-turn scratchpad | Overwritten each activation |

An agent that never needs `todo.md` doesn't create it. An agent that needs
monthly notes creates `notes/2026-03.md`. The conventional files are strong
defaults, not mandates.

### 2.4 The workspace as identity

The workspace is not just storage — it IS the agent:

- **What the agent IS:** `role.md` + `schema.yaml`
- **What the agent KNOWS:** `notes.md` + `log.jsonl`
- **What the agent IS DOING:** `working_memory.md` + `todo.md`
- **What the agent CAN DO:** `capabilities.yaml` (runtime-maintained)

Reading an agent's workspace tells you everything about it. There is no
hidden state. The companion sidebar, developer inspection tools, and the
agent's own context pipeline all read the same files.


---

## 3. schema.yaml — The Turn Definition

`schema.yaml` is the agent's turn definition stored as a plain text file in
its own workspace. The runtime loads it before each activation and converts
it to a `TurnSchema` for execution. If the agent updates `schema.yaml`, the
next activation uses the new definition — no restart, no registration, no
code change.

### 3.1 The format

```yaml
# schema.yaml — agent turn definition
version: "1"

# ── Identity ──────────────────────────────────────────────────────────────────
name: events_module_agent

# ── Capabilities required ─────────────────────────────────────────────────────
# Declared by the agent. Runtime validates against capabilities.yaml.
# Activation fails if any declared capability has not been granted.
capabilities:
  - file_read
  - file_write
  - graph_read
  - event_emit
  - schema_evolve

# ── System prompt ─────────────────────────────────────────────────────────────
# Multiline string. {{role}} and {{notes}} are inlined from workspace files.
# {node.*} and {agent.*} are resolved from runtime context.
system: |
  You are responsible for {node.full_name} at {node.file_path}.
  {{role}}
  Keep notes.md updated. Append one line to log.jsonl every activation.

# ── Context pipeline ──────────────────────────────────────────────────────────
# Steps run before the LLM turn. Each step's output is stored as $step_name
# and available for interpolation in later steps' args.
context:
  - name: role
    tool: read_file
    args: {path: role.md}

  - name: notes
    tool: read_file
    args: {path: notes.md}
    optional: true        # skipped cleanly if file doesn't exist yet

  - name: source
    tool: read_file
    args: {path: "{node.file_path}"}

  - name: recent_events
    tool: read_recent_events
    args: {node_id: "{node.id}", limit: 10}

  - name: callers
    tool: graph_neighbors
    args: {node_id: "{node.id}", direction: in, limit: 20}

# ── Interactive tools ─────────────────────────────────────────────────────────
# Tool names available to the LLM during the turn.
tools:
  - write_file
  - emit_event
  - graph_add_edge
  - graph_neighbors

# ── Event subscriptions ───────────────────────────────────────────────────────
subscriptions:
  - event_type: ContentChangedEvent
    node_id: "{node.id}"
  - event_type: DirectMessageEvent
    to_agent: "{agent.id}"

# ── Turn control ──────────────────────────────────────────────────────────────
max_turns: 5
termination: "done"
```

### 3.2 Template variables

Resolved at activation time from static context — before the LLM sees anything:

| Variable | Resolves to |
|----------|------------|
| `{node.id}` | Code node identifier |
| `{node.file_path}` | File path the agent is responsible for |
| `{node.name}` | Function, class, or module name |
| `{node.full_name}` | Fully qualified name |
| `{node.kind}` | Node kind (e.g. `python:function`) |
| `{agent.id}` | Runtime agent identifier |
| `{{role}}` | Full contents of `role.md` inlined into the string |
| `{{notes}}` | Full contents of `notes.md` inlined into the string |

### 3.3 The `optional` flag

A step marked `optional: true` is silently skipped if its tool call fails
(file not found, permission error, etc.). The step outputs an empty string
to `$step_name` and the pipeline continues.

This makes first-activation reliable: `notes.md` doesn't exist yet, so the
notes step must be optional. The agent writes it during the turn; subsequent
activations find it.

### 3.4 Composition via `extends`

A schema can extend a base schema file, with the child's fields merged on top:

```yaml
extends: code_agent       # resolved from bootstrap/agents/bases/code_agent.yaml

name: docstring_reviewer

context:
  append:                 # added AFTER the base context steps
    - name: current_doc
      tool: read_recent_events
      args: {node_id: "{node.id}", tag: "docstring"}

tools:
  append:
    - rewrite_docstring

max_turns: 3
```

Merge rules: scalars override; `append:` adds to lists; `replace:` replaces lists.
Single inheritance only — one `extends`, max two levels deep.

Base schema files live in `bootstrap/agents/bases/` (version-controlled,
developer-authored). An agent's own `schema.yaml` can extend a base to start
richer without having to redeclare all the standard steps.

### 3.5 Capability presets

Named preset files in `bootstrap/agents/capabilities/` bundle common
capability sets:

```yaml
# code_writer.yaml — the standard code-working capability set
capabilities:
  - file_read
  - file_write
  - schema_evolve
  - graph_read
  - event_emit
```

A schema references a preset and adds to it:

```yaml
capabilities_preset: code_writer
capabilities:
  append:
    - graph_write         # in addition to the preset
```

The presets are the capability ladder (§5) made concrete and version-controlled.

### 3.6 Validation

When the agent writes `schema.yaml` (via `write_file`), the runtime
validates it on the next activation load. Validation failures fall back
to DEFAULT_SCHEMA with a structured error logged to the workspace:

```
.remora/.../workspace.db → schema.error.yaml (the failed schema + error message)
```

The agent can read `schema.error.yaml` on its next activation (DEFAULT_SCHEMA
reads it as a context step) and correct the mistake.

For in-turn feedback, a `validate_schema(yaml_content)` tool is available
to agents with `SCHEMA_EVOLVE` capability. It returns success or a
line-numbered error message before the agent writes the file — giving the
LLM a chance to correct in the same turn.


---

## 4. The Workspace as Memory

An agent's memory is its workspace. No special memory primitives, no
graph-based episode store, no distillation workflows specified in advance.
The two core tools (`read_file`, `write_file`) are all the agent needs to
maintain any memory it finds useful.

The conventional files below are strong defaults — included in the DEFAULT_SCHEMA
context pipeline from activation 1 — but the agent decides their format,
growth strategy, and whether it uses them at all.

### 4.1 notes.md — accumulated knowledge

Append-mostly Markdown. The agent adds entries as it learns things:

```markdown
# Notes — src/remora/core/events/events.py

## 2026-03-08 — activation #12
ContentChangedEvent is imported by 33 modules. Signature changes have
very high blast radius. Treating as frozen until further notice.

## 2026-03-07 — activation #1
Initialized. Responsible for keeping event type signatures stable.
```

The runtime doesn't parse this. The companion sidebar renders it as Markdown.
The agent reads it as `$notes` in the context pipeline — its long-term memory.

**Growth:** Eventually `notes.md` grows too large. The agent manages this:
summarize, prune, archive to `notes/2026-03.md`. The runtime provides no
automatic pruning. An agent that ignores growth will notice context bloat and
learn to manage it. This is emergence.

### 4.2 log.jsonl — activation history

One structured JSON line per activation, appended by the agent at turn end:

```jsonl
{"ts":"2026-03-08T14:32Z","n":12,"trigger":"ContentChangedEvent","outcome":"done","turns":3,"tools":["write_file","emit_event"],"emitted":["SchemaStableEvent"]}
{"ts":"2026-03-07T16:00Z","n":1,"trigger":"NodeDiscoveredEvent","outcome":"bootstrapped","turns":1,"tools":["write_file"],"emitted":[]}
```

Grep-friendly, appendable, parseable by developer tools and other agents.
The companion sidebar parses the last few lines for the LOG section.

### 4.3 todo.md — pending work

Standard Markdown checkbox syntax the agent maintains across activations:

```markdown
# Todo

- [ ] Investigate why ContentChangedEvent has 33 importers
- [ ] Propose discriminated union for StructuredEvent
- [x] Write role.md
- [x] Add graph_neighbors step to schema
```

The companion sidebar renders checkboxes as interactive — a developer can
toggle them directly, writing back to the workspace. The agent sees the
change on next activation: developer and agent share the same list.

### 4.4 working_memory.md — turn scratchpad

Overwritten (not appended) each activation. The agent's current-turn
reasoning:

```markdown
# Working Memory — activation #12

Trigger: ContentChangedEvent. Checking: did any exported signatures change?
- ContentChangedEvent signature: UNCHANGED ✓
- NullResponseEvent: NEW type, 0 callers. Low risk.
Decision: emit SchemaStableEvent. Note the new variant.
```

`notes.md` gets the distilled insight. `working_memory.md` gets the live
reasoning. Whether to include it in the context pipeline is the agent's call.

### 4.5 Memory from activation 1

DEFAULT_SCHEMA prompts the agent to establish all four files in its first
activation. Memory management is a habit from the start, not a behaviour
discovered on activation 20.


---

## 5. The Capability Ladder

The two core tools (`read_file`, `write_file`) are always available, to every
agent, from activation 1. They require no grant, no request, no demonstration.

All other capabilities are earned. A new agent has the minimum needed to
bootstrap itself. Additional capabilities are granted by the maintainer agent
after the requesting agent demonstrates stable, correct behavior at its current
level.

```
  ┌───────────────────────────────────────────────────────────────────────┐
  │  PRIVILEGED                                                           │
  │  update_subscription, register_protocol                               │
  │  — modify the substrate itself                                        │
  ├───────────────────────────────────────────────────────────────────────┤
  │  TOOL_SYNTHESIZE                                                      │
  │  write_file into tools/*.pym                                          │
  │  — create new capabilities for self and neighbors                     │
  ├───────────────────────────────────────────────────────────────────────┤
  │  GRAPH_WRITE                                                          │
  │  graph_add_node, graph_add_edge, graph_remove_*                       │
  │  — author the shared semantic structure                               │
  ├───────────────────────────────────────────────────────────────────────┤
  │  EVENT_EMIT + GRAPH_READ                                              │
  │  emit_event, read_recent_events, graph_node, graph_neighbors,         │
  │  graph_find_nodes                                                     │
  │  — observe and participate in swarm coordination                      │
  ├───────────────────────────────────────────────────────────────────────┤
  │  SCHEMA_EVOLVE                                                        │
  │  validate_schema (in-turn feedback before write_file("schema.yaml"))  │
  │  — refine own turn definition with validation feedback                │
  ├═══════════════════════════════════════════════════════════════════════╡
  │  CORE — all agents, always                                            │
  │  read_file, write_file                                                │
  │  — read and write own workspace                                       │
  └───────────────────────────────────────────────────────────────────────┘
```

### 5.1 Capability declaration and enforcement

The agent declares what it needs in `schema.yaml`:

```yaml
capabilities:
  - file_read
  - file_write
  - schema_evolve
  - graph_read      # declared — will fail activation if not yet granted
```

The runtime checks each declared capability against `capabilities.yaml`
(the runtime-maintained grant file in the workspace). If any declared
capability is not granted, activation is rejected with a clear error message
written to the workspace. The agent sees this on its next DEFAULT_SCHEMA
activation and understands it must request the capability first.

### 5.2 The request/grant flow

All via workspace files and events — no out-of-band mechanism:

```
1. Agent writes capability_requests.md to its workspace:
   "I need graph_read to track which modules depend on my signatures.
   Evidence: activations #8, #10, #12 all needed caller context.
   See notes.md entry 2026-03-08."

2. Agent emits RequestCapabilityEvent:
   {capability: "graph_read", evidence_path: "capability_requests.md"}

3. Maintainer agent activates. It reads:
   - The requesting agent's capability_requests.md (via read_agent_workspace)
   - The requesting agent's log.jsonl (stability evidence)
   - The requesting agent's notes.md (context)

4. Maintainer decides. Emits GrantCapabilityEvent or DenyCapabilityEvent.

5. Runtime writes updated capabilities.yaml to the requester's workspace.
   Rebuilds the agent's externals dict for next activation.
```

The policy for what constitutes adequate justification is NOT specified here.
That emerges from what the maintainer agent learns to value.

### 5.3 capabilities.yaml — the grant record

```yaml
# capabilities.yaml — runtime-maintained, agent read-only
version: "1"
agent_id: "agent:events_module_abc123"
granted:
  - file_read
  - file_write
  - schema_evolve
  - graph_read      # added 2026-03-08
history:
  - capability: graph_read
    granted_at: "2026-03-08T10:00Z"
    granted_by: "agent:maintainer_001"
    justification: "Stable file_write over 10 activations; graph_read needed for caller tracking"
```

Readable in the companion sidebar. The full grant history is auditable.


---

## 6. What Is Not Specified

v4 deliberately leaves the following unspecified. The substrate provides the
mechanisms; the bootstrap process determines what goes into them.

**Graph node kinds.** The graph is seeded from code discovery: `CSTNode`
objects become graph nodes, `caller_ids`/`callee_ids` become edges. Beyond
that initial seeding, the bootstrap agents decide what to put in the graph.
An agent that wants to record a relationship adds a node or edge. The concept
document does not name what kinds of nodes or edges should exist.

**Graph edge semantics.** Edges carry a `kind` string and an `attrs` JSON
blob. The agents that create edges define what the kind means. If agents
discover that `kind="tests"` is a useful convention, they adopt it. The
concept document does not dictate edge vocabulary.

**Event taxonomy.** Agents emit events with whatever `event_type` string they
choose. Agents subscribe to whatever event types they find useful. The concept
document does not name the event types the swarm uses.

**Agent taxonomy.** There is no named list of "orchestrator," "editor,"
"reviewer," "maintainer" as prescribed roles. There is one runtime model
(`BootstrapAgent`). What kinds of agents emerge from the bootstrap process —
what roles, what specializations, what hierarchy — is determined by the
bootstrap process, not by this document. The agents' `role.md` files are
where their self-descriptions live, and those are written by the agents.

**Protocol state machines.** Multi-step coordination workflows emerge from
agents subscribing to each other's events. The concept document does not
prescribe which protocols exist. If the swarm finds it needs explicit state
machines to prevent deadlocks, it can build them from the graph and event bus.

**Memory model.** `notes.md` and `log.jsonl` are the suggested defaults.
What memory structures actually prove useful — whether agents converge on
a shared format, invent their own, or use the graph instead of workspace
files — is determined by what works. The concept document does not prescribe it.


---

## 7. The Bootstrap Sequence

### Phase 0: Substrate only

The runtime starts with:
- `CairnWorkspaceService` initialized (stable workspace + per-agent workspaces)
- SQLite property graph initialized (`bootstrap_nodes` + `bootstrap_edges` tables)
- `EventBus` and `EventStore` initialized (v1 components, unchanged)
- `BootstrapExternals` defined: core ops always available (`read_file`,
  `write_file`); all others gated by agent capability set
- Base schema files in `bootstrap/agents/bases/`; capability presets in
  `bootstrap/agents/capabilities/`; seed definitions in `bootstrap/agents/seed/`

Project source is synced into the stable workspace. `discover()` runs,
producing `CSTNode` objects. The runtime seeds the graph with these as nodes
and adds call-relationship edges from `caller_ids` / `callee_ids`.

No agents exist yet. The graph contains only raw code topology.

### Phase 1: First agents — workspace population

`NodeDiscoveredEvent` fires for each code node. For each node, the runtime:

1. Creates a `BootstrapAgent` with `capabilities = {FILE_READ, FILE_WRITE, SCHEMA_EVOLVE}`
2. Creates an empty cairn workspace
3. Checks `bootstrap/agents/seed/` for a matching developer-seeded definition
   - If found: pre-writes `role.md` and `schema.yaml` from the seed
   - If not found: leaves workspace empty → DEFAULT_SCHEMA runs
4. Activates the agent

Each agent runs its first activation (DEFAULT_SCHEMA or seeded schema):
- Reads its source file via the stable workspace fallback
- Writes `role.md`, `notes.md`, `schema.yaml`, `log.jsonl`
- Outputs `"done"`

After Phase 1: every agent has a populated workspace and a `schema.yaml`.
The swarm is alive.

### Phase 2: Agents communicating

Subsequent activations run each agent's own `schema.yaml`. Agents:
- Read `recent_events` and `callers` from the graph in their context pipeline
- Emit events to signal each other (`ContentChangedEvent`, direct messages)
- Write to `notes.md` when they learn something durable
- Request capabilities as they discover they need them

Patterns emerge organically from event subscriptions — no central coordinator.

### Phase 3: Structure accumulates

Recurring patterns crystallize. Agents:
- Add graph edges to record relationships they've verified across many activations
- Evolve `schema.yaml` with richer context steps as they learn what context helps
- Propose new capability presets when they find themselves requesting the same
  combination repeatedly
- Synthesize new `.pym` tools (once TOOL_SYNTHESIZE is granted) when they find
  themselves doing the same multi-step operation repeatedly

The swarm decides what structure is useful. The concept document gets out of
the way.


---

## 8. Developer and Companion Visibility

### 8.1 The companion sidebar as a workspace file viewer

The companion sidebar (Neovim plugin) shows the focused node's agent state.
Because the workspace IS the agent, the sidebar is simply a structured reader
of workspace files — no special protocol, no separate data format:

```
┌───────────────────────────────────────────────────────┐
│ ◈  events_module_agent              [idle]  [↺]       │
│    src/remora/core/events/events.py                   │
│    CAPS: file_r  file_w  graph_r  event_e  schema_e   │
├───────────────────────────────────────────────────────┤
│ ▸ ROLE                                        [edit]  │
│   I maintain the events module. Keeping event type    │
│   signatures stable as the codebase evolves.          │
├───────────────────────────────────────────────────────┤
│ ▸ SCHEMA  5 context steps · 4 tools           [open]  │
│   context: role → notes → source → events → callers  │
│   tools:   write_file  emit_event  graph_add_edge     │
│            graph_neighbors                            │
│   subs:    ContentChangedEvent · DirectMessageEvent   │
├───────────────────────────────────────────────────────┤
│ ▸ NOTES   activation #12                     [open]   │
│   2026-03-08  ContentChangedEvent: 33 importers.      │
│               Signature flagged as frozen.            │
│   2026-03-08  StructuredEvent: 14 variants. Propose   │
│               discriminated union? → todo             │
│                                          [+1 earlier] │
├───────────────────────────────────────────────────────┤
│ ▸ TODO    2 open · 2 done                     [edit]  │
│   ○ Investigate 33-module ContentChangedEvent imports │
│   ○ Propose discriminated union for StructuredEvent   │
│   ● Write role.md  ●  Add graph_neighbors step        │
├───────────────────────────────────────────────────────┤
│ ▸ LOG     12 activations                              │
│   14:32  ContentChanged → done (3 turns)              │
│   09:15  ContentChanged → done (2 turns)              │
│   yesterday  NodeDiscovered → bootstrapped            │
└───────────────────────────────────────────────────────┘
```

| Sidebar section | Source file | Rendering |
|----------------|-------------|-----------|
| Header (caps, status) | `capabilities.yaml` + graph node | Parsed metadata |
| ROLE | `role.md` | Markdown prose, truncated |
| SCHEMA | `schema.yaml` | Parsed: context step names, tool names, sub count |
| NOTES | `notes.md` | Last 2 entries + overflow count |
| TODO | `todo.md` | Parsed `- [ ]` / `- [x]`; interactive |
| LOG | `log.jsonl` | Last 3 lines parsed |

### 8.2 Interactivity

**[edit]** — opens the workspace file in a floating Neovim buffer; save
writes back to the cairn workspace. Available for `role.md`, `todo.md`,
`schema.yaml`.

**[open]** — read-only preview with `e` to switch to edit mode.

**TODO checkboxes** — toggle directly in the sidebar (`<Space>`). Writes
`- [x]` or `- [ ]` to `todo.md`. The agent sees the change on next activation.
Developer and agent share the same task list.

**[↺ refresh]** — re-read all workspace files. Normally happens automatically
after each activation completes (`AgentActivationCompleteEvent`).

### 8.3 Developer correction and inspection

The workspace is always accessible:

| Developer need | Action |
|----------------|--------|
| Understand what an agent does | Read `role.md`, `schema.yaml` |
| Understand what an agent has learned | Read `notes.md`, `log.jsonl` |
| Correct a bad role description | Edit `role.md` via sidebar or direct workspace write |
| Correct a bad schema | Edit `schema.yaml` via sidebar; validated on next load |
| Reset an agent to default | Delete `schema.yaml`; next activation uses DEFAULT_SCHEMA |
| See what an agent is doing now | Read `working_memory.md` |
| Inject a task | Append a `- [ ]` item to `todo.md` |
| Understand the full swarm | `graph_find_nodes(kind="agent.profile")` |

No opaque state. No special debug protocol. The workspace is the agent.


---

## 9. Delivery Plan

Ordered by the core-first priority: get the two-tool loop working before
layering graph, events, and governance on top.

### M0: Core workspace (1–2 days)

The irreducible minimum. After M0, the self-bootstrapping loop can close.

Deliverables:
- `CairnWorkspaceService` integration: per-agent workspace creation,
  stable workspace fallback for `read_file`
- `read_file` and `write_file` as the core externals (always in every
  agent's externals dict, no capability gate)
- `schema.yaml` loading pipeline: read from workspace → parse YAML →
  validate via `AgentSchemaYaml` Pydantic model → convert to `TurnSchema`
- `DEFAULT_SCHEMA` constant
- Schema validation fallback: on load failure, write `schema.error.yaml`
  to workspace and use DEFAULT_SCHEMA
- `validate_schema` tool (in-turn validation feedback, available to all
  agents with SCHEMA_EVOLVE)

Tests: schema.yaml round-trip (write → load → TurnSchema); fallback on
malformed YAML; stable workspace fallback for source file reads.

### M1: Turn executor (2–3 days)

Wire the schema to the LLM.

Deliverables:
- Turn executor: resolve `TurnSchema` → system prompt, context pipeline,
  LLM loop with tools, termination
- `ContextPipeline` step execution: `ToolRef` resolution, `$step_name`
  interpolation, `optional:` handling, `InputGate` pause/resume
- Template variable resolution: `{node.*}`, `{agent.*}`, `{{role}}`,
  `{{notes}}`
- Turn outcome classification: `DONE`, `PARSE_FAILURE`, `CONTEXT_STEP_FAILURE`,
  `MAX_TURNS_EXCEEDED`, `SCHEMA_VALIDATION_ERROR`

Tests: all outcome classes exercised with mock externals; `optional` step
skipping; template variable substitution; `InputGate` in batch mode.

### M2: Self-bootstrapping end-to-end (2–3 days)

The complete loop: new node → DEFAULT_SCHEMA → populated workspace →
subsequent activation uses schema.yaml.

Deliverables:
- `NodeDiscoveredEvent` → agent creation → workspace initialization
- Developer seed check: look for matching file in `bootstrap/agents/seed/`;
  if found, pre-write `role.md` and `schema.yaml`
- Two-activation sequence test: activation 1 writes schema.yaml;
  activation 2 loads and uses it
- `AgentActivationCompleteEvent` emitted after each turn

Tests: full two-activation flow with real (or mocked) LLM; seeded vs.
self-bootstrapped agents; schema.yaml schema version round-trip.

### M3: Graph substrate (2–3 days)

The shared semantic memory. After M3, agents can observe each other via
the graph.

Deliverables:
- SQLite property graph: `bootstrap_nodes` + `bootstrap_edges` tables
  with indexes on `(from_node, kind)` and `(to_node, kind)`
- Code-discovery seeding: `CSTNode` → graph nodes,
  `caller_ids`/`callee_ids` → edges
- `graph_read` externals: `graph_node`, `graph_neighbors`,
  `graph_find_nodes` (gated by GRAPH_READ capability)
- `graph_write` externals: `graph_add_node`, `graph_add_edge`,
  `graph_remove_node`, `graph_remove_edge` (gated by GRAPH_WRITE)

Tests: CRUD, neighborhood queries, index performance, seeding from CSTNode,
capability gating.

### M4: Event bus integration (1–2 days)

Agents communicate. After M4, agents can trigger each other.

Deliverables:
- `emit_event` and `read_recent_events` externals wired to `EventBus`
  + `EventStore` (v1 components, unchanged)
- Causal envelope: every `BootstrapEvent` carries `event_id`,
  `causal_parent_id`, `depth`, `agent_id`, `timestamp`, `payload`
- Depth enforcement: runtime rejects emission when `depth > max_depth`
- Subscription wiring: `schema.yaml` subscriptions → `SubscriptionRegistry`
  entries on agent creation

Tests: event round-trip; causal depth increment; depth limit rejection;
subscription matching.

### M5: Capability ladder (1–2 days)

Agents earn capabilities. After M5, the full governance model is live.

Deliverables:
- `Capability` enum and `capabilities.yaml` runtime-write mechanism
- `RequestCapabilityEvent` / `GrantCapabilityEvent` / `DenyCapabilityEvent`
- Capability validation on schema.yaml load (declared vs. granted)
- Maintainer seed agent (`bootstrap/agents/seed/maintainer.yaml`)
  with PRIVILEGED capability, pre-seeded workspace
- Capability preset files in `bootstrap/agents/capabilities/`

Tests: request/grant round-trip; activation rejection on undeclared capability;
maintainer agent grant flow.

### M6: Companion sidebar (2–3 days)

The workspace is visible. After M6, developers can observe and interact
with the swarm from Neovim.

Deliverables:
- Sidebar workspace file reader: reads `role.md`, `schema.yaml`,
  `notes.md`, `log.jsonl`, `todo.md`, `capabilities.yaml`
- Each file → sidebar section with the layout shown in §8
- `todo.md` interactive checkboxes (toggle → write back to workspace)
- `[edit]` / `[open]` for `role.md`, `schema.yaml`, `todo.md`
- Auto-refresh on `AgentActivationCompleteEvent`
- `remora inspect agent <node_id>` CLI command (wraps the same reads)

Tests: sidebar renders all sections; todo toggle writes back; refresh
on activation event.

### M7: Adapter integration (1–2 days)

Plugs into the existing v1 runtime path.

Deliverables:
- Feature flag: `REMORA_PHASE2_RUNTIME=1`
- When set: route `NodeDiscoveredEvent` and content-change activations
  through the bootstrap turn executor instead of v1 `execute_agent_turn()`
- `HumanChatEvent` from LSP → triggers bootstrap turn on focused agent
- Parallel event logging: bootstrap events emitted alongside legacy v1 events
- Rustworkx added as optional dependency; `trace_causal_chain` external
  for algorithmic graph queries when needed (M7+)

Tests: end-to-end through LSP adapter with mock LLM; `remora swarm start`
with flag set; parallel event log integrity.

---

*This document supersedes v3 as the implementation guide for Phase 2.*
*The core is two tools and one file convention. Everything built on top*
*of that core — graph structure, event taxonomy, agent roles, memory*
*models — is determined by the bootstrap process, not by this document.*

