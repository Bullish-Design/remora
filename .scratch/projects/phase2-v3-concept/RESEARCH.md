# Research: AgentNode Pattern → Bootstrap v3

> How the v1 EventBased agent model informs the bootstrap primitive-first design.
> Exploring how Pydantic models and capability layering can "build up" swarm
> capability from the primitives instead of prescribing it upfront.

---

## 1. What v1 Got Right: The Three-Role Model

The `AgentNode` in `EventBased_Concept.md` is the single most important design
decision in v1, and it's worth understanding exactly what it achieves before
asking how the bootstrap should learn from it.

`AgentNode` is a single Pydantic `BaseModel` that serves three roles
simultaneously:

1. **DB schema** — fields serialize directly to/from the `nodes` SQLite table
2. **LLM prompt context** — `to_system_prompt()` generates the agent's system
   prompt from the same fields
3. **LSP protocol data** — `to_code_lens()`, `to_hover()`, `to_code_actions()`
   convert directly to Neovim LSP responses

There is one object. Reading it gives you everything: where the agent is in the
code, what it's thinking about, what it's currently doing, how to render it in
the editor. No translation layer, no intermediate representation.

The v3 bootstrap needs an equivalent. Not an LSP-facing triple role, but
the same principle: **one model that carries everything needed to understand
and run a bootstrap agent**.

---

## 2. The Data-Over-Subclasses Principle

v1 explicitly rejected class inheritance for specialization. The quote from
the document:

> "There is no `TestAgentNode` subclass or `RouteAgentNode` subclass. Every
> agent in the system is an `AgentNode` instance. Behavioral differences come
> from **different field values**, populated by extension configs at discovery
> time."

The reasons given:
1. Events are the behavioral mechanism — agents differ in subscriptions, tools,
   and system prompt. All of these are data.
2. Hot-reload works — extension configs are Python files loaded with mtime-based
   caching. No class identity issues.
3. DB serialization is trivial — one table, flat fields, same schema for all
   agents.

This principle should carry into the bootstrap. But the user's question opens
a productive tension: **Pydantic inheritance as a developer-facing authoring
tool vs. as a runtime mechanism**.

These are different. The claim that runtime agents should not use inheritance
is compatible with the claim that developers should use Pydantic models/
inheritance to author capability definitions that then produce data.

---

## 3. The Extension Config Pattern

v1's extension system is the key mechanism:

```python
class TestFunctionExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "function" and name.startswith("test_")

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "TestFunction",
            "custom_system_prompt": "...",
            "extra_tools": [ToolSchema(name="run_test", ...)],
            "extra_subscriptions": [
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="src/**/*.py"),
            ],
        }
```

An extension config:
1. **Matches** a code pattern by node_type and name
2. **Returns data** — field values that get merged into the AgentNode at
   discovery time
3. Produces **no new class** — the resulting AgentNode is always `AgentNode`

The bootstrap equivalent: what gets written to `role.md` and `schema.json`
during the first activation IS the extension config. The agent itself determines
what data goes into its own "extension fields." This is the self-bootstrapping
sequence — an agent that discovers its own purpose and writes its own
specialization data.

But there's a gap. In v1, extension configs are written by developers and loaded
at startup. In the bootstrap, they're written by agents at first activation. Both
mechanisms produce the same output: data in fields.

---

## 4. The Future the EventBased Doc Pointed At

Section 8 of `EventBased_Concept.md` is the most important passage for the
bootstrap design. It describes what v1 was heading toward:

> "Custom query packs in `.remora/queries/` — This would discover
> `node_type="route"` nodes — Flask route handlers get their own node type."

> "These semantic relationships would be stored in the `edges` table (via
> **LazyGraph/rustworkx**)"

> "EdgeType.CONFIGURES: ("toml:table:database", "python:class:DatabasePool")
> EdgeType.IMPLEMENTS: ("python:function:get_user", "python:class:UserProtocol")
> EdgeType.TESTS: ("python:function:test_get_user", "python:function:get_user")"

This is significant: **rustworkx was already identified as the graph library for
v1's edge table**. The semantic graph in bootstrap v3 is not a new idea — it's
the direct continuation of what v1 was building toward.

The bootstrap is v1's future realized: instead of developers writing extension
configs that add semantic edges manually, **agents discover and write the
semantic relationships themselves**. The edges emerge from the bootstrap process
rather than from developer configuration.

---

## 5. The Tension: Structure vs. Emergence

