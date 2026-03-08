# Research: Mixin Patterns, Developer Ergonomics, and Authoring Ideas

> Continuation of RESEARCH.md. The first research document established the
> core BootstrapAgent / Capability / AgentDefinition triad. This document
> explores more deeply:
>
> 1. Pydantic mixin baseclasses as a capability composition pattern
> 2. Developer ergonomics: how to make the swarm readable, writable, and
>    understandable from the outside
> 3. Other authoring patterns not yet explored (decorators, builders, etc.)
> 4. Emergent composition: how agents inherit from each other's schemas
> 5. The developer interaction surface: inspect, inject, correct, understand

---

## Table of Contents

1. [Pydantic Mixin Baseclasses: Full Exploration](#1-pydantic-mixin-baseclasses-full-exploration)
   The diamond problem in practice. Mixin field resolution. Comparison with
   AgentDefinition inheritance. When mixins win, when they don't.

2. [Other Authoring Patterns](#2-other-authoring-patterns)
   Decorators, builders, YAML definitions, Protocol structural typing,
   and dataclass approaches. Pros, cons, and when each fits.

3. [Developer Ergonomics: Making the Swarm Legible](#3-developer-ergonomics-making-the-swarm-legible)
   Query patterns, CLI inspection, the agent catalog, TurnSchema as a
   readable format, and hot-reload for developer-authored definitions.

4. [Emergent Composition: Schema Diffusion as Inheritance](#4-emergent-composition-schema-diffusion-as-inheritance)
   How agents "inherit" from each other's schemas without a formal hierarchy.
   The genome metaphor. Controlled vs. uncontrolled diffusion.

5. [The Developer Interaction Surface](#5-the-developer-interaction-surface)
   Inject, pause, inspect, correct, understand. The six operations a developer
   needs when working with a live swarm.

6. [Synthesis: Recommended Authoring Stack](#6-synthesis-recommended-authoring-stack)
   Combining the best of each approach. What to include in v3. What to leave
   for the swarm to define.

---

## 1. Pydantic Mixin Baseclasses: Full Exploration

### 1.1 The core idea

A mixin is a class designed to be composed into another via multiple
inheritance. Unlike abstract base classes, mixins provide concrete field
definitions and (optionally) methods. The composing class gets all the mixin
fields by virtue of Python's MRO resolution.

For capability composition, the idea:

```python
class FileReadMixin(BaseModel):
    """Mixin: agent can read from its cairn workspace."""
    # No added fields — capability is structural, not data
    # The presence of this mixin in the MRO means FILE_READ is granted.
    pass

class FileWriteMixin(FileReadMixin):
    """Mixin: agent can also write."""
    pass

class GraphReadMixin(BaseModel):
    """Mixin: agent can query the semantic graph."""
    pass

class GraphWriteMixin(GraphReadMixin):
    """Mixin: agent can also mutate the graph."""
    pass

class EventEmitMixin(BaseModel):
    """Mixin: agent can emit events."""
    pass

class EventReadMixin(EventEmitMixin):
    """Mixin: agent can also read recent events."""
    pass

class SchemaEvolveMixin(BaseModel):
    """Mixin: agent can call emit_schema to evolve its own TurnSchema."""
    pass
```

A concrete definition composes what it needs:

```python
class DocstringAgentDefinition(
    FileWriteMixin,    # read + write workspace
    GraphReadMixin,    # query graph
    EventEmitMixin,    # emit events
    SchemaEvolveMixin, # evolve own schema
    AgentDefinition,   # base
):
    name: str = "docstring_agent"
    role_description: str = "You maintain docstrings for $node.full_name."
    context_steps: tuple[Step, ...] = (
        Step("source", ToolRef("read_file", {"path": "$node.file_path"})),
        Step("current_doc", ToolRef("extract_docstring", {"path": "$node.file_path"})),
    )
    tools: tuple[str, ...] = ("write_file", "emit_event", "emit_schema")
```

The class hierarchy encodes capabilities. The runtime can introspect the MRO
to determine what capability set to grant:

```python
MIXIN_TO_CAPABILITY = {
    FileReadMixin: Capability.FILE_READ,
    FileWriteMixin: Capability.FILE_WRITE,
    GraphReadMixin: Capability.GRAPH_READ,
    GraphWriteMixin: Capability.GRAPH_WRITE,
    EventEmitMixin: Capability.EVENT_EMIT,
    EventReadMixin: Capability.EVENT_READ,
    SchemaEvolveMixin: Capability.SCHEMA_EVOLVE,
    ToolSynthesizeMixin: Capability.TOOL_SYNTHESIZE,
    PrivilegedMixin: Capability.PRIVILEGED,
}

def capabilities_from_definition(defn_class: type) -> frozenset[Capability]:
    return frozenset(
        cap for mixin, cap in MIXIN_TO_CAPABILITY.items()
        if issubclass(defn_class, mixin)
    )
```

The `capabilities` field on `AgentDefinition` doesn't need to be set manually
— it's derived from the class's inheritance chain.

### 1.2 The diamond problem in Pydantic

The Pydantic diamond problem arises when two mixins share a common base that
defines fields:

```
     BaseModel
      /    \
FileReadMixin   GraphReadMixin
      \    /
  ConcreteAgent    <-- inherits FileReadMixin AND GraphReadMixin
```

If `FileReadMixin` and `GraphReadMixin` both define fields, Pydantic uses
Python's MRO (C3 linearization) to resolve them. With `BaseModel` as the root
and no conflicting fields, this works fine. The problem is:

1. **Field redeclaration conflicts.** If both `FileWriteMixin` (which extends
   `FileReadMixin`) and `GraphWriteMixin` (which extends `GraphReadMixin`) are
   in the MRO alongside each other, and both declare a `_capability_set` class
   variable, MRO picks the first one found — not a merge.

2. **Validator inheritance.** If a mixin declares a `@model_validator`, all
   subclasses inherit it. Stacking many mixins means stacking many validators
   — potentially surprising performance or validation order issues.

3. **The frozen field issue.** If the concrete class uses `model_config =
   ConfigDict(frozen=True)`, all mixin fields inherit this. This is usually
   what you want for immutable agent definitions, but something to verify.

**In practice, with capability mixins that add no fields**, the diamond problem
essentially disappears. The mixins are marker classes — they add no fields,
only MRO membership. Python MRO handles this without issue:

```
     BaseModel
      /    \
FileReadMixin   EventEmitMixin
      |               |
FileWriteMixin    (no subclasses)
         \        /
      DocstringAgent
```

Python's MRO for `DocstringAgent`: `DocstringAgent → FileWriteMixin →
FileReadMixin → EventEmitMixin → BaseModel`. No conflicts. `capabilities_from_definition(DocstringAgent)` returns `{FILE_READ, FILE_WRITE, EVENT_EMIT}` by issubclass checks.

**The diamond gets real** when someone does:

```python
class FullCodeAgent(FileWriteMixin, GraphWriteMixin, EventReadMixin, SchemaEvolveMixin):
    pass
```

Where `GraphWriteMixin(GraphReadMixin)` and `EventReadMixin(EventEmitMixin)`
are both in the MRO. Python's C3 works: `FullCodeAgent → FileWriteMixin →
FileReadMixin → GraphWriteMixin → GraphReadMixin → EventReadMixin →
EventEmitMixin → SchemaEvolveMixin → AgentDefinition → BaseModel`.

No issues with pure-marker mixins. Issues would only arise if mixins defined
overlapping fields or validators.

### 1.3 Comparison with AgentDefinition + set[Capability]

The alternative from RESEARCH.md is:

```python
class DocstringAgentDefinition(AgentDefinition):
    name: str = "docstring_agent"
    capabilities: set[Capability] = {
        Capability.FILE_READ, Capability.FILE_WRITE,
        Capability.GRAPH_READ, Capability.EVENT_EMIT,
        Capability.SCHEMA_EVOLVE,
    }
    # ...
```

| Concern | Mixin approach | Capability set approach |
|---------|---------------|------------------------|
| Readability | `class Foo(FileWriteMixin, GraphReadMixin)` — class signature shows capabilities | Must read `capabilities` field |
| Composability | Inherit the mixin → get the capability | Add to set → get the capability |
| Capability inheritance | Automatic via MRO | Manual: must re-declare or compute superset |
| IDE support | Type checker sees the mixin → can generate docs | No static type relationship |
| Runtime cost | issubclass() check at definition-load time | frozenset lookup |
| Subclass granularity | Can constrain: `GraphWriteMixin(GraphReadMixin)` means writes implies reads | Separate entries in set; constraints must be enforced manually |
| Explicitness | Implicit in class hierarchy | Explicit in field |
| Field pollution risk | Low (marker mixins add no fields) | None |

**When mixins win:**
- Developer-facing definitions where readability of the class signature matters
- When you want IDE type checking to enforce capability constraints
- When inheritance hierarchy IS the capability hierarchy (subclass = superset)

**When capability sets win:**
- Runtime storage in the graph (a frozenset serializes easily; MRO does not)
- Self-authored definitions (the agent writes a JSON list of capabilities,
  not Python class definitions)
- When you need dynamic capability grant (runtime adds `GRAPH_WRITE` to a
  frozenset; you can't add a mixin to a class at runtime)

**The right answer:** Both. Mixins for developer-authored definitions
(they produce the capability set via MRO introspection). Capability frozenset
for the runtime `BootstrapAgent` (serializable, dynamic-grant-compatible).

### 1.4 Mixin design for context step composition

Mixins can go beyond just marking capabilities — they can contribute default
context steps:

```python
class SourceContextMixin(BaseModel):
    """Mixin: contributes source-reading context step."""
    _source_steps: ClassVar[tuple[Step, ...]] = (
        Step("source", ToolRef("read_file", {"path": "$node.file_path"})),
    )

class EventHistoryContextMixin(BaseModel):
    """Mixin: contributes event history context step."""
    _history_steps: ClassVar[tuple[Step, ...]] = (
        Step("history", ToolRef("read_recent_events", {"node_id": "$node.id"})),
    )

class GraphNeighborContextMixin(BaseModel):
    """Mixin: contributes graph neighbor context step."""
    _neighbor_steps: ClassVar[tuple[Step, ...]] = (
        Step("callers", ToolRef("graph_neighbors", {
            "node_id": "$node.id", "direction": "in",
        })),
    )
```

A base definition class collects them:

```python
class AgentDefinition(BaseModel):
    context_steps: tuple[Step, ...] = ()

    @classmethod
    def collect_mixin_steps(cls) -> tuple[Step, ...]:
        """Collect _*_steps from all mixins in MRO order."""
        all_steps = []
        seen = set()
        for klass in cls.__mro__:
            for attr in vars(klass):
                if attr.endswith("_steps") and attr.startswith("_") and attr not in seen:
                    seen.add(attr)
                    all_steps.extend(getattr(klass, attr, ()))
        return tuple(all_steps)

    def to_turn_schema(self) -> TurnSchema:
        combined_steps = self.collect_mixin_steps() + self.context_steps
        return TurnSchema(
            system=Concat(parts=("You are responsible for: ", ToolRef("read_file", {"path": "role.md"}))),
            context=ContextPipeline(steps=combined_steps),
            tools=self.tools,
            max_turns=self.max_turns,
            termination=self.termination,
        )
```

Now a definition that inherits `SourceContextMixin` and
`EventHistoryContextMixin` automatically gets both steps in its
`ContextPipeline` without manually listing them in `context_steps`.

**Risk:** This is magic. Developers have to know which mixins contribute
which steps. If a mixin's `_steps` attribute is misspelled, it silently
contributes nothing. This is the classic mixin debugging pain.

**Mitigation:** Each mixin's `__init_subclass__` could register itself,
and a `to_turn_schema()` debug method could print the resolved step list.
Or: keep context steps explicitly in `context_steps` and use mixins only
for capabilities. Simpler is more predictable.

---

## 2. Other Authoring Patterns

Beyond `AgentDefinition` with Pydantic inheritance and mixins, several
other patterns are worth considering.

### 2.1 Decorator-based authoring

```python
@agent(
    name="docstring_reviewer",
    capabilities={Capability.FILE_READ, Capability.FILE_WRITE, Capability.GRAPH_READ},
    subscribes=[SubscriptionPattern(event_type="ContentChangedEvent", tag="docstring_drift")],
)
def define_docstring_reviewer(node: GraphNode) -> TurnSchema:
    """Returns the TurnSchema for a docstring reviewer agent on node."""
    return TurnSchema(
        system=f"You review docstrings for {node.full_name}.",
        context=ContextPipeline(steps=(
            Step("source", ToolRef("read_file", {"path": node.file_path})),
        )),
        tools=("write_file", "emit_event"),
    )
```

The decorator registers the function in an `AgentRegistry`. When a
`NodeDiscoveredEvent` fires, the registry finds matching agents by node
pattern and calls the function to get the TurnSchema.

**Pros:**
- Very Pythonic. Familiar to anyone who has written Flask routes or Click CLI.
- The function signature makes it clear this is a definition-time callback.
- Easy to write unit tests: call `define_docstring_reviewer(mock_node)`.

**Cons:**
- Harder to inspect statically. The `capabilities` are in the decorator, not
  in the class — IDEs don't see them as type information.
- Hard to compose: you can't "inherit" from one decorated function to get
  another that extends it.
- Self-bootstrapping agents can't easily author decorated functions — they'd
  need to write Python code, not just data.

**Verdict:** Great for developer-authored agents where ergonomics matter.
Not suitable as the sole mechanism if agents are expected to author their
own definitions. Could coexist with `AgentDefinition`.

### 2.2 Builder / fluent API

```python
agent = (AgentBuilder("docstring_reviewer")
    .with_capabilities(FILE_READ, FILE_WRITE, GRAPH_READ)
    .with_context_step("source", read_file("$node.file_path"))
    .with_context_step("doc", extract_docstring(from_step="source"))
    .with_tool("write_file")
    .subscribes_to("ContentChangedEvent", tag="docstring_drift")
    .max_turns(5)
    .build())
```

**Pros:**
- Very readable. Each step is explicit.
- Easy to extend: `.with_context_step()` is composable without inheritance.
- Trivial for agents to write: just emit a JSON structure that maps to the
  builder calls.

**Cons:**
- Verbose. You can't "inherit" from a builder — you'd have to clone it
  and modify.
- The builder accumulates state — not immutable.
- Not a great IDE experience for discovering what's available.

**Verdict:** Excellent for programmatic assembly in agent self-bootstrapping
(emit a JSON instruction that the runtime interprets as builder calls). Less
great as the primary human-authoring interface.

### 2.3 YAML/TOML definition files

```yaml
# agents/docstring_reviewer.yaml
name: docstring_reviewer
role_description: "You maintain docstrings for $node.full_name."
capabilities:
  - file_read
  - file_write
  - graph_read
  - event_emit
context_steps:
  - name: source
    tool: read_file
    args: {path: "$node.file_path"}
  - name: current_doc
    tool: extract_docstring
    args: {path: "$node.file_path"}
tools:
  - write_file
  - emit_event
  - emit_schema
subscriptions:
  - event_type: ContentChangedEvent
    tag: docstring_drift
```

**Pros:**
- Non-Python authoring: agents can write YAML to their workspace, humans can
  too. The same serialization format works for both.
- Version-controllable, diffable.
- Schema validation via Pydantic: `AgentDefinition.model_validate(yaml.safe_load(f))`.

**Cons:**
- No composition mechanism — no inheritance, no mixins. Every definition is flat.
- Tooling: need a YAML schema file for IDE completion.
- Less expressive for complex context pipelines.

**Verdict:** The right serialization format for `schema.json` in cairn
workspaces — agents write JSON/YAML, the runtime parses it. Not the right
primary authoring format for developers (Pydantic classes are better for
humans; YAML is better for agents).

This points at a clean separation: **Developers author `AgentDefinition`
subclasses in Python. The runtime serializes them to JSON/YAML in cairn.
Agents read/write JSON/YAML. The runtime deserializes to `AgentDefinition`.**

### 2.4 Protocol-based structural typing

```python
class HasFileReadCapability(Protocol):
    """Agent can read files from cairn workspace."""
    node_id: str
    capabilities: frozenset[Capability]

    @property
    def can_read_files(self) -> bool:
        return Capability.FILE_READ in self.capabilities

class HasGraphWriteCapability(HasFileReadCapability, Protocol):
    """Agent can also mutate the graph."""
    @property
    def can_write_graph(self) -> bool:
        return Capability.GRAPH_WRITE in self.capabilities
```

These are not used for inheritance — they're used as type annotations for
functions that need a specific capability level:

```python
def emit_edge_for_relationship(
    agent: HasGraphWriteCapability,
    from_node: str,
    to_node: str,
    kind: str,
) -> None:
    """Only callable with an agent that has graph-write capability."""
    ...
```

**Pros:**
- Zero runtime cost. No class hierarchy in `BootstrapAgent`.
- Type checker enforces capability requirements at call sites.
- Structural typing means any class with the right attributes qualifies.

**Cons:**
- Doesn't help with determining WHICH externals to include — that's still
  done via the `frozenset[Capability]` at runtime.
- Adds Protocol classes that don't directly affect behavior.

**Verdict:** Useful as a type-checking layer on top of the capability system.
Not a replacement for the capability enum/frozenset. Could be generated
automatically from the `Capability` enum.

### 2.5 Dataclass-based definitions

```python
@dataclass(frozen=True)
class DocstringReviewerDef:
    name: str = "docstring_reviewer"
    capabilities: frozenset[Capability] = frozenset({
        Capability.FILE_READ, Capability.FILE_WRITE, Capability.GRAPH_READ,
    })
    context_steps: tuple[Step, ...] = (
        Step("source", ToolRef("read_file", {"path": "$node.file_path"})),
    )
    tools: tuple[str, ...] = ("write_file",)
```

**Pros:**
- `slots=True, frozen=True` → fast, immutable, hashable.
- No Pydantic dependency for the definition itself.
- Simple to introspect.

**Cons:**
- No automatic validation (Pydantic's strong suit).
- No inheritance field merging (dataclasses don't merge fields from parent).
- Can't serialize to/from JSON without extra work.

**Verdict:** Less ergonomic than Pydantic for this use case. Pydantic wins.

---

## 3. Developer Ergonomics: Making the Swarm Legible

The swarm builds itself. But developers need to understand what it's doing.
The agent model's flat `BootstrapAgent` structure is designed for legibility —
the whole swarm is queryable via the graph + event bus. Here's what the
developer interaction patterns look like.

### 3.1 Graph-based inspection

Because every agent IS a graph node, all of the `graph_*` externals serve
double duty as developer inspection tools. The same API agents use to
understand each other, developers use to understand the swarm:

```python
# Who are all the agents?
graph_find_nodes(kind="agent.profile")

# What is this agent's current state?
graph_node(node_id="agent:docstring_reviewer_abc123")
# → {node_id: ..., capabilities: [...], status: "running", ...}

# What does this agent know about its neighbors?
graph_neighbors(node_id="...", direction="all")

# Who are the agents working on this file?
graph_find_nodes(kind="agent.profile", attrs={"file_path": "src/remora/core/events/events.py"})
```

### 3.2 Schema inspection

An agent's TurnSchema is stored as `schema.json` in its cairn workspace.
Developers can read it directly:

```
.remora/<swarm_id>/agents/<agent_id>/workspace.db → schema.json
```

The schema is JSON, readable by humans. It shows exactly what context pipeline
runs, what tools the agent has, and what system prompt it uses. No opaque
bytecode, no compiled artifacts — just data.

### 3.3 Event stream observation

The `EventStore` (v1, unchanged) logs every event. A developer can tail
the event stream for a specific agent or correlation:

```python
read_recent_events(node_id="agent:docstring_reviewer", limit=50)
# → list of events with causal_parent_id chains
```

This shows:
- What event triggered the agent
- What events the agent emitted in response
- The causal chain depth (to detect runaway recursion early)
- What the agent reported via `submit_result`

### 3.4 The agent catalog: developer-authored definitions as a registry

Developer-authored `AgentDefinition` subclasses live in Python files that
the runtime discovers (same pattern as v1's extension configs):

```
bootstrap/agents/
    __init__.py
    code/
        docstring_reviewer.py   ← DocstringReviewerDefinition
        signature_watcher.py    ← SignatureWatcherDefinition
    meta/
        maintainer.py           ← MaintainerDefinition
```

The runtime discovers these at startup via importlib — the same
`discover_grail_tools()` pattern, but for definition classes. It builds
an `AgentCatalog`:

```python
class AgentCatalog:
    """Registry of developer-authored AgentDefinitions."""

    def register(self, defn_class: type[AgentDefinition]) -> None: ...
    def find_by_node(self, node: GraphNode) -> list[AgentDefinition]: ...
    def all_definitions(self) -> list[AgentDefinition]: ...

    def summary(self) -> str:
        """Human-readable catalog for developers."""
        ...
```

A `remora agents list` CLI command prints the catalog: what definitions are
registered, what capabilities each has, what nodes each matches.

### 3.5 Hot-reload for developer-authored definitions

Developer-authored definition files can be hot-reloaded during development.
The runtime watches `.py` files in `bootstrap/agents/` with mtime-based
caching (same pattern as v1 extension configs). When a file changes:

1. Re-import the module
2. Update the `AgentCatalog` with the new definition classes
3. Mark all agents based on the changed definition as `needs_schema_refresh`
4. On next activation, they get a fresh TurnSchema from `to_turn_schema()`

This means a developer can edit a definition file, save, and the swarm
updates without restart. The cairn workspace `schema.json` for affected
agents is regenerated on their next activation.

### 3.6 What the developer sees vs. what the agent sees

This is an important ergonomic point:

| What the developer sees | What the agent sees |
|------------------------|---------------------|
| `AgentDefinition` subclass in a Python file | `schema.json` in cairn workspace |
| `capabilities=` field or mixin inheritance chain | externals dict passed at runtime |
| `subscriptions=` on the definition | SubscriptionRegistry entries |
| `AgentCatalog.summary()` | `graph_find_nodes(kind="agent.profile")` |
| Event log in SQLite (direct query) | `read_recent_events()` external |

Same information, two interfaces. The Python authoring layer and the
graph/cairn substrate layer are two views of the same state. This is the
legibility invariant: nothing the agent knows about itself is hidden from
the developer.

---

## 4. Emergent Composition: Schema Diffusion as Inheritance

The Primitives Walkthrough (Appendix II) describes Schema Diffusion: an agent
can copy a useful context step from a neighbor's schema and add it to its own.
This is emergent inheritance — agents building on each other's schemas without
a formal class hierarchy.

### 4.1 The mechanism

Schema diffusion works through events:

1. Agent A has a useful context step (`score_docstring_alignment`)
2. Agent A emits a `SchemaStepEvent` with the step serialized
3. Agent B subscribes to `SchemaStepEvent` for nodes in the same scope
4. Agent B calls `emit_schema` adding the step to its own TurnSchema

The step propagates from A to B to C... The useful pattern spreads without
central coordination. No developer needs to update any class definition.

### 4.2 Why this is the right kind of inheritance

Static inheritance (class hierarchy) is decided at authoring time. Emergent
composition (schema diffusion) is decided at runtime by the agents themselves.

- **Static inheritance:** Developer decides that `SignatureWatcher` gets
  the `CallerContextStep` because it makes sense for the domain. Correct
  decision for the pattern as understood at authoring time.

- **Schema diffusion:** Agent A discovers empirically that the
  `CallerContextStep` helps it produce better outputs. It shares the step
  via an event. Agent B sees the step being useful in similar situations
  and adopts it. The step becomes common in the agent population because
  it's useful — not because a developer pre-decided it.

This is Darwinian inheritance: survival of the useful step.

### 4.3 Controlling diffusion

Uncontrolled diffusion could cause chaos — a bad step spreading across the
whole swarm. Controls:

1. **Capability gate:** Only agents with `SCHEMA_EVOLVE` can call `emit_schema`.
   Only agents with `EVENT_EMIT` can emit `SchemaStepEvent`. These are
   capabilities that must be earned.

2. **Adoption validation:** When an agent receives a `SchemaStepEvent` and
   considers adopting the step, the runtime validates that the step's `ToolRef`
   refers to an external the agent actually has. Can't adopt a step that uses
   `graph_add_edge` if you don't have `GRAPH_WRITE`.

3. **Maintainer oversight:** `SchemaStepEvent` can be routed through the
   maintainer agent before adoption. The maintainer sees what's spreading and
   can revoke a step by emitting a `RevokeSchemaStepEvent`.

4. **Lineage tracking:** Every adopted step records `adopted_from: agent_id`
   in its metadata. If a bad step spreads, you can trace it back to the source.

### 4.4 The genome metaphor

Each agent's `TurnSchema` is its "genome" — the complete specification of its
behavior. The `ContextPipeline` steps are genes. The tools list is a gene. The
system prompt is a gene.

Schema diffusion is horizontal gene transfer: agents exchanging genetic
material laterally, not just inheriting from parents. A successful strategy
(a useful context step) spreads through the population.

Static `AgentDefinition` inheritance is vertical descent: child definitions
inherit from parent definitions at authoring time. This is the class hierarchy.

Both mechanisms coexist. Neither replaces the other:
- Static inheritance: **designed** capability composition (developers know
  what they want before running)
- Schema diffusion: **discovered** capability composition (the swarm finds
  what works by running)

---

## 5. The Developer Interaction Surface

A live swarm needs a developer to be able to do six things:

### 5.1 Inspect

Read the current state of any agent, any event, any graph node.

Mechanisms:
- `graph_node(node_id)` — get a specific agent's state
- `graph_find_nodes(kind="agent.profile", attrs={...})` — search agents
- `read_recent_events(node_id)` — event history for an agent
- `cairn_workspace_read(agent_id, "schema.json")` — read stored TurnSchema
- CLI: `remora inspect agent <node_id>` (wraps the above)
- CLI: `remora inspect events <node_id> --limit 50`

### 5.2 Inject

Add a new agent definition to a running swarm, or create a new agent for a
specific node.

Mechanisms:
- Write a new `AgentDefinition` class → runtime hot-reloads catalog → on
  next `NodeDiscoveredEvent` matching that definition, the agent gets it
- Manually emit `NodeDiscoveredEvent` with a specific node_id → triggers
  agent creation/reactivation
- `remora inject agent <node_id> --definition DocstringReviewer`

### 5.3 Pause and Resume

Pause a specific agent or the whole swarm for inspection or correction.

Mechanisms:
- Set agent status to "paused" in graph → runtime checks before activation
- `remora pause agent <node_id>`
- `remora pause swarm` (sets a system-wide pause flag)
- Resume: `remora resume agent <node_id>`

### 5.4 Correct

Modify a misbehaving agent's state without full restart.

Mechanisms:
- Write directly to the agent's cairn workspace: override `role.md` or
  `schema.json` with corrected content
- `remora edit schema <node_id>` → opens `schema.json` in $EDITOR
- Emit `CapabilityRevokedEvent` to reduce an agent's capabilities
- Emit `SchemaResetEvent` → runtime resets agent to DEFAULT_SCHEMA on
  next activation

### 5.5 Observe Live

Watch what the swarm is doing in real time.

Mechanisms:
- `remora tail events` → streams the event bus output
- `remora watch agent <node_id>` → streams events for a specific agent
- `remora swarm status` → summary of all agent statuses (idle/running/error)
- LSP integration: if Neovim LSP is connected, agent status appears as
  code lens annotations on the function/class the agent is responsible for

### 5.6 Understand the Emerged Structure

After the swarm has been running, a developer wants to know what structure
accumulated in the graph — what node kinds, edge kinds, and relationships the
agents created.

Mechanisms:
- `graph_find_nodes(kind="*")` → all unique node kinds in the graph
- `remora graph summary` → histogram of node kinds + edge kinds
- `remora graph explore` → interactive TUI for walking the graph
- Export: `remora graph export --format graphml` → for visualization in
  external tools (Gephi, yEd, etc.)

---

## 6. Synthesis: Recommended Authoring Stack

Taking everything above, the recommended authoring stack is:

### For developer-authored definitions

**Primary:** `AgentDefinition` subclasses with Pydantic inheritance.
The class hierarchy is the composition mechanism. Developers write Python
classes that extend a base definition.

**Secondary:** Mixin classes for capability composition within the
`AgentDefinition` hierarchy. Pure marker mixins (no fields, no validators)
avoid all the diamond problems while enabling the `capabilities_from_definition()`
runtime introspection.

```
AgentDefinition (base)
    ├── BaseCodeAgentDefinition (adds: FileWriteMixin, GraphReadMixin, EventEmitMixin)
    │       ├── DocstringReviewerDefinition
    │       ├── SignatureWatcherDefinition
    │       └── TestCoverageDefinition
    ├── MetaAgentDefinition (adds: PrivilegedMixin, GraphWriteMixin)
    │       └── MaintainerDefinition
    └── InfraAgentDefinition (adds: ToolSynthesizeMixin)
            └── ToolBuilderDefinition
```

**For inspection:** Protocol structural types auto-generated from the
Capability enum. Used by type checkers only; no runtime cost.

### For agent self-authored definitions

**Serialization format:** JSON (same as `schema.json`). The `AgentDefinition`
model can serialize/deserialize to JSON. Agents write a JSON structure that
conforms to `AgentDefinition`'s schema.

**Conversion path:** JSON → `AgentDefinition.model_validate(...)` →
`to_turn_schema()` → stored as `schema.json`.

Agents don't write Python class definitions — they write data. The runtime
interprets data as definitions.

### For the v3 concept document

What the v3 document should specify:
1. `BootstrapAgent` as the runtime model (in §6 — already added)
2. `Capability` enum as the access control mechanism (in §6 — already added)
3. `AgentDefinition` as the authoring model with Pydantic inheritance (in §6)
4. Mixin capability classes as the capability composition pattern (in §6)
5. Developer visibility patterns (query, inspect, tail, correct) — in §6.5

What NOT to specify:
- Concrete `AgentDefinition` subclasses beyond the base
- Specific mixin compositions used in production
- What the mixin hierarchy looks like beyond the capability mapping
- What "the catalog" ends up containing

The developer ergonomics (inspect, inject, pause, correct, observe, understand)
should be mentioned in the concept document as first-class requirements —
the agent model is designed for legibility, and the delivery plan should
include at minimum a `remora inspect` CLI command by M5.
