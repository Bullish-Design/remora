# Phase 2 Bootstrap v2: Semantic Swarm Architecture

> An alternative concept for the Remora Phase 2 bootstrap, building on v1's foundations
> but pushing further on graph semantics, turn contracts, testability, and self-reflection.

---

## Table of Contents

1. Core Premise
2. What Changes from v1
3. Design Principles
4. Semantic Graph Topology
5. Composable Turn Contracts
6. The Causal Event Bus
7. Swarm Protocols (Typed State Machines)
8. Structured Tool Contracts
9. Memory as a Graph Layer
10. Substrate Reflection
11. Developer Inner Loop
12. Incremental Delivery Plan
13. Risks and Mitigations
14. How This Diverges from v1

---

## 1. Core Premise

v1 states the goal as: "bootstrap a new core that treats remora as a library and builds an explicit
graph/swarm runtime from first principles."

v2 accepts this goal but sharpens it: the bootstrap doesn't just build a *cleaner* runtime — it builds
a runtime that can **inspect and evolve itself**. The swarm is the author of the next version of the swarm.

This means:
- The graph represents not just code structure, but semantic relationships (requirement → implementation
  → test → violation).
- Every agent turn is a typed contract with explicit failure modes, not a freeform LLM call.
- Swarm behavior is defined by composable protocols (typed state machines), not by emergent routing alone.
- The swarm has tools to read and modify its own graph — subscriptions, protocols, agent definitions.

The "bootstrap" in Phase 2 bootstrap is literal: the swarm participates in bootstrapping itself.

---

## 2. What Changes from v1

| Concern | v1 Approach | v2 Approach |
|---------|-------------|-------------|
| Graph model | Code topology | Semantic topology (intent + structure + test) |
| Agent activation | Subscription pattern matching | Protocol state transitions + pattern matching |
| Turn execution | Capability-gated freeform LLM | Typed TurnContract with structured output requirement |
| Tool definition | `.pym` Grail scripts (legacy) / BootstrapTool (new) | Pure Python classes with typed I/O + mock impl |
| Failure handling | Emit typed failure classification | Fail-first contracts + typed failure routing |
| Memory | Per-agent blob + durable event links | Memory as graph nodes + edges (queryable, shared) |
| Self-modification | Not addressed | Explicit substrate reflection capability |
| Testing | Not addressed | Synthetic harness built alongside runtime |
| Emergence | Local rules → global behavior | Protocol bounds + local rules → bounded global behavior |

---

## 3. Design Principles

### P1: Semantic graph over syntactic graph

Code constructs (functions, classes) are entry points into the semantic graph, not the whole of it.
The graph represents *meaning*: what a function is supposed to do, what tests it, what requirement it
satisfies, what invariants it upholds. Code is a projection of semantics, not the reverse.

### P2: Contracts before code

Every agent turn, every tool call, every protocol state transition is specified by a typed contract
before any implementation runs. The contract is the unit of test, the unit of failure, the unit of
documentation. Code that satisfies the contract is correct code.

### P3: Failure is first-class

The system is designed around the assumption that agents will fail. Every failure has a typed reason.
Every typed reason has a routing policy. "Generic LLM error" is not an acceptable failure mode —
it means the contract was underspecified.

### P4: Causal provenance is mandatory

Every event carries its causal parent. Every graph node carries its originating event. Every agent
turn carries the event that triggered it. You can always answer: why does this exist? What caused it?
What would be undone if we reverted it?

### P5: Testable without a live LLM

The entire swarm, including multi-agent cascades, should be runnable in a synthetic mode where
LLM calls are replaced by mock tool responses. This is not a testing convenience — it is an
architectural requirement. If you can't test it without a live LLM, you can't debug it either.

### P6: The swarm knows about itself

Agents have read access to the graph that describes them: their subscriptions, their capabilities,
their recent causal history. Selected privileged agents have write access. This is how the swarm evolves
without external configuration changes.

### P7: Protocols bound emergence

Emergence is not "anything can happen." Emergence is constrained by registered protocols with explicit
state machines. Every causal chain belongs to one or more active protocols. Chains that don't match any
protocol are quarantined for inspection, not silently dropped.