The v3 concept deliberately leaves node kinds, edge kinds, and protocol state
machines unspecified — letting the bootstrap process determine them. But the
v1 model points at a specific structure that works: AgentNode with defined
fields.

This is not a contradiction. There are two different things:

- **The agent model** (what an agent IS, what fields it has) — this SHOULD be
  specified. It's the substrate.
- **The agent taxonomy** (what kinds of agents exist, what they do) — this
  should NOT be specified. It emerges.

The v3 concept specified neither. But we can specify the agent model without
specifying the taxonomy. An `AgentNode` doesn't know it's a "TestFunction" or
a "RouteHandler" — the extension data just happens to have those values. The
type system doesn't have those as named types.

The bootstrap equivalent: we need to specify `BootstrapAgent` (the model) while
leaving the concrete kinds of bootstrap agents (what roles emerge) unspecified.

---

## 6. Brainstorming: What Is `BootstrapAgent`?

Taking v1's three-role model as a guide, what are the three (or N) roles for a
bootstrap agent?

### Candidate roles

**Role 1: Graph node.** A bootstrap agent IS a node in the semantic graph. Its
node_id, kind, and attributes are stored there. Reading the graph gives you the
agent. The graph is the source of truth, just as the `nodes` SQLite table is
v1's source of truth.

**Role 2: Turn executor.** The bootstrap agent has a `TurnSchema` (loaded from
`schema.json` in its cairn workspace). The runtime resolves this schema and
runs the LLM loop. `TurnSchema` here is the equivalent of `to_system_prompt()`
+ the bundle manifest — it describes the turn completely.

**Role 3: Event subscriber.** The agent has a list of `SubscriptionPattern`
entries that determine what events trigger it. These are stored in the existing
`SubscriptionRegistry`. This is already in v1.

So a minimal `BootstrapAgent` model:

```python
class BootstrapAgent(BaseModel):
    """A bootstrap agent: graph node + turn schema + subscriptions."""

    # Identity (maps to a graph node of kind "agent.profile")
    node_id: str
    name: str
    full_name: str       # e.g., "agent:bootstrap_docstring_reviewer"

    # Capability grant (determines which externals are in the dict)
    capabilities: frozenset[Capability]

    # Current turn shape (loaded from schema.json in cairn workspace)
    # None = use DEFAULT_SCHEMA
    schema: TurnSchema | None = None

    # Runtime state (derived from events, like AgentNode.status)
    status: str = "idle"    # "idle", "running", "error"
    last_trigger_event: str = ""
    last_completed_at: float | None = None

    # Subscription patterns (like AgentNode.extra_subscriptions)
    subscriptions: list[SubscriptionPattern] = Field(default_factory=list)

    # Self-description (like AgentNode.extension_name + custom_system_prompt)
    # Written by the agent to its cairn workspace (role.md + schema.json)
    extension_name: str | None = None
```

This is the core. Now the question is: how does capability layering work?

---

## 7. Brainstorming: Capability Layering

The user's instinct — Pydantic models and inheritance — is strongest here.

### Option A: Enum + frozenset (data-driven, v1-style)

```python
class Capability(str, Enum):
    FILE_READ  = "file_read"    # read_file, list_dir, file_exists, search_*
    FILE_WRITE = "file_write"   # write_file, submit_result
    GRAPH_READ = "graph_read"   # graph_node, graph_neighbors, graph_find_nodes
    GRAPH_WRITE = "graph_write" # graph_add_node, graph_add_edge, graph_remove_*
    EVENT_EMIT  = "event_emit"  # emit_event
    EVENT_READ  = "event_read"  # read_recent_events
    SCHEMA_EVOLVE = "schema_evolve"  # emit_schema tool in TurnSchema.tools
    TOOL_SYNTHESIZE = "tool_synthesize"  # write_workspace_file for new .pym tools
    PRIVILEGED  = "privileged"  # update_subscription, register_protocol
```

The `BootstrapExternals` class checks `agent.capabilities` to decide which
functions to include in `as_externals()`. Different agents get different dicts.

**Pros:** Simple, serializable, queryable in the graph (`find_nodes(kind="agent.profile", attr_filter='{"capabilities": "graph_write"}')`).

**Cons:** Capability sets might interact in non-obvious ways. No compile-time
verification that a given capability set is coherent.

### Option B: Protocol classes (structural typing for capabilities)

