# Phase 2 Bootstrap v6: Primitives All the Way Down

> Two primitives. Three stores. One file format.
>
> read(store, selector)    →  value
> write(store, key, value) →  ok
>
> Every agent operation — reading workspace files, querying the graph,
> emitting events, synthesizing new tools — is a read or write on one of
> three stores: workspace, graph, events.
>
> All tools the agent can call are Grail .pym scripts. The system provides
> primitive .pym tools (one per named operation). Agents compose and extend
> them by writing new .pym tools into their own workspace. The only Python
> is the absolute bedrock: six functions that touch the databases directly.

---

## Table of Contents

1. [The Stack](#1-the-stack)
   Three layers: LLM calls .pym tools → .pym tools call Python bedrock →
   bedrock touches SQLite. The six bedrock functions. Why nothing above
   the bedrock layer needs to be Python.

2. [The Two Primitives](#2-the-two-primitives)
   read(store, selector) and write(store, key, value). How every named
   operation reduces to one of these. The only semantic difference between
   stores: write to the event store notifies subscribers.

3. [The Three Stores](#3-the-three-stores)
   Workspace (Cairn key-value, per-agent). Graph (SQLite directed property
   graph, shared). Events (SQLite append-only log, shared, notifying).

4. [The System Tools](#4-the-system-tools)
   The primitive .pym files in bootstrap/tools/. One tool per named
   operation. Each declares @external on the bedrock. Discovery via
   discover_grail_tools().

5. [The Workspace as Agent Identity](#5-the-workspace-as-agent-identity)
   What lives in every agent's workspace. Contractual files the runtime
   reads. Conventional files the agent creates. The workspace as the
   complete description of what an agent is and knows.

6. [schema.yaml — A Turn as a Text File](#6-schemayaml--a-turn-as-a-text-file)
   The turn definition stored in the workspace. Format, template variables,
   the context pipeline as an ordered read sequence. Composition via extends.

7. [Tool Synthesis: Composing New Primitives](#7-tool-synthesis-composing-new-primitives)
   Agents write .pym files into workspace/tools/. Same architecture as
   system tools. Discovered alongside them. New named operations built
   from existing ones — composition all the way up.

8. [What Is Not Specified](#8-what-is-not-specified)
   Graph topology, event taxonomy, agent roles, protocol structure,
   memory model. These emerge from what agents read and write.

9. [The Bootstrap Sequence](#9-the-bootstrap-sequence)
   From empty stores to a self-defining, coordinating swarm — using
   only the two primitives and the .pym tool architecture.

10. [Delivery Plan](#10-delivery-plan)
    Ordered by layer: bedrock first, then system tools, then turn
    executor, then self-bootstrapping loop, then companion visibility.

---

## 1. The Stack

```
┌─────────────────────────────────────────────────────────────────────┐
│  LLM                                                                │
│  Receives context assembled from reads. Calls named tools.          │
│  Outputs the termination string when done.                          │
├─────────────────────────────────────────────────────────────────────┤
│  .pym tools  (Grail scripts)                                        │
│  System tools:  bootstrap/tools/*.pym                               │
│  Agent tools:   workspace/tools/*.pym                               │
│  Declare @external on bedrock functions. Grail compiler enforces    │
│  nothing else is reachable. Discovered by discover_grail_tools().   │
├─────────────────────────────────────────────────────────────────────┤
│  Python bedrock  (six functions, never exposed to agents directly)  │
│  _cairn_read(path)          _cairn_write(path, content)             │
│  _graph_read(selector)      _graph_write(op, data)                  │
│  _event_read(selector)      _event_write(event_type, payload)       │
├─────────────────────────────────────────────────────────────────────┤
│  SQLite                                                             │
│  workspace.db  (per-agent Cairn store)                              │
│  bootstrap_graph.db  (shared property graph)                        │
│  event_store.db  (shared append-only log, WAL mode)                 │
└─────────────────────────────────────────────────────────────────────┘
```

### The bedrock

The bedrock is the only Python in the system that agents cannot see or
modify. It is six functions that talk to three SQLite databases:

```python
# Workspace channel
def _cairn_read(path: str) -> str:
    """Read a file from the agent's cairn workspace.
    Falls back to the stable workspace if not found."""

def _cairn_write(path: str, content: str) -> None:
    """Write a file to the agent's cairn workspace."""

# Graph channel
def _graph_read(selector: dict) -> str:
    """Query the shared graph. Returns JSON."""

def _graph_write(op: str, data: dict) -> str:
    """Mutate the shared graph. Returns JSON with generated IDs."""

# Event channel
def _event_read(selector: dict) -> str:
    """Read from the shared event log. Returns JSON."""

def _event_write(event_type: str, payload: dict) -> str:
    """Append to the event log and notify matching subscribers.
    Returns JSON with the new event_id."""
```

Everything above the bedrock is a `.pym` script. The system primitive
tools are `.pym` scripts. Agent-synthesized tools are `.pym` scripts.
The schema that defines a turn is a text file. The agent's notes, logs,
and role are text files. There is nothing else.

### Why .pym all the way up

Grail's `@external` declaration is the enforcement boundary. A `.pym`
script can only reach the Python functions it explicitly declares. The
Grail compiler rejects any call to an undeclared function at compile time.
This means:

- System tools call only the bedrock functions they need
- Agent tools call only the system tools (via `@external`) they need
- The runtime controls the externals dict — what is available to each
  agent at each activation

The Grail boundary is not a policy. It is a compiler invariant.

## 2. The Two Primitives

There are exactly two operations in this system:

```
read(store, selector)    →  value
write(store, key, value) →  ok
```

Every named tool — `read_file`, `graph_node`, `emit_event`, `write_file`,
`graph_add_node`, `read_recent_events` — is one of these two operations
applied to one of the three stores. There is no third kind of operation.

### How named operations reduce

```
read_file(path)                  = read(workspace,  path)
write_file(path, content)        = write(workspace,  path, content)

graph_node(id)                   = read(graph,  {node: id})
graph_neighbors(id, direction)   = read(graph,  {neighbors: id, dir: direction})
graph_find_nodes(attrs)          = read(graph,  {match: attrs})
graph_add_node(attrs)            = write(graph, {node: attrs})
graph_add_edge(from, to, kind)   = write(graph, {edge: {from, to, kind}})

read_recent_events(node_id, n)   = read(events,  {node_id, limit: n})
emit_event(type, payload)        = write(events,  {type, payload})
```

The only semantic difference between stores is the side effect on write:

| Store     | read side effect | write side effect          |
|-----------|-----------------|---------------------------|
| workspace | none            | none                       |
| graph     | none            | none                       |
| events    | none            | notifies matching subscribers |

Everything else is storage mechanics.

### Why two and not one

`read` and `write` are not symmetric. `read` is pure: same selector, same
value (within a transaction). `write` is not: it changes what future reads
return, and on the event store it triggers external effects. Collapsing them
into one primitive (`access(store, op, ...)`) adds nothing except confusion.

Two is the minimum that captures the read/write distinction cleanly.

---

## 3. The Three Stores

### Workspace — per-agent Cairn key-value store

The workspace is an agent's private key-value store, backed by a SQLite
Cairn database. Keys are file paths. Values are strings (text files).

- **Scope**: per-agent. No agent reads another agent's workspace directly.
  Agents share knowledge by emitting events and writing to the graph.
- **Durability**: every write is durable. The workspace persists across
  activations.
- **Fallback**: `_cairn_read` falls back to the stable (shared) workspace
  if a key is not found in the agent's own workspace. This is how system
  default files (e.g. DEFAULT_SCHEMA) are visible to new agents.

The workspace is not just storage. It IS the agent. A new agent is an
empty workspace. An agent that has been running for a week is a workspace
with `role.md`, `schema.yaml`, `notes.md`, `log.jsonl`, synthesized tools,
and whatever else it chose to write. The workspace is the complete record
of what the agent is and knows.

### Graph — shared SQLite directed property graph

The graph is a shared directed property graph. Any agent with graph access
can read and write it.

Nodes have:
- A system-generated ID
- A `kind` string (e.g. `"module"`, `"function"`, `"agent"`, `"task"`)
- Arbitrary JSON attributes

Edges have:
- `from` and `to` node IDs
- A `kind` string (e.g. `"calls"`, `"imports"`, `"assigned_to"`)
- Optional attributes

The graph has no fixed schema. Agents decide what to put in it. The graph
is how agents externalize structured knowledge that other agents can query.

### Events — shared append-only log (SQLite, WAL mode)

The event store is a shared append-only log. Every write to it is permanent
and ordered. New events are assigned a monotonically increasing `event_id`.

An event has:
- `event_id` — monotonic integer
- `event_type` — string
- `node_id` — the graph node this event concerns (optional but conventional)
- `payload` — JSON

The event store is the coordination channel. When agent A emits an event,
agent B (subscribed to that event type and node_id) is notified and activated.
This is the only push mechanism in the system. Everything else is polling.

### Store comparison

```
                 workspace        graph           events
─────────────────────────────────────────────────────────
scope            per-agent        shared          shared
structure        key-value        property graph  append-only log
write effect     none             none            notifies subscribers
read returns     string           JSON            JSON array
```

---

## 4. The System Tools

The system tools live in `bootstrap/tools/`. They are `.pym` files — Grail
scripts. Each one implements exactly one named operation. Each one declares
`@external` on the bedrock functions it needs and nothing else.

### The primitive tool set

```
bootstrap/tools/
  read_file.pym
  write_file.pym
  graph_node.pym
  graph_neighbors.pym
  graph_find_nodes.pym
  graph_add_node.pym
  graph_add_edge.pym
  read_recent_events.pym
  emit_event.pym
```

That is the complete set of primitive operations available to agents. There
is no other system-provided functionality.

### Anatomy of a system tool

```python
# bootstrap/tools/graph_neighbors.pym
@external
def _graph_read(selector: dict) -> str: ...

def graph_neighbors(node_id: str, direction: str) -> str:
    """Return the neighbors of node_id in the given direction.
    direction: 'in' | 'out' | 'both'
    Returns JSON array of {id, kind, attrs, edge_kind} objects."""
    selector = {"neighbors": node_id, "dir": direction}
    return _graph_read(selector)
```

Each tool is:
1. A single `@external` declaration per bedrock function it needs
2. One public function (the tool name)
3. Thin: it translates the tool's named arguments into the bedrock call

The Grail compiler verifies that `_graph_read` is declared `@external` and
that no other Python function is called. The runtime injects the actual
bedrock implementation into the externals dict at activation time.

### Discovery

The runtime calls `discover_grail_tools()` at startup. This scans:
1. `bootstrap/tools/*.pym` — system primitive tools
2. `workspace/tools/*.pym` — agent-synthesized tools (per-agent)

Both sets are compiled and made available to the LLM as callable tools.
Agent tools shadow system tools only if they share a name — giving agents
the ability to override system behavior in their own scope.

### What the LLM sees

The LLM sees tool names and their docstrings. It does not see `@external`
declarations, bedrock function names, or the `.pym` source. It calls tools
by name with JSON arguments. The runtime dispatches to the compiled Grail
bytecode.

---

## 5. The Workspace as Agent Identity

An agent is not a class. It is not a database row. An agent is a workspace
— a cairn key-value store with a conventional file layout. The runtime reads
certain files from this workspace before each activation. The agent writes
to this workspace during each activation. Nothing more is required.

### Contractual files (runtime reads these)

```
workspace/
  role.md          The agent's purpose. Plain English. Injected into
                   the system prompt via {{role}} in schema.yaml.

  schema.yaml      The turn definition. If absent, DEFAULT_SCHEMA is
                   used. Loaded fresh before every activation.

  capabilities.yaml  The set of system tools this agent is given access
                     to. Runtime-enforced: tools not listed here are
                     not injected into the externals dict.
```

`role.md` and `schema.yaml` are written by the agent. `capabilities.yaml`
is written by the runtime or by a privileged governance agent.

### Conventional files (agent creates these)

```
workspace/
  notes.md         Free-form notes across activations. Injected via
                   {{notes}} in schema.yaml. The agent's working memory.

  log.jsonl        Append-only activation log. One JSON object per line.
                   The agent decides what to record.

  todo.md          Checkbox task list. The agent decides the format.
                   Visible in the companion sidebar as interactive items.

  working_memory.md  Structured context for the current task. The agent
                     overwrites this each activation as needed.

  tools/           Agent-synthesized .pym tools. Discovered and compiled
    *.pym          alongside system tools.
```

These files are not required. An agent that never writes `notes.md` simply
has no notes. The DEFAULT_SCHEMA prompts the agent to create them, but the
agent is free to ignore that prompt.

### The workspace IS the agent

This has a concrete consequence: inspecting an agent is reading its workspace.
Correcting an agent is writing to its workspace. Cloning an agent is copying
its workspace. Pausing an agent is stopping activations while the workspace
remains intact.

There is no hidden state. No in-memory objects to serialize. The workspace
is the complete description of what the agent is and knows, at any moment,
without any running process.

### New agent bootstrap

A new agent starts with an empty workspace. The runtime falls back to
DEFAULT_SCHEMA, which gives the agent `read_file` and `write_file` and
a system prompt that says: "Read your role. Write notes. Write schema.yaml
when you know what you are."

After the first activation, the agent has written `role.md` and possibly
`notes.md`. After a few activations, it has written `schema.yaml`. After
that, the runtime loads `schema.yaml` instead of DEFAULT_SCHEMA, and the
agent runs as it has defined itself.

---

## 6. schema.yaml — A Turn as a Text File

`schema.yaml` is the agent's turn definition. It describes what context to
assemble, which tools to offer, and how the turn ends. It is a plain text
file that the agent writes and the runtime reads.

### Full format

```yaml
version: "1"
name: events_module_agent

# System prompt. Template variables resolved at activation time.
system: |
  You are responsible for {node.full_name} in the Remora codebase.
  {{role}}
  {{notes}}

# Context pipeline: executed top-to-bottom before the LLM call.
# Each step reads a value and makes it available as a named variable.
context:
  - name: role
    tool: read_file
    args:
      path: role.md

  - name: notes
    tool: read_file
    args:
      path: notes.md
    optional: true          # missing file → empty string, not error

  - name: source
    tool: read_file
    args:
      path: "{node.file_path}"

  - name: callers
    tool: graph_neighbors
    args:
      node_id: "{node.id}"
      direction: in

# Tools available during the turn (subset of capabilities.yaml).
tools:
  - write_file
  - emit_event
  - graph_add_node

# Event subscriptions. When one of these fires, activate this agent.
subscriptions:
  - event_type: ContentChangedEvent
    node_id: "{node.id}"

# Turn control.
max_turns: 5
termination: "DONE"         # LLM outputs this string to end the turn
```

### Template variables

Two namespaces are available:

**`{node.*}`** — the graph node this agent is responsible for.
Resolved from the activation event's `node_id`. Examples:
- `{node.id}` — the node's graph ID
- `{node.full_name}` — e.g. `remora.core.events.events`
- `{node.file_path}` — e.g. `src/remora/core/events/events.py`
- `{node.kind}` — e.g. `module`, `function`, `class`

**`{{name}}`** — the value of a named context pipeline step. `{{role}}`
inserts whatever `read_file(role.md)` returned. `{{notes}}` inserts
whatever `read_file(notes.md)` returned (empty string if optional and
missing). Template variables are resolved after the context pipeline runs.

### The context pipeline

The `context:` list is an ordered sequence of read operations. The runtime
executes them top-to-bottom before the LLM call, collecting named values.
Each step is:
- A tool call (`tool: read_file`) with resolved args
- Tagged as `optional: true` if a missing result is acceptable

The context pipeline is the mechanism by which agents assemble their own
context. An agent that wants to see recent events adds a step:

```yaml
- name: recent_events
  tool: read_recent_events
  args:
    node_id: "{node.id}"
    limit: 10
```

Then uses `{{recent_events}}` in its system prompt.

### Composition via extends

```yaml
# workspace/schema.yaml
extends: base_code_agent      # resolves to bootstrap/agents/base_code_agent.yaml

# Override or add to the base.
context:
  - name: callers
    tool: graph_neighbors
    args:
      node_id: "{node.id}"
      direction: in

tools:
  - graph_add_edge
```

`extends:` performs a shallow merge: the child's keys override the parent's.
For `context:` and `tools:`, the child's list is appended to the parent's.
One level of inheritance only — no deep chains.

### Why a text file and not code

An agent can write `schema.yaml` with `write_file`. An agent cannot write
Python code that the runtime executes directly. The text file format is the
boundary between what agents can define and what the runtime controls.

An agent evolving its own schema is not "arbitrary code execution" — it is
writing a configuration file. The runtime parses it, validates it, and
constructs the turn. The agent never touches the parser or the turn executor.

---

## 7. Tool Synthesis: Composing New Primitives

Agents extend the tool set by writing `.pym` files into `workspace/tools/`.
These files are discovered and compiled alongside the system tools. From the
LLM's perspective, a synthesized tool is indistinguishable from a system tool.

### The composition model

A synthesized tool declares `@external` on the system tools it calls — not
on the bedrock functions. System tools are the building blocks. Bedrock
functions are not directly reachable from synthesized tools.

```python
# workspace/tools/node_context.pym
# Composes read_file, graph_node, graph_neighbors into one call.

@external
def read_file(path: str) -> str: ...

@external
def graph_node(node_id: str) -> str: ...

@external
def graph_neighbors(node_id: str, direction: str) -> str: ...

def node_context(node_id: str) -> str:
    """Return full context for a graph node: source, metadata, callers, callees.
    Returns JSON with keys: source, node, callers, callees."""
    import json
    node    = json.loads(graph_node(node_id))
    source  = read_file(node["attrs"]["file_path"])
    callers = json.loads(graph_neighbors(node_id, "in"))
    callees = json.loads(graph_neighbors(node_id, "out"))
    return json.dumps({
        "source":  source,
        "node":    node,
        "callers": callers,
        "callees": callees,
    })
```

The Grail compiler verifies that `read_file`, `graph_node`, and
`graph_neighbors` are declared `@external` and that nothing else is called.
The runtime injects the compiled system tool implementations into the
externals dict when this tool is activated.

### What synthesis enables

An agent that synthesizes `node_context.pym` has effectively created a new
primitive for itself and any agent whose workspace includes that file. The
new primitive:

- Has a clean name the LLM understands
- Bundles three round-trips into one
- Can be inspected, modified, or deleted like any workspace file
- Can itself be used as an `@external` by a further synthesized tool

Composition is not limited to one layer. An agent can write a tool that calls
a synthesized tool that calls system tools. The Grail boundary holds at every
layer: each `.pym` file can only reach what it explicitly declares `@external`.

### Sharing synthesized tools

Synthesized tools live in an agent's workspace. They are not automatically
shared. An agent that wants to share a useful tool writes it to the graph
(as an event or a node attribute), and another agent reads it from there and
writes it into its own workspace. Tool sharing is a coordination protocol,
not a system feature.

### Agent-defined tool libraries

Over time, a swarm converges on useful tool patterns. A governance agent
can canonicalize frequently-synthesized tools by copying them into
`bootstrap/tools/` — promoting them to system primitives. The architecture
accommodates this without any structural change: it is the same `.pym` format
in a different directory.

---

## 8. What Is Not Specified

This document specifies the substrate. It does not specify what agents do
with it. The following are explicitly left unspecified — they emerge from
what agents read and write.

### Graph topology

The schema of the graph — what node kinds exist, what edge kinds exist,
what attributes nodes carry — is not defined here. The initial population
of the graph comes from whatever seeding process introduces Remora source
nodes. Agents add to it as they discover structure.

### Event taxonomy

The set of event types is not defined here. Agents name their events.
Agents choose what payloads to include. The only constraint is that events
have a `node_id` field (conventional, not enforced) so that subscriptions
can route by node.

### Agent roles and specialization

Which agents exist, what they are responsible for, how they divide work —
none of this is specified. A coordinator agent, a per-module agent, a
refactoring agent: these are patterns that emerge from agents reading the
graph and deciding what to be.

### Memory model

How much an agent remembers, in what form, for how long — not specified.
An agent with a thorough `notes.md` remembers a lot. An agent that never
writes `notes.md` starts fresh every activation. The workspace provides
the mechanism; the agent decides the policy.

### Inter-agent protocol

How agents coordinate beyond event emission — not specified. An agent can
create a task node in the graph and another agent can claim it. An agent
can write a proposal to its workspace and emit an event pointing to it.
The protocol is whatever the agents agree to write and read.

### What is specified

| Specified                        | Not specified                    |
|----------------------------------|----------------------------------|
| Two primitives (read, write)     | Graph schema / topology          |
| Three stores (workspace, graph, events) | Event taxonomy              |
| Six bedrock functions            | Agent roles / specialization     |
| System tool set (9 tools)        | Memory model / retention policy  |
| .pym tool format + @external     | Inter-agent coordination protocol|
| schema.yaml turn definition      | What agents actually do          |
| Workspace file conventions       |                                  |

The specified parts are the minimum substrate. The unspecified parts are
the space in which the swarm self-organizes.

---

## 9. The Bootstrap Sequence

Starting from empty stores, how does a self-defining, coordinating swarm
come into existence? This section traces the sequence using only the two
primitives and the `.pym` tool architecture.

### Step 0: Seed the graph

A one-time seeding script (not an agent) walks the Remora source tree and
writes graph nodes for each module, class, and function. It calls
`_graph_write` directly — this is the one moment where bedrock is called
from outside the agent runtime. After seeding, the graph contains the
initial code topology. No events. No agents. No workspaces.

### Step 1: The first agent activation

The runtime activates the first agent (e.g. `coordinator`) with an empty
workspace. Because there is no `schema.yaml`, DEFAULT_SCHEMA is used:

```yaml
# DEFAULT_SCHEMA (built into the runtime, not a file)
system: |
  You are a Remora agent. Your workspace is empty.
  Read your activation context. Decide what you are.
  Write role.md to record your purpose.
  Write schema.yaml to define how you will run next time.
  Use write_file for both.
context: []
tools:
  - read_file
  - write_file
max_turns: 5
termination: "DONE"
```

The activation payload tells the agent it is `coordinator` and gives it
the graph node ID for the project root.

### Step 2: The coordinator writes itself

In its first activation the coordinator:
1. Calls `read_file("role.md")` → not found, empty string
2. Calls `write_file("role.md", "I coordinate the Remora bootstrap...")` → ok
3. Calls `write_file("schema.yaml", yaml_string)` → ok

The yaml_string it writes requests `graph_find_nodes`, `graph_add_node`,
`graph_add_edge`, and `emit_event`. On its next activation, DEFAULT_SCHEMA
is no longer used — the coordinator's own `schema.yaml` is loaded.

### Step 3: The coordinator surveys the graph

In subsequent activations, the coordinator reads the graph, identifies
unassigned module nodes, and emits `AgentNeededEvent` events:

```python
# coordinator's reasoning, expressed as tool calls:
modules = graph_find_nodes({"kind": "module", "assigned": False})
for module in modules:
    emit_event("AgentNeededEvent", {"node_id": module["id"]})
```

### Step 4: Spawn agents for each module

The runtime receives `AgentNeededEvent` events and spawns new agents with
empty workspaces, each with the `node_id` from the event payload.

Each new agent goes through Step 1 and 2 for itself: DEFAULT_SCHEMA →
writes `role.md` and `schema.yaml` tailored to its module.

### Step 5: Module agents begin working

Once a module agent has written its `schema.yaml` with a `ContentChangedEvent`
subscription, it will be activated whenever its module changes. It reads
the source, updates its notes, updates graph edges, emits events for
callers and callees as needed.

### Step 6: Tool synthesis emerges

A module agent notices it always calls `read_file` + `graph_neighbors`
together. It writes `workspace/tools/module_context.pym`. On the next
activation, `module_context` is available as a single tool call. It emits
a `ToolSynthesizedEvent` so the coordinator can decide whether to promote
this to a system tool.

### The loop

From this point the system is self-sustaining:
- Agents write `schema.yaml` → runtime loads it → agents run as they defined
- Agents emit events → other agents are activated → coordination without a scheduler
- Agents synthesize tools → composition grows → the tool set evolves with the swarm
- Everything is readable as workspace files and graph nodes — there is no hidden state

The bootstrap sequence is not special. It is the same two primitives, the
same three stores, the same `.pym` tools, used from the very beginning.

---

## 10. Delivery Plan

Ordered by layer. Each milestone delivers a running, testable system.
Nothing is speculative — each milestone is exactly what is needed to enable
the next one.

### M0 — Python bedrock

Deliverable: six Python functions, three SQLite databases, no agent runtime.

```
src/remora/bootstrap/bedrock.py
  _cairn_read(path)      _cairn_write(path, content)
  _graph_read(selector)  _graph_write(op, data)
  _event_read(selector)  _event_write(event_type, payload)

tests/unit/test_bedrock.py
  Read/write round-trips for each store.
  Event write notifies a synchronous subscriber.
  Cairn read falls back to stable workspace.
```

No Grail. No agents. Just the six functions and their SQLite backends.

### M1 — System tools (.pym)

Deliverable: nine `.pym` files, Grail compilation, `discover_grail_tools()`.

```
bootstrap/tools/
  read_file.pym        write_file.pym
  graph_node.pym       graph_neighbors.pym    graph_find_nodes.pym
  graph_add_node.pym   graph_add_edge.pym
  read_recent_events.pym   emit_event.pym

src/remora/bootstrap/tool_discovery.py
  discover_grail_tools(workspace_path) → list[GrailTool]

tests/unit/test_system_tools.py
  Each tool compiled. Each tool callable with a live bedrock.
  @external boundary verified: calling an undeclared function raises.
```

### M2 — Turn executor

Deliverable: load `schema.yaml`, run context pipeline, call LLM, dispatch tool calls.

```
src/remora/bootstrap/turn_executor.py
  TurnExecutor(schema, bedrock, tools)
  .run(activation_event) → TurnResult

src/remora/bootstrap/schema_loader.py
  load_schema(workspace_path) → TurnSchema
  Falls back to DEFAULT_SCHEMA if schema.yaml absent.
  Resolves extends: one level.

tests/integration/test_turn_executor.py
  Full turn with mocked LLM: context assembled, tools called, turn ends on termination string.
  DEFAULT_SCHEMA used when workspace has no schema.yaml.
  Agent-written schema.yaml loaded on subsequent activation.
```

### M3 — Self-bootstrapping loop

Deliverable: coordinator agent bootstraps from empty workspace, writes `schema.yaml`,
subsequent activations use that schema.

```
bootstrap/agents/DEFAULT_SCHEMA.yaml   (the fallback schema as a file)
bootstrap/agents/base_code_agent.yaml  (extends base for code module agents)

tests/integration/test_bootstrap_loop.py
  Empty workspace → DEFAULT_SCHEMA → agent writes schema.yaml
  Next activation → agent's own schema loaded
  Coordinator emits AgentNeededEvent → new agent workspace created → new agent bootstraps
```

### M4 — Graph seeding

Deliverable: one-time script that populates the graph from Remora source.

```
bootstrap/seed_graph.py
  Walks src/remora/, calls _graph_write for each module, class, function.
  Creates "imports" and "calls" edges from existing static analysis.

tests/integration/test_seed_graph.py
  Seeded graph contains expected nodes and edges.
  graph_find_nodes and graph_neighbors return correct results.
```

### M5 — Companion visibility

Deliverable: companion sidebar reads and displays workspace files.

```
Workspace file sections in companion sidebar:
  ROLE     — role.md (plain text)
  SCHEMA   — schema.yaml (parsed, rendered as structured view)
  NOTES    — notes.md (plain text, scrollable)
  TODO     — todo.md (checkboxes rendered interactive)
  LOG      — log.jsonl (last N entries, collapsible)
  TOOLS    — workspace/tools/*.pym (syntax highlighted, read-only)

No special protocol. Companion reads workspace files via read_file.
Refresh on activation end (event-driven, not polling).
```

### M6 — Tool synthesis

Deliverable: agent-written `.pym` tools compiled and available on next activation.

```
Extend discover_grail_tools() to scan workspace/tools/*.pym per agent.
Extend turn_executor.py to include synthesized tools in the tool set.
Synthesized tools can declare @external on system tools (not bedrock).

tests/integration/test_tool_synthesis.py
  Agent writes a .pym tool. Next activation: tool is callable.
  Synthesized tool that calls two system tools: both externals resolve correctly.
  Synthesized tool attempting to call _cairn_read directly: compilation fails.
```

### Summary

| Milestone | What it enables                                    |
|-----------|----------------------------------------------------|
| M0        | Bedrock: the six functions work                    |
| M1        | System tools: named operations callable from .pym  |
| M2        | Turn executor: LLM can call tools, turn runs       |
| M3        | Self-bootstrapping: agents define themselves       |
| M4        | Graph seeded: code topology available to agents    |
| M5        | Companion: developers can see what agents are doing|
| M6        | Synthesis: composition grows; tool set evolves     |

Each milestone is independently testable. M0–M3 can be demonstrated
without a graph, sidebar, or tool synthesis. The substrate works from M2 onward.
The full system is live at M6.

---

*End of PHASE2_V6_BOOTSTRAP_CONCEPT.md*