---

## 4. Semantic Graph Topology

### 4.1 Node kinds

The graph contains nodes of distinct semantic kinds, not just code constructs:

```
code.function         A callable unit of code
code.class            A type definition
code.file             A source file
code.module           A Python module
spec.requirement      A stated capability requirement ("the system shall...")
spec.invariant        A property that must always hold ("sum is never negative")
spec.contract         An explicit pre/post condition pair
test.assertion        A single test assertion tied to a spec or code node
test.case             A test function containing assertions
doc.section           A documentation section
doc.example           A code example in documentation
agent.profile         A registered bootstrap agent
agent.protocol        A registered swarm protocol definition
memory.episode        A recorded interaction episode (short-horizon)
memory.insight        A distilled durable memory (long-horizon)
```

### 4.2 Edge kinds and semantics

Edges carry semantics. An edge is not just "node A relates to node B" — it carries a typed relation
with a defined meaning and activation policy:

| Edge kind | From | To | Semantics | Activation |
|-----------|------|----|-----------|------------|
| `implements` | code.* | spec.requirement | this code satisfies this requirement | review when code changes |
| `tests` | test.* | code.* | this test exercises this code | run when code changes |
| `asserts` | test.assertion | spec.invariant | this assertion checks this invariant | index for violation detection |
| `documents` | doc.section | code.* | this doc describes this code | update when code changes |
| `violates` | code.* | spec.invariant | this code violates this invariant (detected) | immediately activates violation protocol |
| `proposes_change_to` | agent.profile | code.* | agent has an open proposal against this code | activates review protocol |
| `coordinates` | agent.profile | agent.profile | first agent delegates to second | routing hint for orchestrator |
| `caused_by` | any | event | this node exists because of this event | causal provenance |
| `remembers` | memory.episode | any | this episode involves this node | memory recall |
| `specializes` | agent.profile | agent.profile | first agent is a specialization of second | capability inheritance |

### 4.3 Graph as activation fabric

Edges replace hardcoded subscription patterns as the primary routing mechanism.

When an agent creates a `violates` edge, the violation protocol activates automatically — because
violation-watcher agents are subscribed to `EdgeCreatedEvent(edge_kind="violates")`. When a `tests`
edge disappears (because a test was deleted), a coverage-gap protocol activates.

The graph IS the subscription system. You configure agent behavior by editing the graph, not by
editing config files.

### 4.4 Node identity

Every node has a deterministic ID derived from its semantic signature:

```python
node_id = stable_hash(kind, canonical_name, anchor)
```

Where `anchor` is the closest stable parent for code nodes (file path + qualified name), or a
human-assigned slug for spec/doc/agent nodes. This is consistent with Remora's existing `CSTNode`
identity model and can coexist with it.

Phase 2 graph nodes are not the same as legacy `AgentNode` rows. They live in a separate storage
namespace. Bi-directional mapping entries (mapping legacy node_id → Phase 2 node_id) can be added
as a migration bridge but are not required at bootstrap start.

---

## 5. Composable Turn Contracts

The core failure mode of current Remora (and most LLM agent systems) is that an agent turn is
"try to get the LLM to produce useful output, hope it uses tools." v2 replaces this with
**TurnContracts** — explicit specifications of what a turn requires and what it produces.

### 5.1 TurnContract anatomy

```python
@dataclass(frozen=True)
class TurnContract:
    name: str
    # What capabilities must be available for this turn to run
    requires: tuple[CapabilityRef, ...]
    # What event types this turn is expected to emit (at least one)
    produces: tuple[type[BootstrapEvent], ...]
    # What the LLM is allowed to call (subset of registered tools)
    allowed_tools: tuple[str, ...]
    # Maximum token budget for this turn
    budget: TokenBudget
    # What to do if the turn fails
    on_failure: FailurePolicy
    # If set, this turn is safe to retry if idempotency_key matches a recent turn
    idempotency_key: str | None = None
```

### 5.2 Failure classification