```python
class FileReadingAgent(Protocol):
    """Any agent that can read files."""
    node_id: str

class GraphReadingAgent(FileReadingAgent, Protocol):
    """Any agent that can also query the graph."""
    pass

class GraphWritingAgent(GraphReadingAgent, Protocol):
    """Any agent that can also mutate the graph."""
    pass
```

Runtime agents are all `BootstrapAgent` instances. Protocol classes are used
only for type checking — to verify that when you call a function that needs
graph-write access, you're passing the right kind of agent.

**Pros:** No runtime cost. Type checker catches capability mismatches at call
sites. Clean separation of "what this agent can do" from "what this agent is."

**Cons:** Doesn't help with the runtime question of "which externals go in this
agent's dict." Still need the Capability enum for that.

### Option C: Capability mixin Pydantic models (actual inheritance)

```python
class CoreAgent(BaseModel):
    """Minimal agent: has an identity and a cairn workspace."""
    node_id: str
    status: str = "idle"
    schema: TurnSchema | None = None

class FileAgent(CoreAgent):
    """Can read from its cairn workspace."""
    # Externals: read_file, list_dir, file_exists, search_*, log
    pass

class FileWriteAgent(FileAgent):
    """Can also write to its cairn workspace."""
    # Externals: + write_file, submit_result
    pass

class GraphReadAgent(FileWriteAgent):
    """Can query the semantic graph."""
    # Externals: + graph_node, graph_neighbors, graph_find_nodes
    pass

class GraphWriteAgent(GraphReadAgent):
    """Can mutate the semantic graph."""
    # Externals: + graph_add_node, graph_add_edge, graph_remove_*
    pass

class EventAgent(GraphReadAgent):
    """Can emit and read events."""
    # Externals: + emit_event, read_recent_events
    pass

class FullAgent(GraphWriteAgent, EventAgent):
    """Can do everything non-privileged."""
    subscriptions: list[SubscriptionPattern] = Field(default_factory=list)
    extension_name: str | None = None

class PrivilegedAgent(FullAgent):
    """Can modify the substrate (subscriptions, protocols)."""
    # Externals: + update_subscription, register_protocol
    pass
```

**Pros:** Class hierarchy IS the capability hierarchy. No separate Capability
enum. The model's class tells you its capability level. Pydantic handles
serialization.

**Cons:** Multiple inheritance gets messy (diamond problem if EventAgent and
GraphWriteAgent both inherit from GraphReadAgent). Class hierarchy is rigid
— you can't easily add "a graph-write agent that can't emit events."

**The diamond problem:**
```
CoreAgent
    └─ FileAgent
        └─ FileWriteAgent
            └─ GraphReadAgent
                ├─ GraphWriteAgent
                └─ EventAgent
                    └─ FullAgent (inherits from both GraphWriteAgent and EventAgent)
```

Python's MRO handles this, but Pydantic's field resolution in diamond
hierarchies can be surprising. Not a dealbreaker but requires care.

### Option D: AgentDefinition concept (the authoring layer)

The most productive framing: separate the **authoring model** from the **runtime
model**, just as v1 separated extension configs (authoring) from AgentNode
(runtime).

```python
# The authoring model — developers/agents write these
class AgentDefinition(BaseModel):
    """Describes what a bootstrap agent should be. Produces BootstrapAgent."""
    name: str
    role_description: str          # goes into role.md
    capabilities: set[Capability]  # determines externals dict
    context_steps: tuple[Step, ...] = ()  # appended to DEFAULT_SCHEMA pipeline
    tools: tuple[str, ...] = ()    # added to TurnSchema.tools
    subscriptions: list[SubscriptionPattern] = Field(default_factory=list)
    max_turns: int = 5
    termination: str = "done"

    def to_turn_schema(self) -> TurnSchema:
        """Convert this definition to a TurnSchema."""
        return TurnSchema(
            system=Concat(parts=(
                "You are responsible for: ",
                ToolRef("read_file", {"path": "role.md"}),
            )),
            context=ContextPipeline(steps=(
                Step("role", ToolRef("read_file", {"path": "role.md"})),
                *self.context_steps,
            )),
            tools=self.tools,
            max_turns=self.max_turns,
            termination=self.termination,
        )

    def to_bootstrap_agent(self, node_id: str) -> "BootstrapAgent":
        """Instantiate a runtime BootstrapAgent from this definition."""
        return BootstrapAgent(
            node_id=node_id,
            name=self.name,
            capabilities=frozenset(self.capabilities),
            schema=self.to_turn_schema(),
            subscriptions=self.subscriptions,
        )


# The runtime model — what actually runs
class BootstrapAgent(BaseModel):
    node_id: str
    name: str
    capabilities: frozenset[Capability]
    schema: TurnSchema | None = None
    status: str = "idle"
    subscriptions: list[SubscriptionPattern] = Field(default_factory=list)
```

