# Phase 2 Bootstrap v3: Primitive-First

> v3 is a refinement of v2's concept through the lens of the Primitives design.
> Where v2 specified an elaborate semantic graph topology, v3 describes only
> the substrate — the minimal ground the bootstrap needs to stand on — and
> trusts the self-bootstrapping process to build structure on top of it.
>
> The two additions to v2 that prompted this refinement:
> 1. Grail .pym scripts are the **only** agent tool interface, and they
>    **only** read and write cairn workspaces.
> 2. Agents need to be able to navigate the Remora graph. Rustworkx is the
>    candidate graph library; options are discussed below.

---

## Table of Contents

1. [Reframing the Goal](#1-reframing-the-goal)
   What "build up from primitives" means. What the substrate is. What it is not.

2. [The Substrate](#2-the-substrate)
   The three things the runtime provides: a cairn workspace, a graph, an event bus.

3. [The Cairn Boundary](#3-the-cairn-boundary)
   Why .pym-only + cairn-only is the right constraint. How it maps to the actual
   CairnExternals API. What gets added.

4. [Graph Navigation](#4-graph-navigation)
   What graph access means for agents. Options for the graph library.
   How graph ops enter the cairn boundary.

5. [Turn Execution: The Primitives](#5-turn-execution-the-primitives)
   TurnSchema as the canonical turn model. How it replaces bundle.yaml.
   DEFAULT_SCHEMA and self-bootstrapping.

6. [The Agent Model](#6-the-agent-model)
   BootstrapAgent: the single runtime model. Capability enum: what gates
   access. AgentDefinition: the authoring mechanism. The capability ladder.

7. [What Is Not Specified](#7-what-is-not-specified)
   Deliberate omissions: node kinds, edge kinds, protocol state machines,
   memory models. Why these should emerge, not be prescribed.

8. [The Bootstrap Sequence](#8-the-bootstrap-sequence)
   How agents build themselves from the substrate up.

9. [Delivery Plan](#9-delivery-plan)
   Milestones, grounded in v1 reality.

---

## 1. Reframing the Goal

v2's premise — the swarm is the author of its next version — is correct. But
v2 tried to specify both the substrate *and* the things built on the substrate:
specific node kinds (spec.requirement, test.case, memory.episode ...), specific
edge kinds (implements, violates, asserts ...), specific protocol state machines
(DirectTask, ViolationResponse ...). This over-specification defeats the point.
If the structure is pre-specified, the swarm isn't building it — we are.

The Primitives design points toward the right approach. `TurnSchema`,
`ContextPipeline`, `ToolRef`, `InputGate` — six types, nothing else. These
describe the *shape of a turn*, not the shape of the system. The system's shape
emerges from what agents do with turns.

v3 applies this discipline to the whole concept:

**Specify the substrate. Leave the structure to the swarm.**

The substrate is the minimal set of capabilities the runtime must provide for
agents to be able to do anything at all:

- **A cairn workspace per agent.** A place to read and write files. This is how
  an agent has persistent state, a role description, a schema, local tools.

- **A graph.** A queryable store of nodes and edges. The *kinds* of nodes and
  edges it contains at any given moment are not prescribed — the bootstrap
  process writes them. The runtime provides the ability to add, remove, and
  query; agents decide what to put there.

- **An event bus.** A way to emit named events and subscribe to them. The
  specific event types that agents use are not prescribed — they are defined
  by the agents that emit them and the agents that subscribe to them.

That is the substrate. Everything else — node taxonomies, edge vocabularies,
protocol state machines, memory models — is built by agents on top of it.

---

## 2. The Substrate

### 2.1 Cairn workspace

Each agent has a cairn workspace: a Cairn-backed key-value store that behaves
like a filesystem (paths → string content). Backed by a SQLite `.db` file in
`.remora/<swarm_id>/agents/<agent_id>/workspace.db`.

The workspace is persistent across activations. An agent that writes
`role.md` during its first activation finds it there on every subsequent one.

The stable workspace (`.remora/<swarm_id>/stable.db`) contains the synced
project source files. An agent can read project files by querying the stable
workspace; agent workspace reads fall back to stable automatically.

`CairnWorkspaceService` (v1, `core/agents/cairn_bridge.py`) manages both.
No changes needed here for the bootstrap.

### 2.2 Graph

A queryable directed graph accessible to agents through cairn externals. The
graph holds whatever nodes and edges the bootstrap process has put there —
initially seeded from the code discovery output (`CSTNode` → node, `caller_ids`
→ edges), then extended by agents as they run.

The runtime provides add, remove, and query operations. It does not prescribe
what nodes or edges should exist. An agent that wants to track a relationship
between two things adds an edge. An agent that wants to record a fact adds a
node. The graph is the shared structured memory of the swarm.

See §4 for graph library options.

### 2.3 Event bus

An event bus with typed subscription. Backed by the existing v1 `EventBus`
and `EventStore` (`core/events/`). Agents emit named events with a JSON
payload. Other agents subscribe to event types and are triggered when matching
events arrive.

Causal provenance is tracked: every event carries the ID of the event that
caused it to be emitted (or `None` for root events). This is the mechanism for
tracing what caused what, detecting infinite loops, and enforcing depth limits.

The runtime provides `emit_event` and `read_recent_events` as cairn externals.
Agents don't interact with the EventBus directly.

---

## 3. The Cairn Boundary

### 3.1 The constraint

Grail `.pym` scripts are the only agent tool interface. A `.pym` script can
only call functions declared with `@external`. The runtime controls the
externals dict entirely. This is not a policy — it is how the Grail compiler
works: undeclared externals cause a compile-time error.

The bootstrap runtime passes every agent a `BootstrapExternals` dict. That
dict is the complete set of things agents can do. There is no other interface.

**Agents can only reach what is in the externals dict.**

### 3.2 What is in the dict today (v1 CairnExternals)

```python
# core/agents/cairn_externals.py — CairnExternals.as_externals()
{
    "read_file":      ...,  # read from agent cairn workspace
    "write_file":     ...,  # write to agent cairn workspace
    "list_dir":       ...,  # list workspace directory
    "file_exists":    ...,  # check file existence
    "search_files":   ...,  # glob pattern search in workspace
    "search_content": ...,  # regex content search in workspace
    "submit_result":  ...,  # signal turn complete + changed files
    "log":            ...,  # structured log
}
```

All paths are normalized through `PathResolver.to_workspace_path()` — they
cannot escape the workspace. This is the existing enforcement.

### 3.3 What gets added for the bootstrap

The bootstrap extends `CairnExternals` with graph and event operations:

```python
# BootstrapExternals adds:
{
    # Graph (read-only except for add/remove which are gated by role)
    "graph_add_node":    ...,  # add a node to the graph
    "graph_add_edge":    ...,  # add an edge to the graph
    "graph_remove_node": ...,  # remove a node
    "graph_remove_edge": ...,  # remove an edge
    "graph_neighbors":   ...,  # get neighbors of a node (by edge kind, direction)
    "graph_find_nodes":  ...,  # find nodes by kind or attribute
    "graph_node":        ...,  # get a single node by ID

    # Event
    "emit_event":         ...,  # emit a named event into the causal bus
    "read_recent_events": ...,  # recent events for a node or correlation
}
```

Graph mutation ops (`graph_add_node`, `graph_add_edge`, `graph_remove_node`,
`graph_remove_edge`) are role-gated: the runtime passes them only to agents
whose role permits graph writes. Read-only agents receive only
`graph_neighbors`, `graph_find_nodes`, and `graph_node`.

The keys in the dict are what `.pym` scripts declare as `@external`. An agent
that only needs to read the graph declares only the read ops. This is the
capability model: what's in the dict is what's possible.

### 3.4 All paths stay in the workspace

Graph externals return data as JSON strings, not Python objects. They do not
return live graph handles. An agent that calls `graph_neighbors(node_id,
edge_kind="whatever")` gets back a JSON string listing neighbor node IDs and
edge attributes. It cannot hold a reference to the graph or issue arbitrary
traversal calls — only the declared externals.

This preserves the workspace boundary. Graph data flows through the same
read/write interface as file data. The graph is simply another kind of
structured content accessible through cairn.

---

## 4. Graph Navigation

### 4.1 What graph access means for agents

Agents use graph ops through `.pym` scripts — both as pre-turn reads (in the
`ContextPipeline` via `ToolRef`) and as interactive tools (during the LLM loop).

A pre-turn read might look like: call `graph_neighbors` to get the list of
nodes that depend on this one before the LLM sees the prompt. An interactive
tool might look like: the LLM calls `graph_add_edge` to record a relationship
it discovered. Both go through the same externals dict.

The graph is a shared substrate. Any agent can query it. Mutation is
role-gated but not otherwise restricted — agents decide what nodes and edges
are meaningful. The bootstrap process, not the concept document, determines
what structure accumulates in the graph.

### 4.2 Graph library options

The externals need something to call into. The following are the realistic
options for the graph implementation backing the `graph_*` externals.

---

#### Option A: Rustworkx + SQLite (Recommended)

**What it is:** [rustworkx](https://github.com/Qiskit/rustworkx) is a
Rust-backed directed graph library from the Qiskit project. Used here as an
in-memory traversal engine; SQLite provides durable storage.

**Pros:**
- Rust-speed traversal: cycle detection, shortest path, topological sort,
  strongly connected components — all at native speed
- `PyDiGraph` stores arbitrary Python objects as node/edge data
- MIT license, `pip install rustworkx`, actively maintained, no native build
  tools required beyond pip
- Cycle detection maps to deadlock detection; shortest path maps to causal
  depth; topological sort maps to dependency ordering — useful properties
  that emerge naturally from the algorithm set
- Integer-indexed internally → very cache-friendly for large traversals

**Cons:**
- No native persistence: requires a SQLite serialize/deserialize layer
- Integer node indices internally — need to maintain a `str node_id → int
  rustworkx index` mapping
- No native query language: neighborhood queries are Python loops over
  edge lists from the Rustworkx API
- Documentation is quantum-computing-flavored; general graph API requires
  reading the API reference

**Implications:**
- Two systems working together: Rustworkx for traversal algorithms, SQLite
  for persistence and attribute queries
- On startup: deserialize from SQLite into Rustworkx (fast for <100k nodes)
- On shutdown / checkpoint: serialize Rustworkx back to SQLite
- Simple neighborhood queries go directly to SQLite (faster than loading
  into Rustworkx for single-hop reads)
- Rustworkx used only for algorithmic queries: cycle detection, depth
  calculation, transitive closure

**Opportunities:**
- The full Rustworkx algorithm library is available for free once the graph
  is loaded: SCC analysis, minimum spanning tree, betweenness centrality —
  capabilities that could become useful as the swarm grows
- Fast enough to keep the full graph in memory for any realistic codebase

---

#### Option B: NetworkX + SQLite

**What it is:** [NetworkX](https://networkx.org/) is the de facto standard
Python graph library. Same hybrid model as Option A but pure Python.

**Pros:**
- Best documentation, widest algorithm coverage, most Pythonic API
- Node IDs are strings directly — no integer index mapping needed
- Richest algorithm set in Python
- Easy to debug: `G.nodes[n]` is a plain dict
- Lower initial learning curve

**Cons:**
- Pure Python: 10–50× slower than Rustworkx for large traversals
- Higher memory overhead per node

**Implications:**
- For Remora's expected graph sizes (code nodes in a typical project are well
  under 100k), the performance gap is academic — LLM call latency dominates
- Clean upgrade path: switch to Rustworkx later if profiling shows graph
  traversal is actually a bottleneck; both expose similar `DiGraph` semantics

**Opportunities:**
- Lower barrier to contribution during initial development
- Cleaner debugging during M0–M3 when correctness matters more than speed

---

#### Option C: SQLite Property Graph (No In-Memory Library)

**What it is:** The graph lives entirely in SQLite as two tables
(`bootstrap_nodes`, `bootstrap_edges`) with proper indexes.

```sql
CREATE TABLE bootstrap_nodes (
    node_id TEXT PRIMARY KEY,
    kind    TEXT,
    attrs   TEXT  -- JSON
);
CREATE TABLE bootstrap_edges (
    edge_id   TEXT PRIMARY KEY,
    kind      TEXT,
    from_node TEXT REFERENCES bootstrap_nodes(node_id),
    to_node   TEXT REFERENCES bootstrap_nodes(node_id),
    attrs     TEXT  -- JSON
);
CREATE INDEX idx_edges_from_kind ON bootstrap_edges(from_node, kind);
CREATE INDEX idx_edges_to_kind   ON bootstrap_edges(to_node, kind);
```

**Pros:**
- Zero new dependencies; SQLite already used throughout v1
- Native persistence; no serialize/deserialize cycle
- Single-hop neighborhood queries are fast with the indexes above
- Can JOIN graph data with event log easily (same database file)

**Cons:**
- No native graph algorithms: cycle detection requires recursive CTEs or
  loading a subgraph into Python
- Multi-hop traversal requires recursive SQL or Python loops

**Implications:**
- Works for all simple neighborhood queries agents actually need (who are my
  neighbors? what edges do I have?)
- Add Rustworkx on demand when algorithmic queries are needed (M4+ territory)

**Opportunities:**
- Simplest starting point; Option A can be layered on top without changing the
  externals API at all

---

#### Option D: Kuzu (Embedded Graph Database)

**What it is:** [Kuzu](https://kuzudb.com/) is an embedded ACID graph
database with openCypher query language — DuckDB for property graphs.

**Pros:**
- Native property graph model with typed schemas
- Cypher query language: expressive multi-hop queries without Python loops
- ACID transactions; built-in persistence; columnar storage
- `pip install kuzu`, actively maintained

**Cons:**
- New dependency with a Cypher learning curve
- Younger project, smaller community
- Typed node/edge tables require upfront schema declaration — conflicts with
  v3's "don't prescribe structure" philosophy (node kinds would need to be
  known in advance or stored as string attributes in a generic table)

**Implications:**
- Most expressive query language, but the schema rigidity works against v3's
  open-ended graph philosophy

**Opportunities:**
- Right choice if the graph becomes a platform feature queried by many
  external consumers
- Could expose a `graph_query_cypher` privileged external for advanced
  semantic queries without new Python code

---

#### Recommendation

**Start with Option C (SQLite property graph) for M0–M2.** Lowest friction,
zero new dependencies, covers all initial neighborhood queries.

**Add Option A (Rustworkx) at M3–M4** when algorithmic queries appear (depth
enforcement, cycle detection). Load relevant subgraphs on demand; SQLite
remains the source of truth.

This two-phase approach means the externals API doesn't change between M0
and M4 — only the implementation backing the externals changes.

Option B (NetworkX) is a valid substitute for Rustworkx if the team prefers
a pure-Python start. The upgrade path is the same.

Option D (Kuzu) is noted for future consideration. Its schema rigidity is a
real friction point for v3's open-ended graph.

---

## 5. Turn Execution: The Primitives

The six types in `primitives.py` (`str`, `ToolRef`, `Concat`, `InputGate`,
`Step`, `ContextPipeline`, `TurnSchema`) are the canonical data model for
every agent turn. This is the core contribution of the Primitives design, and
it does not change in v3.

`TurnSchema` replaces `bundle.yaml` + `_build_prompt()`. Instead of a config
file that hardcodes context assembly in Python, an agent stores a `TurnSchema`
as `schema.json` in its cairn workspace. The runtime loads it on every
activation and executes it:

1. **Resolve `system`** — walk the `PromptNode` tree, calling any `ToolRef`
   pre-turn reads. These are `.pym` scripts that run before the LLM sees
   anything.

2. **Run the `ContextPipeline`** — steps execute in order. Each step's output
   is stored as `$step_name` for interpolation in later steps' args.

3. **Run the LLM loop** — the LLM gets the resolved messages and the declared
   `.pym` tool names. It calls tools, gets results, iterates up to `max_turns`.
   When it outputs the `termination` string, the loop ends.

### DEFAULT_SCHEMA

Every new agent starts with:

```python
DEFAULT_SCHEMA = TurnSchema(
    system="You are a Remora agent node. Read your workspace to understand your role.",
    context=ContextPipeline(steps=(
        Step("role", ToolRef("read_file", {"path": "role.md"})),
    )),
    tools=("read_file", "write_file", "emit_schema"),
    max_turns=2,
    termination="done",
)
```

The `emit_schema` tool is the key: it writes the agent's own `TurnSchema`
specification to `schema.json` in its cairn workspace. On every subsequent
activation the runtime uses that stored schema. The agent bootstraps itself
from nothing using only workspace files and the emit_schema tool.

This is the self-bootstrapping sequence (from the Primitives Walkthrough):

```
1. NodeDiscoveredEvent fires → runtime creates agent node
2. Runtime activates with DEFAULT_SCHEMA
3. Agent reads role.md → empty (new node)
4. Agent writes role.md with a description of its purpose
5. Agent calls emit_schema({...richer schema...})
6. Runtime stores schema.json
7. Next activation → runtime loads schema.json and uses it
```

Steps 1–6 happen once. Step 7 happens every time.

---

## 6. The Agent Model

The substrate is what the runtime provides. But we also need to specify what
an agent *is* — the shape that all bootstrap agents share regardless of what
they specialize into. This is the agent model: not a taxonomy of agent types,
but the single data structure that represents any agent at runtime.

Following v1's principle of "data over subclasses" (from `EventBased_Concept.md`:
"There is no TestAgentNode subclass. Every agent is an AgentNode instance.
Behavioral differences come from different field values"), the bootstrap has
one runtime model.

### 6.1 BootstrapAgent: the runtime model

```python
class BootstrapAgent(BaseModel):
    """A bootstrap agent: graph node + turn schema + event subscriber."""

    # Identity — also stored as a graph node (kind="agent.profile")
    node_id: str
    name: str

    # Capability grant — determines which externals are in this agent's dict
    capabilities: frozenset[Capability]

    # Current turn shape — loaded from schema.json in cairn workspace.
    # None = use DEFAULT_SCHEMA.
    schema: TurnSchema | None = None

    # Runtime state (updated by the runtime after each activation)
    status: str = "idle"   # "idle", "running", "error"

    # Event subscriptions — what events trigger this agent
    subscriptions: list[SubscriptionPattern] = Field(default_factory=list)

    # Authoring origin — set during first activation
    extension_name: str | None = None
```

There is no `DocstringBootstrapAgent` subclass or `ReviewerBootstrapAgent`
subclass. Every bootstrap agent is a `BootstrapAgent` instance. Behavioral
differences come from three data fields:

1. `capabilities` — which externals are in the dict → what the agent can do
2. `schema` — the TurnSchema → how the agent runs (context pipeline, tools, LLM loop)
3. `subscriptions` — which events trigger it → when the agent runs

The `BootstrapAgent` plays two roles simultaneously:
- **Graph node** — it IS a node in the semantic graph (kind="agent.profile").
  The graph is the source of truth; reading the graph gives you the agent.
- **Turn executor** — its `schema` (a `TurnSchema`) describes how to run the
  next activation completely.

### 6.2 Capability: the access control mechanism

The `Capability` enum determines which externals appear in an agent's dict.
It is not a taxonomy of agent kinds — it is a precise access control:

```python
class Capability(str, Enum):
    FILE_READ       = "file_read"       # read_file, list_dir, file_exists, search_*
    FILE_WRITE      = "file_write"      # write_file, submit_result
    GRAPH_READ      = "graph_read"      # graph_node, graph_neighbors, graph_find_nodes
    GRAPH_WRITE     = "graph_write"     # graph_add_node, graph_add_edge, graph_remove_*
    EVENT_EMIT      = "event_emit"      # emit_event
    EVENT_READ      = "event_read"      # read_recent_events
    SCHEMA_EVOLVE   = "schema_evolve"   # emit_schema (write schema.json to workspace)
    TOOL_SYNTHESIZE = "tool_synthesize" # write new .pym tools to workspace
    PRIVILEGED      = "privileged"      # update_subscription, register_protocol
```

The runtime builds the externals dict from the agent's `capabilities` frozenset.
Two agents running the same `.pym` tool get different results if one has
`GRAPH_WRITE` and the other doesn't — the one without it simply doesn't have
`graph_add_node` in its dict.

All new agents start with `{FILE_READ, FILE_WRITE, SCHEMA_EVOLVE}`. This is
enough to run `DEFAULT_SCHEMA`, write `role.md`, and call `emit_schema`.

### 6.3 AgentDefinition: the authoring mechanism

`BootstrapAgent` is the runtime representation. `AgentDefinition` is the
authoring representation — what developers or self-bootstrapping agents use to
*describe* what an agent should become.

The separation is intentional: you author a definition, the runtime runs the
agent. Just as v1's extension configs (Python files, authored by developers)
produce `AgentNode` instances at discovery time, `AgentDefinition` produces
`BootstrapAgent` instances at activation time.

```python
class AgentDefinition(BaseModel):
    """Describes what a bootstrap agent should be. Produces a BootstrapAgent."""
    name: str
    role_description: str            # written to role.md on first activation
    capabilities: set[Capability]    # determines externals dict
    context_steps: tuple[Step, ...] = ()
    tools: tuple[str, ...] = ()
    subscriptions: list[SubscriptionPattern] = Field(default_factory=list)
    max_turns: int = 5
    termination: str = "done"

    def to_turn_schema(self) -> TurnSchema: ...
    def to_bootstrap_agent(self, node_id: str) -> BootstrapAgent: ...
```

**Capability mixin classes.** Capabilities are composed via Pydantic mixin
baseclasses — pure marker classes that add no fields, only MRO membership.
The runtime checks the definition's MRO to determine the capability set:

```python
# Capability mixins — pure markers, no fields
class FileReadMixin(BaseModel): pass
class FileWriteMixin(FileReadMixin): pass     # write implies read
class GraphReadMixin(BaseModel): pass
class GraphWriteMixin(GraphReadMixin): pass   # write implies read
class EventEmitMixin(BaseModel): pass
class EventReadMixin(EventEmitMixin): pass    # read implies emit access
class SchemaEvolveMixin(BaseModel): pass
class ToolSynthesizeMixin(BaseModel): pass
class PrivilegedMixin(BaseModel): pass

# Runtime uses MRO to derive the capability frozenset — no manual listing
def capabilities_from_definition(defn: type[AgentDefinition]) -> frozenset[Capability]:
    return frozenset(c for mixin, c in MIXIN_CAPABILITY_MAP.items()
                     if issubclass(defn, mixin))
```

A base definition composes what a whole family needs. Concrete definitions
extend it with domain specifics:

```python
class BaseCodeAgentDefinition(
    FileWriteMixin,   # reads + writes workspace
    GraphReadMixin,   # queries the graph
    EventEmitMixin,   # emits events
    SchemaEvolveMixin, # evolves its own schema
    AgentDefinition,  # base
):
    """Common foundation for agents that work on code nodes."""
    context_steps: tuple[Step, ...] = (
        Step("source", ToolRef("read_file", {"path": "$node.file_path"})),
        Step("history", ToolRef("read_recent_events", {"node_id": "$node.id"})),
    )
    tools: tuple[str, ...] = ("write_file", "emit_event", "emit_schema")


class SignatureWatcherDefinition(BaseCodeAgentDefinition, GraphWriteMixin):
    """Extends base — also writes graph edges to record detected relationships."""
    name: str = "signature_watcher"
    role_description: str = "You detect and propagate signature changes."
    # Inherits all base steps; adds graph write capability via the mixin
```

The class signature is the capability declaration. No manual `capabilities`
set to maintain. `issubclass(SignatureWatcherDefinition, GraphWriteMixin)` is
the runtime check that grants `GRAPH_WRITE`.

Mixins add **no fields**, only MRO membership — avoiding all Pydantic
diamond-inheritance field conflicts. The definition hierarchy collapses into a
flat `frozenset[Capability]` at activation time. The runtime receives a
`BootstrapAgent` — no class hierarchy, no MRO resolution during the turn.

**Self-authored definitions.** An agent's first activation uses
`DEFAULT_SCHEMA`. The agent reads its node context (code it's responsible for,
callers, callees) and calls `emit_schema` with a richer `TurnSchema`. This is
the agent authoring its own `AgentDefinition` — writing its own specialization
data rather than running fixed developer-supplied code.

The authoring and self-bootstrapping mechanisms are the same: both produce a
`TurnSchema` stored in `schema.json`. The only difference is who produces it.

### 6.4 The capability ladder

Capabilities are earned through demonstrated behavior, not pre-assigned:

```
                    PRIVILEGED
                    └─ modify substrate (subscriptions, protocols)
                TOOL_SYNTHESIZE
                └─ write new .pym tools to workspace
            GRAPH_WRITE
            └─ add/remove nodes and edges
        GRAPH_READ + EVENT_EMIT + EVENT_READ
        └─ query graph, participate in event flow
    FILE_READ + FILE_WRITE + SCHEMA_EVOLVE
    └─ read/write workspace, emit own schema
ALL NEW AGENTS START HERE
```

Progression is event-driven:
- An agent sends `RequestCapabilityEvent` with the capability needed and
  a justification (what it has demonstrated, what it needs the capability for)
- A privileged maintainer agent evaluates and sends `GrantCapabilityEvent`
  or `DenyCapabilityEvent`
- The runtime updates the agent's `capabilities` set and rebuilds its
  externals dict for next activation

The mechanism is specified. The policy — what counts as justification, how
the maintainer agent reasons, what progression looks like — is NOT specified.
It emerges from the bootstrap process.

### 6.5 Developer visibility

The agent model is designed to be legible. Because every agent is a
`BootstrapAgent` with flat Pydantic fields stored in the graph, a developer
can inspect the swarm state with simple graph queries:

- What agents exist? → `graph_find_nodes(kind="agent.profile")`
- What can agent X do? → read its `capabilities` frozenset
- What is agent X doing right now? → read its `status` + `last_trigger_event`
- What does agent X's turn look like? → read `schema.json` from its cairn workspace
- What events triggered agent X recently? → `read_recent_events(node_id=X)`
- What agents subscribe to event Y? → `SubscriptionRegistry.get_subscribers(Y)`

There is no opaque internal state. The graph is the source of truth.
`BootstrapAgent` instances are just data. The whole swarm is queryable.

**Developer interaction operations:**

| Operation | Mechanism |
|-----------|-----------|
| **Inspect** agent state | `graph_node(node_id)` / `read_recent_events(node_id)` |
| **Read** agent schema | `read_file("schema.json")` from cairn workspace |
| **Inject** new definition | Add `AgentDefinition` subclass → hot-reload catalog |
| **Pause** a misbehaving agent | Set `status="paused"` in graph → runtime skips activation |
| **Correct** a bad schema | Write new `schema.json` to cairn workspace directly |
| **Observe** live swarm | Tail `EventStore` → stream of all agent events with causal chains |
| **Understand** emerged structure | `graph_find_nodes(kind="*")` → histogram of what agents built |

Developer-authored `AgentDefinition` classes live in `bootstrap/agents/`
and are discovered at startup via the same mtime-cached import pattern as v1
extension configs. The `AgentCatalog` tracks all registered definitions and
serves them to the runtime when nodes are discovered. A `remora agents list`
command prints the catalog; `remora inspect agent <id>` shows live state.

The delivery plan (§9) includes `remora inspect` by M5.

---

## 7. What Is Not Specified

v3 deliberately leaves the following unspecified. These are things the
bootstrap *process* determines, not things the concept document prescribes.

### Graph node kinds

v2 specified `code.function`, `code.class`, `spec.requirement`,
`spec.invariant`, `test.case`, `memory.episode`, `memory.insight`, and more.
v3 says: the graph can hold any nodes. The bootstrap agents decide what
they want to track. An agent that finds it useful to represent test coverage as
a graph edge adds that edge. One that doesn't, doesn't.

The only initial seeding is from the code discovery output: `CSTNode` objects
become nodes in the graph (with `node_id` from `compute_node_id()`). Their
`caller_ids` and `callee_ids` become edges. Everything beyond that is built by
agents.

### Graph edge kinds

v2 specified twelve named edge kinds with specific semantics and activation
policies. v3 says: edges carry a `kind` string and an `attrs` JSON blob.
The agents that create edges define what the kind means. If two agents agree
that `kind="tests"` means "this node tests that node," they'll use it that
way. The concept document doesn't dictate it.

### Protocol state machines

v2 specified `DirectTask`, `ViolationResponse`, and `CoverageGap` as
first-class typed state machines with explicit states and transitions.
v3 says: the substrate provides an event bus and subscriptions. Multi-step
workflows emerge from agents subscribing to each other's events. If the swarm
discovers it needs explicit state machines to prevent deadlocks, it can build
them — and the substrate (specifically, the graph + event ops) supports that.
But the concept document doesn't prescribe which protocols exist.

### Memory model

v2 specified `memory.episode` and `memory.insight` as first-class node kinds
with specific fields, TTLs, and distillation workflows. v3 says: agents can
write whatever they find useful to their cairn workspace or to the shared
graph. Memory is whatever the agents make of the substrate. If episodic
memory turns out to be useful, agents will build it from workspace files and
graph nodes. If a different structure works better, they'll build that.

### Agent roles

v2 specified `orchestrator`, `editor`, `reviewer`, `maintainer` as explicit
role kinds that gate tool access. v3 says: the externals dict is what gates
access. Agents with graph-write access have the mutation externals in their
dict. Agents without, don't. Role names are conventions agents may adopt;
they are not a runtime concept.

---

## 8. The Bootstrap Sequence

How the system builds itself from the substrate up.

### Phase 0: Substrate only

The runtime starts with:
- `CairnWorkspaceService` initialized (stable workspace + per-agent workspaces)
- Graph initialized (SQLite tables, empty)
- `EventBus` and `EventStore` initialized (v1, no changes)
- `BootstrapExternals` defined (file ops + graph ops + event ops)
- System `.pym` tools discoverable from `bootstrap/tools/`

The project source is synced into the stable workspace. `discover()` runs,
producing `CSTNode` objects. The runtime adds these as nodes in the graph
(using `graph_add_node`) and adds call relationship edges from `caller_ids`
and `callee_ids`.

No agents exist yet. No node kinds beyond "code node" exist. The graph is
a raw call graph seeded from tree-sitter.

### Phase 1: First agents

`NodeDiscoveredEvent` fires for each code node. The runtime creates an
AgentNode for each and activates it with `DEFAULT_SCHEMA`.

Each agent:
1. Reads its `role.md` (empty)
2. Calls `write_file("role.md", ...)` to define its own role based on its
   node type and the code it's responsible for
3. Calls `emit_schema(...)` with a richer schema that reads its source, recent
   events, and any workspace files it wants
4. Outputs `"done"`

Now each agent has a persisted schema. The next activation uses that schema.

### Phase 2: Agents communicating

Agents start seeing each other's events (via `read_recent_events`) and
calling `emit_event` to signal each other. Patterns emerge:
- An agent that changes a function emits an event; its callers notice and
  check if they need to adapt
- An agent that finds a problem writes to its workspace and emits an event
  describing the problem; a neighboring agent picks it up

Agents add edges to the shared graph to record relationships they discover.
These edges become queryable by other agents in their context pipelines.

### Phase 3: Structure accumulates

Recurring patterns get crystallized. If agents keep emitting events with
`kind="test_needed"`, some agent will subscribe to those and propose tests.
If agents keep querying a particular relationship, they'll start recording it
explicitly in the graph rather than recomputing it each time.

The swarm decides what structure is useful. The concept document gets out of
the way.

---

## 9. Delivery Plan

### M0: Substrate types (1–2 days)

Deliverables:
- `BootstrapEvent` dataclass with causal envelope (`event_id`, `correlation_id`,
  `causal_parent_id`, `depth`, `agent_id`, `timestamp`, `payload`)
- `BootstrapExternals` class extending `CairnExternals` with stub graph and
  event ops (stubs that raise `NotImplementedError` — wire real impls in M1–M2)
- `TurnSchema` / `ContextPipeline` / etc. from `primitives.py` (already
  implemented — needs integration tests against the runtime)
- `DEFAULT_SCHEMA` constant
- `emit_schema` system `.pym` tool (writes `schema.json` to agent workspace)

Tests: type construction, serialization, `emit_schema` tool with mock externals.

Not included: real graph, real event emission, real LLM.

### M1: Graph substrate (2–3 days)

Deliverables:
- SQLite property graph: `bootstrap_nodes` + `bootstrap_edges` tables with
  indexes
- Real implementations of `graph_add_node`, `graph_add_edge`,
  `graph_remove_node`, `graph_remove_edge`, `graph_neighbors`,
  `graph_find_nodes`, `graph_node` in `BootstrapExternals`
- Startup seeding: `CSTNode` → graph nodes, `caller_ids`/`callee_ids` → edges
- System `.pym` tools: `graph_neighbors.pym`, `graph_find_nodes.pym`,
  `graph_node.pym`

Tests: CRUD, neighborhood queries, index performance, seeding from CSTNode.

### M2: Event bus integration (1–2 days)

Deliverables:
- `emit_event` and `read_recent_events` real implementations in
  `BootstrapExternals` (wiring into `EventBus` + `EventStore`)
- `emit_event.pym` and `read_recent_events.pym` system tools
- `BootstrapEvent` persistence in `EventStore` (append via existing path)
- Causal envelope enforcement (runtime sets `causal_parent_id` and `depth`)

Tests: event round-trip, causal depth increment, depth limit rejection.

### M3: Turn executor + primitives integration (2–3 days)

Deliverables:
- Turn executor that resolves `TurnSchema`: system prompt, `ContextPipeline`,
  LLM loop with `.pym` tools
- `ToolRef` resolution: call named `.pym` tool via Grail, interpolate
  `$step_name` args
- `InputGate` resolution: pause pipeline, collect user input, resume
- Failure classification (`PARSE_FAILURE`, `TIMEOUT`, etc.)
- `DEFAULT_SCHEMA` runtime + `schema.json` loading per agent

Tests: all failure outcomes exercised synthetically (mock externals),
`ContextPipeline` step chaining, `InputGate` in interactive + batch modes.

### M4: Rustworkx + algorithmic queries (1–2 days)

Deliverables:
- `rustworkx` added as dependency
- `trace_causal_chain` external: loads event subgraph into Rustworkx,
  returns causal ancestors/descendants with depth
- Depth enforcement: `ProtocolEngine` reads `event.depth` against configured
  `max_depth`; exceeding it emits `DepthLimitExceededEvent`
- Cycle detection utility: used by the runtime to detect agent activation
  loops (replacement for v1's `_check_depth_limit` cooldown heuristic)

Tests: causal chain traversal, depth enforcement, cycle detection.

### M5: Self-bootstrapping end-to-end (2–3 days)

Deliverables:
- Full activation flow: `NodeDiscoveredEvent` → `DEFAULT_SCHEMA` turn →
  agent writes `role.md` + calls `emit_schema` → `schema.json` stored
- Second activation uses stored `schema.json`
- `emit_schema.pym` and `read_file.pym` as the minimal bootstrap tool set
- End-to-end test with a real small Python project and a real (or mocked) LLM

Tests: two-activation sequence deterministic (first uses DEFAULT, second uses
stored), schema round-trip fidelity.

### M6: Adapter integration (2–3 days)

Deliverables:
- Feature flag: `REMORA_PHASE2_RUNTIME=1`
- When set: route agent activations through the bootstrap turn executor
  instead of the v1 `execute_agent_turn()`
- Neovim LSP: `HumanChatEvent` triggers a bootstrap turn on the focused
  agent node
- Parallel event logging: bootstrap events emitted alongside legacy v1 events

Tests: end-to-end through the LSP adapter with mock LLM; CLI `remora swarm
start` with flag set.

---

*This document supersedes v2 as the implementation guide for Phase 2.*
*It specifies the substrate; what gets built on it is determined by the*
*bootstrap process, not by this document.*