Every turn completes with one of these outcomes:

| Outcome | Meaning | Routing |
|---------|---------|---------|
| `SUCCESS` | At least one `produces` event emitted | Continue protocol |
| `PARSE_FAILURE` | LLM response didn't produce structured output | Retry with parse-focused prompt, then escalate |
| `SCHEMA_MISMATCH` | Tool call arguments didn't match tool schema | Emit diagnostics, retry once |
| `POLICY_DENIAL` | Agent attempted a capability not in `allowed_tools` | Hard fail, log violation |
| `BUDGET_EXCEEDED` | Token or turn budget exhausted | Terminate, emit partial result |
| `CAPABILITY_MISSING` | A required capability is not registered | Hard fail immediately, config error |
| `TIMEOUT` | Turn exceeded wall-clock limit | Terminate, emit diagnostic |
| `RUNTIME_ERROR` | Unhandled exception in tool handler | Emit error event, apply failure policy |

This replaces "no tool calls" ambiguity with a taxonomy that can be routed, logged, and acted on.

### 5.3 Structured output requirement

Every agent in the bootstrap runtime is given a system prompt that includes the active TurnContract.
The contract specifies exactly what output format is required. If the model produces unstructured text,
the executor classifies it as `PARSE_FAILURE` before the response is used for anything.

The executor does not retry indefinitely. It applies the `on_failure` policy from the contract:
- `Retry(max=2)` — retry up to two times with a parse-focused reprompt
- `Escalate(to_protocol="human_review")` — route to human-in-the-loop protocol
- `Abandon` — emit `TurnFailedEvent` and terminate the protocol leg

---

## 6. The Causal Event Bus

### 6.1 Event envelope

Every event in the bootstrap runtime carries a causal envelope:

```python
@dataclass(frozen=True)
class BootstrapEvent:
    event_id: str              # UUID
    event_type: str            # discriminator
    correlation_id: str        # top-level user request or workflow ID
    causal_parent_id: str | None  # event that triggered this one (None for root events)
    depth: int                 # causal depth from root (0 for root events)
    agent_id: str | None       # agent that emitted this event (None for system events)
    timestamp: float           # unix timestamp
    payload: dict              # event-specific data
```

### 6.2 Causal graph

Every event's `causal_parent_id` forms a forest of causal trees. This forest is a first-class data
structure, queryable via the graph substrate:

```python
# What did event X cause?
graph.causal_descendants(event_id="abc-123")

# What caused this node to exist?
graph.causal_ancestors(node_id="fn:my_module.my_function")

# What would be undone by reverting event X?
graph.causal_scope(event_id="abc-123")
```

Causal scope is the basis for **undo semantics**: reverting an event means emitting compensating
events for everything in its causal scope.

### 6.3 Depth and budget tracking

Depth is tracked per-event, not per-agent. A depth limit is a constraint on causal chains, not on
individual agents. This matters: an agent that emits 10 events all at depth 3 is fine; an agent that
causes a chain of events reaching depth 15 is not.

Budget tracking is per-correlation: total token spend, total wall-clock time, and total turn count
are tracked across all events in a correlation chain. The Emergence Engine enforces budgets at the
correlation level.

---

## 7. Swarm Protocols (Typed State Machines)

### 7.1 The problem with pure emergence

Pure emergence ("local rules → global behavior") is correct as a principle but fragile as an
implementation. Without explicit state machines, the swarm has no concept of "progress." Two agents
can coordinate forever, each waiting for the other to do something, with no mechanism to detect the
deadlock.

v2 introduces **SwarmProtocols**: explicit state machines that bound and structure swarm behavior.

### 7.2 Protocol anatomy

```python
@dataclass(frozen=True)
class SwarmProtocol:
    name: str
    # Event pattern that starts this protocol
    trigger: EventPattern
    # Ordered list of states in this protocol
    states: tuple[ProtocolState, ...]
    # Protocol-level guard conditions
    guards: ProtocolGuards
```