**This is where Pydantic inheritance shines as an authoring tool:**

```python
class BaseCodeAgentDefinition(AgentDefinition):
    """Base for any agent that works on code nodes."""
    capabilities: set[Capability] = {
        Capability.FILE_READ,
        Capability.FILE_WRITE,
        Capability.GRAPH_READ,
        Capability.EVENT_EMIT,
        Capability.SCHEMA_EVOLVE,
    }
    context_steps: tuple[Step, ...] = (
        Step("source", ToolRef("read_file", {"path": "$node.file_path"})),
        Step("history", ToolRef("read_recent_events", {"node_id": "$node.id"})),
    )
    tools: tuple[str, ...] = (
        "write_file", "emit_event", "emit_schema", "graph_neighbors",
    )
    subscriptions: list[SubscriptionPattern] = [
        SubscriptionPattern(to_agent="$self"),  # direct messages
    ]


class DocstringAgentDefinition(BaseCodeAgentDefinition):
    """Specializes for docstring maintenance."""
    name: str = "docstring_agent"
    role_description: str = "You maintain docstrings for $node.full_name."
    context_steps: tuple[Step, ...] = (
        # Inherits base steps + adds docstring-specific reads
        *BaseCodeAgentDefinition.context_steps,
        Step("node_source", ToolRef("extract_node_source", {"node": "$node.id"})),
        Step("current_doc", ToolRef("extract_docstring", {"source": "$node_source"})),
        Step("drift_signal", ToolRef("score_docstring_alignment", {
            "docstring": "$current_doc",
            "implementation": "$node_source",
            "threshold": "0.75",
        }, extract="signal")),
    )
    tools: tuple[str, ...] = (
        *BaseCodeAgentDefinition.tools,
        "rewrite_docstring",
    )


class SignatureWatcherDefinition(BaseCodeAgentDefinition):
    """Specializes for signature change detection and propagation."""
    name: str = "signature_watcher"
    role_description: str = "You detect and propagate signature changes for $node.full_name."
    context_steps: tuple[Step, ...] = (
        *BaseCodeAgentDefinition.context_steps,
        Step("current_sig", ToolRef("extract_signature", {"node": "$node.id"})),
        Step("previous_sig", ToolRef("read_file", {"path": "last_known_signature.txt"})),
        Step("sig_diff", ToolRef("diff_signatures", {
            "before": "$previous_sig", "after": "$current_sig",
        }, extract="diff")),
        Step("callers", ToolRef("graph_neighbors", {
            "node_id": "$node.id", "edge_kind": "calls", "direction": "in",
        })),
    )
    tools: tuple[str, ...] = (
        *BaseCodeAgentDefinition.tools,
        "graph_add_edge",  # to record detected relationships
    )
    capabilities: set[Capability] = {
        *BaseCodeAgentDefinition.capabilities,
        Capability.GRAPH_WRITE,  # needs to write edges
    }
```

This is the pattern: `AgentDefinition` subclasses use Pydantic field
inheritance to build up capability from a base. The base handles common
context steps, the subclass adds domain-specific ones. `capabilities` is
additive (union of base + additions). `context_steps` is concatenative
(base steps + new steps).

**Why this is good:**
- Inheritance is used ONLY for authoring — developers write definitions,
  not runtime code
- Runtime agents are always `BootstrapAgent` instances — no class hierarchy
  at runtime
- Definitions convert to TurnSchema via `to_turn_schema()` — the schema is
  the runtime representation
- Capabilities are still enum-based → externals dict is still data-driven

**The self-bootstrapping fit:**
The first activation sequence is: DEFAULT_SCHEMA → agent discovers its
purpose → writes `role.md` → calls `emit_schema`. What if instead of
writing raw JSON, the agent calls `emit_definition` with a structured
`AgentDefinition`? The runtime would then:
1. Validate the definition (capabilities within granted bounds)
2. Call `definition.to_turn_schema()` to get the TurnSchema
3. Store `schema.json` in the cairn workspace

The agent authors its own `AgentDefinition` during first activation. On
subsequent activations, the runtime loads `schema.json` and uses it
directly — no re-parsing the definition needed.

---

## 8. The Critical v1 Insight for Bootstrap: Subscriptions as the Behavioral Mechanism

v1's event document says:

