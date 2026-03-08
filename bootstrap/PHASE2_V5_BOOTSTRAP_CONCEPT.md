# Phase 2 Bootstrap v5: Two Primitives

> Everything an agent does is a READ or a WRITE.
>
> READ(channel, selector) — pull data from somewhere.
> WRITE(channel, data)    — push data somewhere.
>
> The channel determines what's stored and what side effects occur.
> The capability tier determines which channels the agent can reach.
> Everything else — graph access, events, tool synthesis, governance —
> is composed from these two primitives applied to different channels.

---

## Table of Contents

1. [The Two Primitives](#1-the-two-primitives)
   READ and WRITE as the irreducible core. The four channels. How every
   agent operation is a READ or WRITE on one of them.

2. [The Capability Ladder](#2-the-capability-ladder)
   Channel access as capability. Which tiers unlock which channels.
   CORE (workspace only) is sufficient to close the bootstrapping loop.

3. [Composition: Building Everything From Two Primitives](#3-composition-building-everything-from-two-primitives)
   How read_file, write_file, graph_*, emit_event, and subscribe all
   reduce to READ or WRITE on a channel. How schema.yaml is itself just
   WRITE(workspace).

4. [The Workspace Channel](#4-the-workspace-channel)
   Always available. What lives here. The workspace as the agent's
   identity, memory, and self-definition — all expressed through READ
   and WRITE on a single channel.

5. [schema.yaml — A Turn as a Text File](#5-schemayaml--a-turn-as-a-text-file)
   The agent's turn definition stored as YAML in its workspace. Format,
   template variables, composition via `extends`. How the runtime
   resolves a schema into a TurnSchema for execution.

6. [The Graph and Event Channels](#6-the-graph-and-event-channels)
   Shared state (graph) and shared notification (events) as two more
   channels unlocked by capability. The key semantic difference: WRITE
   to the event channel notifies subscribers; WRITE to the graph does not.

7. [What Is Not Specified](#7-what-is-not-specified)
   What the agents write into those channels — the graph topology, event
   taxonomy, protocol structure — is not specified here. It emerges.

8. [The Bootstrap Sequence](#8-the-bootstrap-sequence)
   From an empty workspace to a self-defining agent, using only CORE
   channel access. How the loop closes in one activation.

9. [Developer and Companion Visibility](#9-developer-and-companion-visibility)
   The workspace channel as the developer interface. The companion sidebar
   as a workspace reader. Correction, inspection, injection — all via
   READ and WRITE on the workspace channel.

10. [Delivery Plan](#10-delivery-plan)
    Milestones ordered by channel: workspace first, then graph, then
    events, then subscriptions.

---

## 1. The Two Primitives

Every operation an agent performs is one of two things:

```
READ(channel, selector)  →  data
WRITE(channel, data)     →  ok | id | error
```

**READ** pulls data from a channel. **WRITE** pushes data to a channel.
The channel determines where data lives and what happens when it's written.

### The four channels

| Channel | READ returns | WRITE stores | WRITE side effect |
|---------|-------------|--------------|-------------------|
| `workspace` | file content (string) | file content (durable) | none |
| `graph` | nodes / edges (JSON) | nodes / edges (durable) | none |
| `events` | event history (list) | event record (durable) | **notifies subscribers** |
| `subscriptions` | trigger patterns | trigger patterns | **reconfigures who gets triggered** |

The only semantic difference between channels is the WRITE side effect.
Writing to `workspace` or `graph` stores data silently. Writing to `events`
stores data *and* triggers any agents subscribed to that event type. Writing
to `subscriptions` is privileged and reconfigures the entire trigger routing.

### The concrete operations

Every named external in the system is a READ or WRITE on one of these channels:

```
READ  (workspace,  path)                 →  read_file(path)
WRITE (workspace,  path, content)        →  write_file(path, content)

READ  (graph,      node_id)              →  graph_node(node_id)
READ  (graph,      {kind, attrs, ...})   →  graph_find_nodes(...)
READ  (graph,      {node_id, direction}) →  graph_neighbors(...)
WRITE (graph,      node attrs)           →  graph_add_node(attrs)
WRITE (graph,      edge {from,to,kind})  →  graph_add_edge(...)
WRITE (graph,      remove node_id)       →  graph_remove_node(node_id)

READ  (events,     {node_id, limit})     →  read_recent_events(...)
WRITE (events,     {type, payload})      →  emit_event(type, payload)

WRITE (subscriptions, pattern)           →  update_subscription(pattern)
```

There are no other primitive operations. Tool synthesis (writing `.pym` files
to the workspace's `tools/` directory) is WRITE(workspace, tools/name.pym).
Schema evolution (writing `schema.yaml`) is WRITE(workspace, schema.yaml).
Capability requests (writing `capability_requests.md`) are WRITE(workspace, ...).
Reading the project source is READ(workspace, ...) via the stable workspace
fallback.

Everything is a READ or a WRITE. The channel is the variable.

---

## 2. The Capability Ladder

Capability is channel access. Every agent always has READ and WRITE on the
`workspace` channel — that's the core. All other channel access is earned.

```
  ┌───────────────────────────────────────────────────────────────────┐
  │  TIER 5  — WRITE(subscriptions)                                   │
  │  Reconfigure who gets triggered by what. Substrate governance.    │
  ├───────────────────────────────────────────────────────────────────┤
  │  TIER 4  — WRITE(workspace/tools/*.pym)                           │
  │  Synthesize new named externals. Extend the primitive set itself. │
  ├───────────────────────────────────────────────────────────────────┤
  │  TIER 3  — WRITE(graph)                                           │
  │  Author the shared semantic structure. Add and remove nodes/edges.│
  ├───────────────────────────────────────────────────────────────────┤
  │  TIER 2  — WRITE(events)                                          │
  │  Participate in swarm coordination. Notify other agents.          │
  ├───────────────────────────────────────────────────────────────────┤
  │  TIER 1  — READ(graph) + READ(events)                             │
  │  Observe shared state. Know what others have built and said.      │
  ├═══════════════════════════════════════════════════════════════════╡
  │  CORE    — READ(workspace) + WRITE(workspace)                     │
  │  All agents. Always. From activation 1.                           │
  │  Sufficient to close the self-bootstrapping loop.                 │
  └───────────────────────────────────────────────────────────────────┘
```

### Why CORE is sufficient for bootstrapping

With only READ(workspace) and WRITE(workspace), an agent can:

1. Read its own role and source file → understand its responsibility
2. Write `role.md` → define its own identity
3. Write `notes.md`, `log.jsonl` → maintain persistent memory
4. Write `schema.yaml` → redefine its own next turn

Point 4 is what closes the loop. The agent rewrites its own behavior by
writing a file. The runtime reads `schema.yaml` before every activation.
No other channel is needed to bootstrap.

Higher tiers add *reach* — the ability to observe and influence other agents.
But they add nothing to the agent's ability to define and improve itself.

### Earning tiers

Capability tiers are granted after demonstrating stable behavior at the
current level. The request/grant mechanism itself is composed from primitives:

- WRITE(workspace, "capability_requests.md", justification)
- WRITE(events, {type: "RequestCapabilityEvent", capability: "..."})
- [maintainer evaluates via READ(workspace) of requester's files]
- WRITE(events, {type: "GrantCapabilityEvent", to: "...", capability: "..."})
- [runtime updates capabilities.yaml via WRITE(workspace, "capabilities.yaml")]

The governance mechanism is entirely self-describing through the same two
primitives.


---

## 3. Composition: Building Everything From Two Primitives

The power of READ and WRITE as primitives is that complex behaviors compose
from sequences of them — none require new primitive operations.

### Schema evolution

An agent that wants to change its own behavior next activation:

```
WRITE(workspace, "schema.yaml", new_yaml_content)
```

That's it. On the next activation, the runtime reads `schema.yaml` and uses
it. No special `emit_schema` primitive is needed — though a `validate_schema`
helper (itself a read-and-validate) is available for in-turn feedback before
writing.

### Working memory

An agent thinking through a complex problem across multiple turns:

```
READ (workspace, "working_memory.md")   → previous analysis
WRITE(workspace, "working_memory.md",   → current analysis
      updated_analysis)
```

### Cross-agent inspection (maintainer reads requester)

```
READ(workspace[requester], "capability_requests.md")  → justification
READ(workspace[requester], "log.jsonl")               → stability evidence
READ(workspace[requester], "notes.md")                → context
```

Cross-workspace reads require TIER 1+ (the maintainer reads other agents'
workspaces via a scoped READ that the capability system gates).

### Capability request flow (all composed from primitives)

```
requester: WRITE(workspace, "capability_requests.md", justification)
requester: WRITE(events,    {type: "RequestCapabilityEvent", ...})
maintainer: READ(workspace[requester], "capability_requests.md")
maintainer: READ(workspace[requester], "log.jsonl")
maintainer: WRITE(events,  {type: "GrantCapabilityEvent", ...})
runtime:    WRITE(workspace[requester], "capabilities.yaml", updated_grants)
```

### Tool synthesis

An agent with TIER 4 access creating a new named external:

```
WRITE(workspace, "tools/score_docstring_alignment.pym", pym_source)
```

The runtime's tool discovery (`discover_grail_tools()`) finds the new `.pym`
file in the agent's workspace on the next activation and adds it to the
available externals. A new READ or WRITE operation has been created from the
existing ones.

### The `schema.yaml` context pipeline as a READ sequence

A context pipeline is just an ordered set of READ operations whose outputs
feed into each other:

```
READ(workspace,  "role.md")              → $role
READ(workspace,  "notes.md")             → $notes   (optional)
READ(workspace,  "{node.file_path}")     → $source   (stable fallback)
READ(events,     {node_id, limit: 10})  → $recent_events
READ(graph,      {node_id, dir: "in"})  → $callers
```

The LLM then receives all of `$role`, `$notes`, `$source`, `$recent_events`,
`$callers` as context. Its tools are named WRITE (and READ) operations it
can call during the turn. The whole turn is a structured composition of
READ and WRITE operations.


---

## 4. The Workspace Channel

The workspace channel is a Cairn-backed key-value store that behaves like a
filesystem: paths map to string content. Backed by a SQLite `.db` file at
`.remora/<swarm_id>/agents/<agent_id>/workspace.db`.

All agents have unrestricted READ and WRITE on their own workspace from
activation 1. The stable workspace (`.remora/<swarm_id>/stable.db`) contains
the synced project source. READ on the workspace channel falls back to the
stable workspace automatically — so `read_file("src/remora/core/events.py")`
just works.

### What lives in the workspace

```
  workspace channel contents

  role.md                ← WRITE on activation 1. Who this agent is.
  schema.yaml            ← WRITE when evolving turn definition.
  capabilities.yaml      ← WRITE by runtime only. What channels are open.

  notes.md               ← WRITE to accumulate knowledge across activations.
  log.jsonl              ← WRITE one line per activation.
  todo.md                ← WRITE for pending tasks. READ by developer too.
  working_memory.md      ← WRITE for current-turn scratchpad. Overwritten.

  tools/*.pym            ← WRITE with TIER 4. New named externals.
  capability_requests.md ← WRITE to request tier promotion.
```

### The workspace IS the agent

```
What the agent IS    →  READ(workspace, "role.md")
                        READ(workspace, "schema.yaml")

What the agent KNOWS →  READ(workspace, "notes.md")
                        READ(workspace, "log.jsonl")

What the agent WANTS →  READ(workspace, "todo.md")

What the agent CAN   →  READ(workspace, "capabilities.yaml")
```

Reading an agent's workspace tells you everything about it. There is no
hidden state. The companion sidebar, developer inspection tools, and the
agent's own context pipeline all use the same READ(workspace) calls.


---

## 5. schema.yaml — A Turn as a Text File

`schema.yaml` is the agent's turn definition. It is a plain text file stored
in the workspace channel — created and updated by the agent via WRITE, loaded
by the runtime via READ before each activation.

If `schema.yaml` is absent, the runtime uses DEFAULT_SCHEMA: a minimal turn
that gives the agent READ(workspace) + WRITE(workspace) and prompts it to
populate its workspace and write `schema.yaml`. After one activation with
DEFAULT_SCHEMA, the loop closes.

### The format

```yaml
version: "1"
name: events_module_agent

# Channels this turn needs. Runtime validates against capabilities.yaml.
capabilities:
  - file_read       # READ(workspace)
  - file_write      # WRITE(workspace)
  - graph_read      # READ(graph)
  - event_emit      # WRITE(events)

# System prompt. {{role}} and {{notes}} are inlined from workspace READs.
system: |
  You are responsible for {node.full_name}.
  {{role}}
  Keep notes.md updated. Append to log.jsonl every activation.

# Context pipeline: ordered READ operations before the LLM turn.
# Each step's output stored as $name for use in subsequent steps.
context:
  - name: role
    tool: read_file                       # READ(workspace, "role.md")
    args: {path: role.md}

  - name: notes
    tool: read_file                       # READ(workspace, "notes.md")
    args: {path: notes.md}
    optional: true

  - name: source
    tool: read_file                       # READ(workspace, path) → stable fallback
    args: {path: "{node.file_path}"}

  - name: callers
    tool: graph_neighbors                 # READ(graph, {node_id, direction})
    args: {node_id: "{node.id}", direction: in}

  - name: recent_events
    tool: read_recent_events              # READ(events, {node_id})
    args: {node_id: "{node.id}", limit: 10}

# Named operations available to the LLM during the turn.
tools:
  - write_file        # WRITE(workspace, ...)
  - emit_event        # WRITE(events, ...)
  - graph_add_edge    # WRITE(graph, edge)

subscriptions:
  - event_type: ContentChangedEvent
    node_id: "{node.id}"
  - event_type: DirectMessageEvent
    to_agent: "{agent.id}"

max_turns: 5
termination: "done"
```

### Template variables

Resolved at activation time before the context pipeline runs:

| Variable | Resolves to |
|----------|------------|
| `{node.id}` | Code node identifier |
| `{node.file_path}` | File this agent is responsible for |
| `{node.full_name}` | Fully qualified name |
| `{node.kind}` | Node kind (e.g. `python:function`) |
| `{agent.id}` | Runtime agent identifier |
| `{{role}}` | Contents of `role.md` inlined (READ then substitute) |
| `{{notes}}` | Contents of `notes.md` inlined (READ then substitute) |

### Composition via `extends`

A schema can extend a base schema file from `bootstrap/agents/bases/`:

```yaml
extends: code_agent       # inherits base context steps and tools

name: docstring_reviewer

context:
  append:                 # adds steps AFTER the base pipeline
    - name: current_doc
      tool: read_file
      args: {path: "current_docstring.txt"}

tools:
  append:
    - rewrite_docstring   # WRITE(workspace, ...) specialized tool

max_turns: 3
```

Single inheritance only. One `extends`, max two levels deep.

### Validation

When schema.yaml fails to parse or validate, the runtime:
1. Stores the failed schema as `schema.error.yaml` in the workspace
2. Runs DEFAULT_SCHEMA instead (which READs `schema.error.yaml` as context
   so the agent can see and fix its mistake)

A `validate_schema(yaml_content)` tool (READ-then-validate) is available
for in-turn feedback before writing.


---

## 6. The Graph and Event Channels

These channels are shared across all agents. They are what turns a collection
of isolated agents into a coordinating swarm.

### The graph channel

A directed property graph stored in SQLite:

```sql
CREATE TABLE bootstrap_nodes (
    node_id TEXT PRIMARY KEY,
    kind    TEXT,
    attrs   TEXT   -- JSON
);
CREATE TABLE bootstrap_edges (
    edge_id   TEXT PRIMARY KEY,
    kind      TEXT,
    from_node TEXT REFERENCES bootstrap_nodes(node_id),
    to_node   TEXT REFERENCES bootstrap_nodes(node_id),
    attrs     TEXT   -- JSON
);
```

Seeded at startup from code discovery: `CSTNode` objects become nodes;
`caller_ids`/`callee_ids` become edges. Beyond that, agents decide what
to add.

**READ(graph)** operations — available at TIER 1:
- `graph_node(node_id)` — get one node by ID
- `graph_neighbors(node_id, direction, kind?)` — adjacent nodes/edges
- `graph_find_nodes(kind?, attrs?)` — search by kind or attribute filter

**WRITE(graph)** operations — available at TIER 3:
- `graph_add_node(kind, attrs)` — create a node, returns `node_id`
- `graph_add_edge(from, to, kind, attrs?)` — create an edge
- `graph_remove_node(node_id)` — delete a node and its edges
- `graph_remove_edge(edge_id)` — delete an edge

All READ returns are JSON strings. WRITE takes JSON-serialisable arguments.
No live graph handles leak to agents — only data flows through the externals.

For algorithmic graph queries (cycle detection, shortest path, transitive
closure) at TIER 3+, a Rustworkx subgraph can be loaded on demand from
SQLite. SQLite is the source of truth; Rustworkx is an optional query engine.

### The event channel

An append-only event log backed by v1's `EventStore` (SQLite, WAL mode,
unchanged). Every event carries a causal envelope:

```python
@dataclass
class BootstrapEvent:
    event_id:        str      # unique identifier
    event_type:      str      # e.g. "ContentChangedEvent"
    payload:         dict
    agent_id:        str      # who emitted it
    causal_parent_id: str | None  # which event caused this activation
    depth:           int      # causal chain depth (enforced limit)
    timestamp:       float
```

**READ(events)** — available at TIER 1:
- `read_recent_events(node_id?, event_type?, limit?)` — query event history

**WRITE(events)** — available at TIER 2:
- `emit_event(event_type, payload)` — store event + notify subscribers

The critical semantic distinction: WRITE(graph) is silent — nothing is
triggered. WRITE(events) notifies all agents whose `schema.yaml` subscription
patterns match the emitted event type and attributes. This is how agents
coordinate without polling.

Subscriptions are declared in `schema.yaml` (not called at runtime). They
are registered with v1's `SubscriptionRegistry` when the agent is created
or when `schema.yaml` is updated. Reconfiguring subscriptions mid-stream
(WRITE(subscriptions)) is TIER 5.

The depth field prevents infinite activation loops: each event emitted in
response to an incoming event has `depth = parent.depth + 1`. The runtime
rejects WRITE(events) calls when `depth > max_depth`.


---

## 7. What Is Not Specified

The two primitives and four channels are specified. What agents put into
those channels is not.

**Graph topology.** No named node kinds beyond the initial code-discovery
seeding (`CSTNode` → node). No named edge kinds. Agents write whatever
nodes and edges they find useful. The graph vocabulary emerges from what
agents consistently create and query.

**Event taxonomy.** No prescribed event type names. An agent emits
`WRITE(events, {type: "SignatureChangedEvent", ...})` because it finds
that useful. Other agents subscribe to it because they find that useful.
The event vocabulary emerges from what agents consistently emit and receive.

**Agent taxonomy.** One runtime model (`BootstrapAgent`). What roles emerge
— what kinds of agents exist, what they specialize in, what hierarchy they
form — is determined by what agents write into their `role.md` and `schema.yaml`
files and how they respond to each other's events.

**Protocol structure.** Multi-step coordination emerges from subscription
chains. An agent that emits event A causes agents subscribed to A to run,
which may emit B, which causes others to run. No state machine is prescribed.
If the swarm discovers it needs deadlock prevention, it builds it from the
graph and event channels.

**Memory model.** `notes.md` and `log.jsonl` are strong conventional defaults,
but what memory structures agents actually converge on — whether they use
workspace files, graph nodes, event streams, or some combination — is
determined by what works.


---

## 8. The Bootstrap Sequence

### Phase 0: Channels initialized, no agents

```
Workspace channel:  CairnWorkspaceService up; stable workspace synced
Graph channel:      SQLite tables created; CSTNode objects seeded as nodes
Event channel:      EventBus + EventStore up (v1, unchanged)
Subscription:       SubscriptionRegistry ready
```

The graph contains a raw call graph from tree-sitter. No agents exist.

### Phase 1: First activation — CORE only

`NodeDiscoveredEvent` fires per code node. For each:

1. Runtime creates `BootstrapAgent` with `capabilities = {READ(workspace), WRITE(workspace)}`
2. Runtime creates empty workspace for the agent
3. If a seed definition exists in `bootstrap/agents/seed/`: pre-WRITE `role.md`
   and `schema.yaml` to workspace. Otherwise: empty workspace → DEFAULT_SCHEMA runs.
4. Activate.

**DEFAULT_SCHEMA turn (empty workspace case):**

```
Context pipeline:
  READ(workspace, "role.md")             → "" (optional, file absent)
  READ(workspace, "{node.file_path}")    → source code (stable fallback)

LLM receives source, decides what it's responsible for.

LLM calls:
  WRITE(workspace, "role.md",       "I am responsible for...")
  WRITE(workspace, "notes.md",      "# Notes\n## [date]\nInitial note...")
  WRITE(workspace, "schema.yaml",   "version: '1'\n...")
  WRITE(workspace, "log.jsonl",     "{...first activation record...}\n")

LLM outputs: "done"
```

After phase 1: every agent has a populated workspace with `schema.yaml`.
The swarm is alive and self-defined.

### Phase 2: Richer turns — tiers earned

Subsequent activations run each agent's own `schema.yaml`. Context pipelines
now include READ(graph) and READ(events) as agents earn TIER 1. Agents
emit WRITE(events) as they earn TIER 2.

No central coordinator. Coordination emerges from subscription chains:
an agent's WRITE(events) activates all agents whose subscription patterns match.

### Phase 3: Structure accumulates

Agents WRITE(graph) as they earn TIER 3 — recording relationships they've
verified. They WRITE(workspace, "tools/...") as they earn TIER 4 — composing
new named operations from existing ones. The swarm builds its own vocabulary.


---

## 9. Developer and Companion Visibility

The workspace channel is the developer interface. Because all agent state
is in the workspace (accessible via READ), and all developer interactions
write back via WRITE, there is no separate observation protocol.

### The companion sidebar as a READ sequence

The companion sidebar (Neovim plugin) is a structured display of workspace
READs for the focused agent:

```
┌───────────────────────────────────────────────────────┐
│ ◈  events_module_agent              [idle]  [↺]       │
│    src/remora/core/events/events.py                   │
│    CAPS: workspace  graph_r  event_e                  │
├───────────────────────────────────────────────────────┤
│ ▸ ROLE                                        [edit]  │
│   READ(workspace, "role.md") →                        │
│   I maintain the events module. Keeping event type    │
│   signatures stable as the codebase evolves.          │
├───────────────────────────────────────────────────────┤
│ ▸ SCHEMA  5 reads · 3 writes              [open]      │
│   READ(workspace, "role.md")                          │
│   READ(workspace, "notes.md")                         │
│   READ(workspace, "{node.file_path}")                 │
│   READ(graph, {node_id, direction: in})               │
│   READ(events, {node_id, limit: 10})                  │
│   tools: WRITE(workspace) · WRITE(events) · WRITE(graph) │
├───────────────────────────────────────────────────────┤
│ ▸ NOTES                                       [open]  │
│   READ(workspace, "notes.md") →                       │
│   2026-03-08  ContentChangedEvent: 33 importers.      │
│               Signature flagged as frozen.            │
├───────────────────────────────────────────────────────┤
│ ▸ TODO                                        [edit]  │
│   READ(workspace, "todo.md") →                        │
│   ○ Investigate 33-module ContentChangedEvent imports │
│   ○ Propose discriminated union for StructuredEvent   │
├───────────────────────────────────────────────────────┤
│ ▸ LOG                                                 │
│   READ(workspace, "log.jsonl") →                      │
│   14:32  ContentChanged → done (3 turns)              │
│   09:15  ContentChanged → done (2 turns)              │
└───────────────────────────────────────────────────────┘
```

Every section is a READ(workspace) call. The sidebar labels are
documentation for the reader; the operations are always READ.

### Developer operations — all composed from READ and WRITE

| Developer need | Operation |
|----------------|-----------|
| Understand what an agent does | READ(workspace, "role.md") + READ(workspace, "schema.yaml") |
| Understand what an agent has learned | READ(workspace, "notes.md") + READ(workspace, "log.jsonl") |
| Correct a bad role | WRITE(workspace, "role.md", corrected_content) |
| Correct a bad schema | WRITE(workspace, "schema.yaml", corrected_yaml) |
| Reset an agent | DELETE(workspace, "schema.yaml") → runtime falls back to DEFAULT_SCHEMA |
| Inject a task | WRITE(workspace, "todo.md", appended_task) |
| Inspect all agents | READ(graph, {kind: "agent.profile"}) |
| Inject a new definition | WRITE(workspace[agent], "schema.yaml", seed_content) |

The companion sidebar's interactive `todo.md` checkboxes are WRITE(workspace)
calls triggered by the developer. The agent sees the change on next activation.


---

## 10. Delivery Plan

Milestones follow the channel order: workspace first (the CORE), then graph,
then events, then subscriptions. Each milestone delivers a working system —
not scaffolding for the next one.

### M0: Workspace channel (1–2 days)

The CORE. After M0, an agent can run DEFAULT_SCHEMA, populate its workspace,
and write `schema.yaml`. The self-bootstrapping loop is closed.

Deliverables:
- `CairnWorkspaceService` integration: per-agent workspace creation, stable
  workspace fallback in READ
- `read_file` and `write_file` as always-available externals (no capability gate)
- `schema.yaml` load pipeline: READ(workspace) → parse YAML →
  `AgentSchemaYaml.model_validate()` → convert to `TurnSchema`
- `schema.error.yaml` fallback: on parse/validation failure, WRITE error file,
  run DEFAULT_SCHEMA
- `validate_schema` tool: READ-and-validate for in-turn feedback
- `DEFAULT_SCHEMA` constant

Tests: schema.yaml write → load → TurnSchema round-trip; stable workspace
fallback; validation error fallback path.

### M1: Turn executor (2–3 days)

Wire the schema to the LLM. After M1, agents run real turns.

Deliverables:
- Turn executor: resolve TurnSchema → system prompt, context pipeline,
  LLM loop, termination
- Context pipeline: step-by-step READ sequence; `$step_name` interpolation;
  `optional:` skipping; `InputGate` pause/resume
- Template variable resolution: `{node.*}`, `{agent.*}`, `{{role}}`, `{{notes}}`
- Turn outcome classification: DONE, PARSE_FAILURE, CONTEXT_STEP_FAILURE,
  MAX_TURNS_EXCEEDED

Tests: all outcomes; optional step skipping; template substitution;
InputGate in batch mode.

### M2: Self-bootstrapping end-to-end (1–2 days)

The complete workspace-only loop. After M2, a real agent (or mocked LLM)
bootstraps itself from an empty workspace.

Deliverables:
- `NodeDiscoveredEvent` → agent creation → workspace initialization
- Developer seed check: if `bootstrap/agents/seed/<match>.yaml` exists,
  WRITE `role.md` and `schema.yaml` to workspace before first activation
- `AgentActivationCompleteEvent` after each turn
- Two-activation sequence: activation 1 writes schema.yaml;
  activation 2 loads and uses it

Tests: full two-activation flow; seeded vs. self-bootstrapped paths;
schema.yaml version field preserved.

### M3: Graph channel (2–3 days)

Shared semantic memory. After M3, agents can observe each other's structure.

Deliverables:
- SQLite property graph: `bootstrap_nodes` + `bootstrap_edges` with indexes
- Code-discovery seeding: CSTNode → nodes, caller/callee → edges
- READ(graph): `graph_node`, `graph_neighbors`, `graph_find_nodes`
  (gated by TIER 1)
- WRITE(graph): `graph_add_node`, `graph_add_edge`, `graph_remove_*`
  (gated by TIER 3)

Tests: CRUD; neighborhood queries; index performance; capability gating.

### M4: Event channel (1–2 days)

Shared notification. After M4, agents coordinate.

Deliverables:
- READ(events): `read_recent_events` wired to `EventStore` (gated by TIER 1)
- WRITE(events): `emit_event` wired to `EventBus` + `EventStore` (gated by TIER 2)
- Causal envelope on every `BootstrapEvent`
- Depth enforcement: reject WRITE(events) when `depth > max_depth`
- Subscription wiring: `schema.yaml` subscriptions → `SubscriptionRegistry`

Tests: event round-trip; causal depth enforcement; subscription matching.

### M5: Capability governance (1–2 days)

Tiers earned. After M5, the full ladder is live.

Deliverables:
- `Capability` enum and `capabilities.yaml` runtime-write mechanism
- `RequestCapabilityEvent` / `GrantCapabilityEvent` / `DenyCapabilityEvent`
- Tier validation on schema.yaml load: declared capabilities ⊆ granted set
- Maintainer seed agent (`bootstrap/agents/seed/maintainer.yaml`) with TIER 5
- Capability preset files in `bootstrap/agents/capabilities/`

Tests: request/grant round-trip; activation rejection on tier violation;
maintainer agent grant flow.

### M6: Companion sidebar (2–3 days)

Workspace visible to the developer. After M6, the workspace channel is
a live developer interface.

Deliverables:
- Sidebar workspace reader: READ(workspace) for each standard file →
  renders ROLE, SCHEMA, NOTES, TODO, LOG sections
- SCHEMA section displays the context pipeline as a READ sequence summary
- Interactive todo.md: toggle → WRITE(workspace, "todo.md", updated)
- `[edit]` / `[open]` for role.md, schema.yaml, todo.md
- Auto-refresh on `AgentActivationCompleteEvent`
- `remora inspect agent <node_id>` CLI

Tests: all sidebar sections render; todo toggle WRITE; auto-refresh.

### M7: Adapter integration (1–2 days)

Plugs into the v1 runtime path.

Deliverables:
- Feature flag: `REMORA_PHASE2_RUNTIME=1`
- Route activations through bootstrap turn executor when flag is set
- `HumanChatEvent` from LSP → bootstrap turn on focused agent
- Parallel event logging alongside v1 events
- Rustworkx as optional dependency for algorithmic READ(graph) queries

Tests: end-to-end through LSP adapter; `remora swarm start` with flag;
parallel event log integrity.

---

*This document supersedes v4 as the implementation guide for Phase 2.*
*The two primitives — READ and WRITE on four channels — compose into*
*every agent operation. The capability ladder is channel access.*
*What agents put into those channels is determined by the bootstrap*
*process, not by this document.*