```python
@dataclass(frozen=True)
class ProtocolState:
    name: str
    # Which agent handles this state (may be a role, not a specific agent)
    agent_role: str
    # Which TurnContract is used for this state
    turn_contract: TurnContract
    # Where to go on success (state name)
    on_success: str
    # Where to go on failure (state name, or "terminate")
    on_failure: str

@dataclass(frozen=True)
class ProtocolGuards:
    max_depth: int         # causal chain depth limit
    max_loops: int         # times the same state can be revisited
    timeout_seconds: float # wall-clock limit for the whole protocol
    require_progress: bool # each loop must advance the state
```

### 7.3 Initial protocol set

**DirectTask**: user intent → result
```
start:          UserIntentEvent
states:
  intaking:     orchestrator / TaskIntake contract → planning | failed
  planning:     orchestrator / PlanDecompose contract → executing | human_review
  executing:    editor / ImplementPlan contract → reviewing | failed
  reviewing:    reviewer / ReviewOutput contract → done | executing (max_loops=2)
  done:         [terminal]
  human_review: [terminal, escalate]
  failed:       [terminal, emit diagnostic]
guards:
  max_depth: 10, max_loops: 2, timeout: 300s
```

**ViolationResponse**: detected invariant violation → fix
```
start:          EdgeCreatedEvent(edge_kind="violates")
states:
  triaging:     reviewer / ViolationTriage contract → patching | dismissed
  patching:     editor / ProposePatch contract → verifying | failed
  verifying:    reviewer / VerifyPatch contract → applying | patching (max_loops=2)
  applying:     maintainer / ApplyPatch contract → done | failed
  dismissed:    [terminal]
  done:         [terminal]
  failed:       [terminal, emit diagnostic]
guards:
  max_depth: 8, max_loops: 2, timeout: 120s
```

**CoverageGap**: missing test coverage detected → new test proposed
```
start:          EdgeRemovedEvent(edge_kind="tests") | NodeDiscoveredEvent(uncovered=True)
states:
  assessing:    reviewer / AssessCoverage contract → generating | dismissed
  generating:   editor / GenerateTest contract → reviewing | failed
  reviewing:    reviewer / ReviewTest contract → done | generating (max_loops=2)
  done:         [terminal]
```

### 7.4 Protocols and emergence

Emergence still happens — at the protocol level. When code changes, which protocols activate?
The graph determines this: a code change that touches a node with `implements` edges activates
ViolationResponse (to check invariants). A code change on a node with `tests` edges may activate
CoverageGap. The protocols are deterministic; which ones fire is emergent.

---

## 8. Structured Tool Contracts

### 8.1 The .pym problem

Current Remora tools are Grail `.pym` scripts: custom-syntax files that define tool parameters
and a Python handler. This makes tools hard to type-check, hard to mock, and hard to compose.

v2 replaces `.pym` tools with pure Python classes:

```python
class BaseTool:
    class Input(BaseModel): ...
    class Output(BaseModel): ...
    side_effects: SideEffect = SideEffect.NONE  # NONE | READ | READ_WRITE | EXTERNAL
    idempotent: bool = True

    async def execute(self, input: Input) -> Output: ...
    async def mock_execute(self, input: Input) -> Output: ...
    # mock_execute() is the default synthetic implementation for testing
```

### 8.2 Initial tool set (v2)

**InspectNode** (side_effects=READ, idempotent=True)
- Input: `node_id: str`, `include_neighbors: bool`, `neighbor_kinds: list[str]`
- Output: `node: GraphNode`, `neighbors: list[GraphEdge]`, `causal_origin: BootstrapEvent | None`
- Purpose: graph introspection for agent local reasoning

**QueryGraph** (side_effects=READ, idempotent=True)
- Input: `edge_kind: str`, `from_kind: str | None`, `to_kind: str | None`, `limit: int`
- Output: `edges: list[GraphEdge]`, `total: int`
- Purpose: semantic neighborhood queries ("what does this require implement?")

**EmitEvent** (side_effects=READ_WRITE, idempotent=False)
- Input: `event_type: str`, `payload: dict`, `target_node_id: str | None`
- Output: `event_id: str`, `depth: int`
- Purpose: controlled swarm testing; agents triggering protocol transitions explicitly