> "Events are the behavioral mechanism. Agents don't differ in how they
> process Python method calls — they differ in what events they subscribe
> to, what tools they have, and what their system prompt says. All of
> these are data."

For the bootstrap, this means: two bootstrap agents that do completely
different things are still both `BootstrapAgent` instances. Their
difference is:
- Different `schema.json` (different TurnSchema → different context steps,
  different tools, different system prompt)
- Different `subscriptions` (what events trigger them)
- Different `capabilities` (which externals are in their dict)

You don't define "a docstring agent" as a class. You define a `BootstrapAgent`
instance whose schema has the docstring-specific context pipeline and whose
subscription pattern is `ContentChangedEvent` for its node's file.

**The subscription patterns are what orchestrate the swarm.** No central
coordinator. No hardcoded workflow. An agent that emits `FileSavedEvent`
with a `tags=["signature_changed"]` payload doesn't know who will respond.
The callers that subscribed to `("FileSavedEvent", tags=["signature_changed"])`
will respond. This is emergence, bounded by subscriptions.

---

## 9. Brainstorming: How Agents "Build Up" Capability

The most interesting question: in the bootstrap process, how do agents
accumulate capability over time?

### Mechanism A: Capability grant events

The system starts all agents with minimal capabilities. An agent that
wants more sends a `RequestCapabilityEvent`. The privileged (maintainer)
agent evaluates the request and sends a `GrantCapabilityEvent`. The
runtime updates the agent's externals dict.

This creates a natural trust hierarchy without hardcoding it:
- New agent: FILE_READ + FILE_WRITE + SCHEMA_EVOLVE
- After proving stability (low error rate, consistent output): GRAPH_READ
- After demonstrating good graph usage: GRAPH_WRITE
- After extensive testing: EVENT_EMIT + PRIVILEGED

The agent's capability set is stored in the graph (as an attribute on its
`agent.profile` node). The externals dict is rebuilt from this on each
activation.

### Mechanism B: Schema step accumulation

The TurnSchema is the agent's current capability expression. An agent
accumulates capability by building up its TurnSchema over many activations:

- Activation 1: DEFAULT_SCHEMA (empty context, emit_schema tool)
- Activation 2 (after role.md written): schema with source + history steps
- Activation 3 (after discovering it needs graph): schema adds graph_neighbors step
- Activation 10 (mature agent): rich schema with many context steps, proven tools

Each time the agent calls `emit_schema` with a richer schema, it's
accumulating capability. The schema.json in cairn workspace is the
accumulated state of this process.

This mechanism requires no central grant process. The agent grows its
own schema. The externals dict must be broad enough to support the
richest possible schema — but the agent only calls the externals it
actually uses.

### Mechanism C: Tool synthesis as capability creation

From the Primitives Walkthrough Appendix III: agents can write new `.pym`
tools to their cairn workspace. This is the most radical form of capability
accumulation. An agent that needs a capability that doesn't exist...
creates it.

A tool that collapses three steps into one (e.g., `read_public_api.pym`)
is a new capability. The agent that writes it gains a new tool. Via
schema diffusion, other agents can adopt it.