**ProposePatch** (side_effects=READ_WRITE, idempotent=False)
- Input: `target_node_id: str`, `patch_content: str`, `rationale: str`, `confidence: float`
- Output: `proposal_id: str`, `proposal_event_id: str`
- Purpose: structured code change proposal (does not apply; creates `proposes_change_to` edge)

**Echo** (side_effects=NONE, idempotent=True)
- Input: `payload: dict`
- Output: `echo: dict`, `depth: int`, `correlation_id: str`
- Purpose: round-trip diagnostics and plumbing validation

**UpdateSubscription** (side_effects=READ_WRITE, idempotent=True) — privileged
- Input: `agent_id: str`, `add_patterns: list[dict]`, `remove_patterns: list[dict]`
- Output: `active_patterns: list[dict]`
- Purpose: substrate reflection — agents updating their own event subscriptions

**RegisterProtocol** (side_effects=READ_WRITE, idempotent=True) — privileged
- Input: `protocol_definition: dict`
- Output: `protocol_id: str`, `active: bool`
- Purpose: substrate reflection — agents registering new swarm protocols

### 8.3 Side effect policy and capability gating

The `side_effects` classification feeds directly into the TurnContract `allowed_tools` policy:
- Agents with `read-only` role can only call `SideEffect.READ` or `NONE` tools
- Agents with `proposal` role can call `READ_WRITE` tools but only `ProposePatch` (not `ApplyPatch`)
- Privileged agents (maintainer) can call the substrate reflection tools

This is the capability policy language: it's the tool's declared `side_effects` + the agent role's
allowed side-effect level. No custom DSL required for Phase 2.

---

## 9. Memory as a Graph Layer

### 9.1 Memory is not a blob

Agents need context about what happened before. Current approaches (pass recent events in context,
maintain per-agent blobs) are fragile: context windows fill up, blobs diverge, agents forget shared
history.

v2 makes memory part of the graph. Memory is not a separate system — it is a set of node kinds and
edge kinds in the semantic graph.

### 9.2 Memory node kinds

**`memory.episode`** — a recorded interaction (short-horizon, ephemeral)
- Fields: correlation_id, summary, participating_agents, outcome, timestamp, ttl_seconds
- Edges: `remembers` to every node that was involved in the interaction
- Eviction: episodes older than `ttl_seconds` are archived (causal links preserved, content deleted)

**`memory.insight`** — a distilled durable observation (long-horizon, persistent)
- Fields: content, confidence, source_episodes (list of episode IDs), created_at, last_reinforced_at
- Edges: `concerns` to relevant code/spec/agent nodes
- Created by: maintainer agent when patterns emerge across multiple episodes
- Eviction: only via explicit `ClearInsightEvent` or confidence decay below threshold

### 9.3 Memory recall

An agent that needs context about a node queries the graph:

```python
# What do we know about this function?
episodes = graph.query(
    edge_kind="remembers",
    to_node=node_id,
    node_kind="memory.episode",
    limit=5,
    order="recency"
)

# What durable insights concern this module?
insights = graph.query(
    edge_kind="concerns",
    to_node=module_id,
    node_kind="memory.insight",
    min_confidence=0.7
)
```

This returns structured memory that the agent can include in its context window in a controlled way
(not dumping raw event logs). The maintainer agent is responsible for distilling episodes into
insights and managing insight quality.

### 9.4 Cross-agent memory sharing

Memory is in the graph, so it is queryable by any agent with read access. An orchestrator can check
whether a similar task was attempted before. A reviewer can recall whether a specific node was found
problematic in prior interactions. Memory is a shared resource, not a per-agent silo.

---

## 10. Substrate Reflection

### 10.1 The meta-loop

The most distinctive idea in v2: the swarm can modify itself through its own tool system.

Specifically:
- **bootstrap_maintainer** has access to `UpdateSubscription` and `RegisterProtocol` tools
- **bootstrap_orchestrator** can propose new `agent.protocol` nodes via `ProposePatch`
- **bootstrap_reviewer** reviews proposed protocol changes before they are applied