This requires TOOL_SYNTHESIZE capability (write_workspace_file must be
in the agent's externals dict for its workspace). But the point is: once
granted, the agent can CREATE new capabilities.

### The capability ladder (synthesizing all three)

```
                  PRIVILEGED
                  └─ can modify substrate (subscriptions, protocols)
              TOOL_SYNTHESIZE
              └─ can write new .pym tools to workspace
          GRAPH_WRITE
          └─ can add/remove nodes and edges
      GRAPH_READ + EVENT_EMIT
      └─ can query the graph, emit causal events
  FILE_READ + FILE_WRITE + SCHEMA_EVOLVE
  └─ can read/write workspace, emit_schema (base)
ALL AGENTS START HERE
```

Each rung is earned through demonstrated behavior. New agents start at
the bottom and climb based on what the runtime/maintainer grants.

---

## 10. Key Design Synthesis

Putting it all together, here is what the v1 → v3 mapping looks like:

| v1 Concept | Bootstrap v3 Equivalent |
|------------|------------------------|
| `AgentNode` (single runtime model) | `BootstrapAgent` (single Pydantic model) |
| `extension_name` field | `extension_name` field (same name, same idea) |
| `custom_system_prompt` | `role.md` in cairn workspace |
| `extra_tools` field | `TurnSchema.tools` (what the LLM can call) |
| `extra_subscriptions` field | `BootstrapAgent.subscriptions` |
| Extension config `matches()` | Agent's first-activation role.md write |
| Extension config `get_extension_data()` | Agent's first-activation `emit_schema` call |
| `to_system_prompt()` | `TurnSchema.system` (resolved at runtime) |
| `to_code_lens()` | Not applicable (bootstrap is not LSP-facing) |
| `nodes` SQLite table | Semantic graph (bootstrap_nodes table) |
| `edges` table (LazyGraph/rustworkx) | Bootstrap graph (SQLite + Rustworkx) |
| EventBus type-based dispatch | Same EventBus (v1, no changes) |
| SubscriptionRegistry | Same SubscriptionRegistry (v1, no changes) |
| `bundle.yaml` | `schema.json` in cairn workspace |
| `bundle_mapping` in remora.yaml | AgentDefinition.to_turn_schema() |

The AgentDefinition concept is the authoring equivalent of the extension
config. Pydantic inheritance works great for AgentDefinition (authoring)
while runtime agents remain flat `BootstrapAgent` instances.

---

## 11. What This Changes in the v3 Concept

The v3 concept currently specifies "the substrate" and leaves everything
else to emerge. Adding the `BootstrapAgent` model and `AgentDefinition`
authoring pattern doesn't violate this — it specifies the agent model
without specifying the agent taxonomy.

**What to add to v3:**

1. `BootstrapAgent` model: the runtime representation. Fields: node_id,
   name, capabilities (frozenset[Capability]), schema (TurnSchema | None),
   status, subscriptions. Stored as a graph node (kind="agent.profile").

2. `Capability` enum: the explicit set of capability levels. Determines
   which externals are in the dict. Not a taxonomy of agent types — just
   a set of what operations are available.

3. `AgentDefinition` as the authoring mechanism: Pydantic model with
   inheritance support. Developers (or self-bootstrapping agents) produce
   AgentDefinitions that convert to TurnSchemas and BootstrapAgent instances.

4. The capability ladder: how agents earn capabilities over time. Either
   through RequestCapabilityEvent/GrantCapabilityEvent, or through the
   TurnSchema accumulation mechanism, or both.

**What NOT to add to v3:**

- Specific AgentDefinition subclasses (DocstringAgentDefinition, etc.)
  These emerge from the bootstrap process
- Named agent roles (orchestrator, editor, reviewer, maintainer)
  These are just AgentDefinition instances with different capabilities
- Fixed protocol state machines
  These emerge from subscriptions and events

---

## 12. Open Questions

1. **Capability grant mechanism**: Should capabilities be centrally granted
   (maintainer agent processes requests) or self-assigned (agents request
   what they need, system approves by policy)? The central grant is safer
   but creates a bottleneck. Policy-based approval is more scalable.

2. **AgentDefinition persistence**: Where do AgentDefinitions live? In
   cairn workspaces? In the graph? In Python files (like v1 extension
   configs)? The answer affects whether they're agent-authored or
   developer-authored.

3. **Inheritance depth**: How deep should AgentDefinition inheritance go?
   One level (BaseCode → Specific) feels right. More than two levels
   creates fragility — the v1 lesson about not over-specifying applies here.

4. **The first activation gap**: The first activation uses DEFAULT_SCHEMA.
   The agent writes role.md and calls emit_schema. But what if the agent
   writes a bad schema (e.g., requests capabilities it doesn't have, or
   uses tools that don't exist)? Need a validation layer in the emit_schema
   tool that checks the schema against the agent's capability set.

5. **Schema diffusion and inheritance**: When Schema Diffusion (Primitives
   Walkthrough Appendix II) spreads a useful context step to neighboring
   agents, are those agents implicitly "inheriting" a step from another
   agent's definition? This is emergent inheritance — agents building on
   each other's schemas without a formal hierarchy. This is probably the
   RIGHT kind of inheritance for the bootstrap.

---

## 13. Recommended Next Step

Update the v3 concept document to include:
- `BootstrapAgent` as the single runtime model (following v1's AgentNode)
- `Capability` enum as the capability classification
- `AgentDefinition` as the authoring/self-bootstrapping mechanism
- How first activation produces an AgentDefinition (via emit_schema)
- How the three concepts compose: agent IS a graph node IS a schema IS a
  subscriber

The additions are minimal — they specify the agent model without
specifying the agent taxonomy. The "what emerges" section remains
unchanged: we still don't specify node kinds, edge kinds, or protocols.
We just specify what the agents that create those things look like.