This means the swarm can:
1. Notice that a recurring task pattern isn't covered by any protocol
2. Propose a new protocol definition as a graph node
3. Have the reviewer check it for soundness (depth bounds, required capabilities, state completeness)
4. Apply it, making it active for future triggering

This is the concrete form of "bootstrap-native: using Remora to build a better Remora."

### 10.2 Safety constraints

Substrate reflection is bounded:

- Only the `maintainer` role can write `agent.protocol` nodes and call `RegisterProtocol`
- Protocol proposals go through the same `ViolationResponse`-style review before activation
- Newly registered protocols are marked `trial` for the first N activations; failures during trial
  disable the protocol and emit a `TrialProtocolFailedEvent`
- No agent can modify another agent's subscriptions directly; they can only propose changes via
  `ProposePatch` on the agent's node

### 10.3 What the meta-loop enables

Without substrate reflection, every new agent capability requires a human to edit config and
redeploy. With it:

- The swarm can learn that "when node X changes, also check node Y" and add that subscription
- The swarm can notice that a protocol's `max_loops` is too low (constant failure at limit) and propose
  an adjustment
- The swarm can register domain-specific protocols for a new codebase it's working on, adapting itself
  to the project's structure

---

## 11. Developer Inner Loop

The concept is only as good as the developer experience for building on it.

### 11.1 Running a single turn

```bash
# Run one turn against the bootstrap runtime (synthetic mode, no LLM)
remora-bootstrap run --synthetic --turn DirectTask --input '{"objective": "explain module X"}'

# Run with a live LLM (requires model server)
remora-bootstrap run --turn DirectTask --input '{"objective": "explain module X"}'
```

Output (structured):
```
[TURN] DirectTask / intaking
  contract: TaskIntake (requires: InspectNode, QueryGraph)
  agent: bootstrap_orchestrator
  ...
[EVENT] TurnCompleteEvent(outcome=SUCCESS, produced=[TaskPlannedEvent])
[STATE] → planning

[TURN] DirectTask / planning
  ...
[EVENT] TurnCompleteEvent(outcome=PARSE_FAILURE, failure_reason=structured_output_missing)
[RETRY] 1/2 with parse-focused reprompt
[EVENT] TurnCompleteEvent(outcome=SUCCESS, produced=[PlanDecomposedEvent])
[STATE] → executing
```

Every failure is visible, classified, and shows exactly what was retried.

### 11.2 Synthetic test harness

Tests that involve multi-agent cascades should not require a live LLM. The synthetic harness
replaces all `BaseTool.execute()` calls with `BaseTool.mock_execute()` calls, and replaces LLM
calls with deterministic scripted responses:

```python
def test_direct_task_protocol_happy_path():
    harness = SyntheticHarness()
    harness.script_agent_response(
        agent="bootstrap_orchestrator",
        state="intaking",
        tool_calls=[InspectNode.Input(node_id="fn:my_module.my_fn")]
    )
    harness.script_agent_response(
        agent="bootstrap_orchestrator",
        state="planning",
        produces=[PlanDecomposedEvent(steps=[...])]
    )
    # ... etc.

    result = harness.run_protocol("DirectTask", input=UserIntentEvent(...))
    assert result.final_state == "done"
    assert result.events_emitted_by_type(PlanDecomposedEvent) == 1
```

No LLM, no network, fully deterministic, fast.

### 11.3 Graph inspector

```bash
# Show graph state as of now
remora-bootstrap graph --show

# Show causal descendants of an event
remora-bootstrap graph --causal-descendants event-id-abc123

# Show active protocols and their current state
remora-bootstrap protocols --active

# Show recent episodes in memory
remora-bootstrap memory --episodes --limit 5
```

### 11.4 Replay

```bash
# Replay a specific correlation chain from the event log
remora-bootstrap replay --correlation-id abc-123

# Replay up to a specific event (for debugging)
remora-bootstrap replay --correlation-id abc-123 --until event-id-xyz
```

Replay runs the same events through the runtime, re-executing tool calls with the same inputs.
This makes it possible to reproduce bugs deterministically.

---

## 12. Incremental Delivery Plan

Each milestone is independently shippable and testable without the next milestone.

### M0: Foundational Types (2-3 days)

Deliverables:
- `GraphNode`, `GraphEdge` dataclasses with all planned kinds and edge kinds
- `BootstrapEvent` envelope with causal fields
- `TurnContract`, `FailureOutcome`, `FailurePolicy` types
- `BaseTool` abstract base class with typed I/O and mock interface
- `SwarmProtocol`, `ProtocolState`, `ProtocolGuards` types

Tests: unit tests for all type construction, serialization, and equality.

Not included: any storage, any LLM, any runtime.

### M1: Graph Substrate (3-4 days)

Deliverables:
- In-memory graph store with typed node/edge CRUD and query API
- SQLite persistence layer for graph store
- `EdgeCreatedEvent`, `NodeDiscoveredEvent`, `NodeRemovedEvent` producers wired to graph mutations
- `InspectNode` and `QueryGraph` tools (real implementations, not just contracts)

Tests: graph CRUD, query correctness, event emission on mutation, full synthetic test of
multi-hop edge traversal.

### M2: Causal Event Bus (2-3 days)

Deliverables:
- Event bus with causal envelope enforcement (rejects events without `causal_parent_id` if `depth > 0`)
- Subscription routing from `EventPattern` definitions
- Depth tracking and budget enforcement per correlation
- `EmitEvent` tool

Tests: event routing correctness, depth limit enforcement, budget enforcement,
duplicate suppression window.

### M3: Turn Executor (3-4 days)

Deliverables:
- `TurnExecutor` that runs a `TurnContract` against a `BaseTool` set and an LLM client
- Structured output parsing with failure classification
- Retry logic with parse-focused reprompt
- `FailurePolicy` routing (`Retry`, `Escalate`, `Abandon`)
- `Echo` tool

Tests: all `FailureOutcome` types exercised synthetically, retry logic, policy routing.
First real LLM integration test (acceptance test, optional).

### M4: Protocol Engine (3-4 days)

Deliverables:
- `ProtocolEngine` that activates protocols from trigger events and advances state machines
- `DirectTask` protocol implemented and tested
- Protocol guard enforcement (max_depth, max_loops, timeout)
- Deadlock detection (cycle in active state graph)

Tests: synthetic full protocol run (all states), guard enforcement, failure recovery paths.

### M5: Memory Layer (2-3 days)

Deliverables:
- `memory.episode` and `memory.insight` node kinds in graph substrate
- Episode recording at end of each protocol run
- Memory recall query helpers
- Episode TTL and eviction
- Maintainer agent with insight distillation logic

Tests: episode creation/recall, insight promotion, TTL eviction, cross-agent memory query.

### M6: Synthetic Harness (2 days)

Deliverables:
- `SyntheticHarness` class with agent-response scripting API
- `SyntheticHarness.run_protocol()` method
- Harness assertions (event type counts, final state, failure mode)
- Documentation on writing synthetic tests

Tests: harness itself is self-testing; also used to add synthetic tests for M4 protocols.

### M7: Substrate Reflection (2-3 days)

Deliverables:
- `UpdateSubscription` and `RegisterProtocol` privileged tools
- `bootstrap_maintainer` agent with access to reflection tools
- Trial protocol activation with failure-based disabling
- `ViolationResponse` protocol (uses reflection to propose protocol adjustments)

Tests: synthetic reflection scenario (maintainer proposes subscription change, reviewer approves).

### M8: Adapter Integration (3-4 days)

Deliverables:
- Feature flag: `REMORA_PHASE2_RUNTIME=1`
- Route Neovim chat messages through Phase 2 `DirectTask` protocol when flag is set
- Route CLI `remora swarm start` through Phase 2 runtime when flag is set
- Emit Phase 2 causal events alongside legacy events (parallel logging, not replacement)

Tests: end-to-end test with mock LLM through Neovim LSP adapter; end-to-end test via CLI.

---

## 13. Risks and Mitigations

### Risk: Protocol state machines are rigid and can't handle novel situations

**Mitigation:** Every protocol has an `Escalate` path that routes to the `human_review` terminal state.
Novel situations are not silently handled — they are escalated and logged for protocol improvement.
Additionally, substrate reflection allows the maintainer to add protocols for recurring novel situations.

### Risk: Causal graph grows without bound

**Mitigation:** Causal metadata is stored in the event log (existing EventStore), not as separate graph
nodes. Graph query APIs load causal data on demand. Event log is append-only and compressible
(completed correlation chains can be archived). Memory episodes have TTLs.

### Risk: Substrate reflection enables the swarm to break itself

**Mitigation:** All protocol changes go through the reviewer. Newly registered protocols run in trial
mode. The `ProtocolGuards` struct enforces minimum safety properties (max_depth ≥ 2, timeout > 0).
Malformed protocol definitions are rejected at registration time by a schema validator.

### Risk: Synthetic harness diverges from real behavior

**Mitigation:** `BaseTool.mock_execute()` is tested against `BaseTool.execute()` in an integration
test suite. Each tool has documented invariants that both implementations must satisfy. Mock
implementations are not arbitrary — they return valid Output instances.

### Risk: Developer tooling adds maintenance burden

**Mitigation:** The inspector (`remora-bootstrap graph`, `remora-bootstrap protocols`) is implemented
as a thin CLI on top of the same graph query APIs that agents use. No separate state is maintained.
The CLI is correct if the graph API is correct.

### Risk: Phase 2 remains perpetually experimental

**Mitigation:** M8 (adapter integration) is explicitly in the plan and uses a feature flag.
The flag means Phase 2 ships to real users — even in a limited mode — before it is "complete."
Real usage feedback drives milestone prioritization.

---

## 14. How This Diverges from v1

v1 is a valid starting point. v2 does not replace it — it extends it with:

1. **Semantic node kinds** — v1 says "graph is the fabric" but only mentions code nodes. v2 adds
   spec, test, doc, agent, and memory kinds, making the graph genuinely multi-domain.

2. **Protocol state machines** — v1 relies entirely on subscription-based routing. v2 adds protocols
   as explicit state machines that bound and structure emergent behavior. Pure subscription routing
   remains for events that don't belong to an active protocol.

3. **TurnContracts** — v1 has `BootstrapCapability` as a concept. v2 specifies the contract structure,
   failure taxonomy, and retry policy concretely, making the executor implementable.

4. **Structured tool contracts** — v1 has `BootstrapTool` as a function. v2 has `BaseTool` as a class
   with typed I/O, side effect declarations, and mandatory mock implementations.

5. **Memory as graph** — v1 has `BootstrapMemory` as a single bullet. v2 defines memory node kinds,
   episode recording, insight distillation, and cross-agent memory recall.

6. **Substrate reflection** — v1 does not mention self-modification. v2 makes it a first-class
   deliverable (M7) with bounded, policy-controlled access.

7. **Developer inner loop** — v1 has no developer experience section. v2 defines the CLI, synthetic
   harness, graph inspector, and replay capability explicitly.

8. **Concrete delivery plan** — v1 has 6 milestones at a high level. v2 has 9 milestones (M0–M8)
   with deliverables, tests, and explicit "not included" scope boundaries.

v1 open questions answered by v2:
- Q1 (graph identity): independent identity, bi-directional mapping as migration bridge
- Q2 (capability policy): side_effects classification + agent role's allowed level
- Q3 (confidence/uncertainty): `confidence: float` field on `memory.insight` and `ProposePatch.Output`
- Q4 (adapter priority): Neovim (most visible surface for developer users)
- Q5 (replay/debug tooling): `remora-bootstrap replay` + graph inspector, M6 synthetic harness

---

*This document is a design proposal. It should be followed by:*
- *Implementation of M0 types as a concrete foundation*
- *A synthetic harness spec (`SYNTHETIC_HARNESS_SPEC.md`)*
- *An edge type vocabulary reference (`EDGE_TYPE_REFERENCE.md`)*
