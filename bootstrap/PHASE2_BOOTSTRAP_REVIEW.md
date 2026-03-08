# Phase 2 Bootstrap Concept: Review

> Reviewed against codebase state as of 2026-03-07

---

## Executive Summary

The Phase 2 Bootstrap Concept is directionally correct. The graph-first, event-sourced, emergence-via-local-rules
architecture aligns well with what Remora is actually trying to be. But the concept is significantly more complete
as a vision document than as an execution guide. Several critical design decisions are deferred as "open questions"
that are in fact **blocking prerequisites** for any code. The bootstrap implementation that exists today
(`bootstrap/src/remora_bootstrap/`) is almost entirely hollow: two toy tools, two agents with no LLM
integration, a runtime with three methods, and no `BootstrapNode` or `BootstrapEdge` types despite these being
listed as core primitives.

The concept is worth building on. But before starting Milestone 2, several gaps need to be closed.

---

## What the Concept Gets Right

### 1. Layered architecture is clean

The four-layer model (Graph → Swarm → Emergence → Adapters) is a good separation of concerns. It makes the
dependency direction explicit: adapters are thin, emergence is policy, swarm is mechanics, graph is data.
This is a meaningful improvement over the current implicit coupling between LSP handlers, AgentRunner,
and execution internals.

### 2. "No backward-compat burden" is the right call

Phase 2 needs room to make clean decisions. The current codebase has accumulated constraints from evolving
design: `runner/agent_runner.py` importing from `lsp.models` (a layer violation), `core/events/events.py`
with in-degree 33, tool definitions locked to Grail `.pym` scripts. Forcing backward compat into a new
core would inherit all of this. Correct instinct to start clean in `bootstrap/`.

### 3. Incremental milestones are sensible

The six-milestone delivery plan is the right shape. Each milestone is independently shippable and tests
a different layer. The feature-flag integration at Milestone 5 is the right way to run dual runtimes safely.

### 4. Guardrails section shows awareness of the main failure mode

Emergent loops are the real risk in any reactive swarm. The concept lists depth limits, cooldown windows,
per-agent quotas, and duplicate suppression. These are the right primitives. Having them listed explicitly
is better than discovering the need for them after a production incident.

### 5. Event-sourced design aligns with existing Remora strengths

Remora already has a solid append-only EventStore (SQLite), subscription pattern matching, and a
five-module event taxonomy. Phase 2 can build on this directly rather than reinventing it.

---

## What's Missing or Unclear

### 1. The core primitives don't exist yet

Section 5 lists six "minimum primitives to make Phase 2 real":
`BootstrapNode`, `BootstrapEdge`, `BootstrapEvent`, `BootstrapCapability`, `BootstrapAgentProfile`, `BootstrapMemory`.

None of these are in `bootstrap/src/remora_bootstrap/`. The only contracts defined are `BootstrapTool`,
`BootstrapAgent`, and `BootstrapTemplate` — which are registry entries, not graph/event primitives.
Milestone 1 is labelled "Contracts + Registry" and marked conceptually complete, but it isn't.

### 2. The bootstrap runtime cannot execute an agent turn

`BootstrapRuntime` in `runtime.py` has three methods: `create()`, `render_template()`, and `call_tool()`.
There is no LLM client, no turn executor, no event emission, no subscription routing. The two defined agents
(`bootstrap_orchestrator`, `bootstrap_editor`) have `allowed_tools` fields but nothing that enforces or
invokes them. The concept is ahead of the implementation by roughly three milestones.

### 3. The emergence model is a principle, not a design

Section 6 states "agents respond only to subscribed event patterns" and "agents act only through allowed
capabilities." These are correct constraints. But the concept doesn't specify:

- **How does scoring work?** When multiple agents match a trigger, which activates? What's the algorithm?
- **What is a "capability" at execution time?** A named function? An LLM tool schema? A declared Python class?
- **How are budgets tracked across a correlation chain?** The correlation ID exists in the concept but
  not in the bootstrap event model.
- **What does convergence detection look like?** "Convergence diagnostics when convergence fails" (Section 10)
  implies some state that can be inspected — that state isn't defined.

### 4. "Tool use is brittle" is a stated pain point with no proposed solution

Section 1 lists "tool use is brittle when models drift into text-only pseudo-calls" as a current problem.
Section 5's `BootstrapCapability` — "named executable operation with schema, policy constraints, and handler"
— is meant to fix this. But the concept doesn't explain *how* the capability schema enforces structured
output. Does Phase 2 use constrained decoding? Retry logic with typed failure classification? A response
parser that maps freeform text to capability calls? This is a load-bearing gap.

### 5. The open questions in Section 12 are blocking, not optional

Section 12 treats five open questions as post-alignment decisions:

- **Q1 (graph identity independence)** determines whether existing node IDs can be reused in bootstrap
  context, or whether Phase 2 creates a parallel identity system that needs eventual reconciliation.
  This affects *every* graph API design decision in Milestones 1–2.

- **Q2 (capability policy language)** is required to implement the turn executor in Milestone 3.
  Without a policy language, "capability gating" is just an allow-list of strings.

- **Q4 (which adapter first)** determines the integration target for Milestone 5. Choosing wrong
  wastes milestone effort.

These need answers before Milestone 1 code, not after Milestone 6.

### 6. "Remora as library" tension is unresolved

The concept says bootstrap should "treat `remora` as a library dependency." But Remora's current Python
API is tightly coupled to specific runtime assumptions:

- `Config` and `load_config()` assume a `.remora/` directory and `remora.yaml`
- `EventStore` is backed by SQLite at a specific path within that directory
- `AgentNode` is simultaneously a DB row model, an LLM prompt builder, and an LSP response format

These are implementation classes, not stable library interfaces. The bootstrap already uses
`from remora.core.config import Config, load_config` (in `runtime.py`) — but if bootstrap needs its
own graph model, its own event format, or a different storage backend, "treat as library" breaks quickly.

The concept should explicitly define which Remora modules are stable library surface (e.g., EventStore,
SubscriptionPattern, CSTNode) versus implementation details that bootstrap should not depend on.

### 7. Memory is a single bullet point

`BootstrapMemory` is described as "short-horizon interaction memory plus durable event-linked memory
entries." That's it. Memory is one of the hardest cross-cutting concerns in multi-agent systems. How does
an agent's memory relate to the graph? Is memory per-agent or queryable across agents? What's the eviction
policy for short-horizon memory? How does durable memory link back to specific events without creating
unbounded cross-references? This needs its own design section, not a single bullet.

### 8. Developer experience in bootstrap mode is absent

The concept defines what to build but not how a developer experiences it. There is no mention of:
- How to run a single bootstrap turn for testing
- What a developer sees when a turn fails (which failure mode?)
- How to inspect live graph state during development
- Whether bootstrap has a CLI, a REPL, or just unit tests

This matters because "developer velocity: time from idea → new bootstrap capability → tested runtime path
measured and trending down" is a stated success metric. Velocity requires good tooling. The concept
doesn't propose any.

---

## Architectural Concerns

### The graph model conflates code graph and coordination fabric

Section 4 says "the graph is not just code indexing data — it is the coordination fabric for swarm behavior."
This is a strong claim. If the graph drives both code structure queries and swarm activation, changes to
one affect the other. A node being "discovered" in code also potentially triggers agent activation. This
conflation may be fine, but the concept doesn't address what happens when graph queries are slow (e.g.,
large repos), or how agent activation is isolated from graph maintenance operations.

### Typed edges are listed but not enumerated

The concept mentions "typed edges (contains, references, depends_on, coordinates, proposes_change_to)"
as a design goal. But these five edge types are listed without semantics. `coordinates` between what and
what? Does `coordinates` imply subscription? Does `proposes_change_to` represent a pending change or a
historical one? The edge type vocabulary is the backbone of the graph model and needs specification
before the graph substrate can be implemented.

### The bootstrap package structure mixes concerns

`remora_bootstrap/bootstrap.py` calls `build_default_registry()` which currently registers two tools
and two agents. This is a startup script, not a bootstrap. The package structure is:
```
contracts.py     → types
registry.py      → storage
runtime.py       → facade
bootstrap.py     → wiring
tools/core.py    → implementations
agents/core.py   → implementations
templates/core.py → (empty)
```

This structure won't scale to the full bootstrap stack cleanly. As capabilities, protocols, event types,
and graph models are added, the flat package will need reorganization that will break import paths.
Worth planning the package structure now.

---

## Readiness Assessment

| Aspect | Concept Completeness | Implementation Completeness |
|--------|---------------------|----------------------------|
| Graph substrate (nodes, edges, identity) | Outlined | 0% |
| Event envelope + bus | Mentioned | 0% (reuses Remora EventStore indirectly) |
| Subscription routing | Described | 0% |
| Turn executor + capability gating | Described | 0% |
| Emergence guardrails | Listed | 0% |
| Tool contracts | High-level | 20% (echo + plan_stub only) |
| Agent contracts | High-level | 10% (names + allowed_tools, no execution) |
| Templates | Mentioned | 0% |
| Memory model | Single bullet | 0% |
| Adapter integration | Conceptual | 0% |
| Developer tooling | Not mentioned | 0% |

Milestone 1 ("Bootstrap Contracts + Registry") is closer to 15% complete, not ready.
Milestone 2 cannot start until Milestone 1 is actually done.

---

## Recommendations

1. **Resolve the four blocking open questions before writing any Milestone 2 code:**
   - Graph identity strategy (independent vs. bi-directional mapping)
   - Capability policy language (even a simple string-matching DSL is better than nothing)
   - First adapter target (Neovim or CLI — pick one and commit)
   - How structured output is enforced (constrained decoding, retries, parser, or all three)

2. **Specify the edge type vocabulary.** Define all planned edge types with their semantics before
   implementing the graph substrate. This vocabulary is the API that agents program against.

3. **Define "Remora as library" boundaries explicitly.** List which modules are stable public API
   (safe to import in bootstrap) and which are implementation details (bootstrap should reimplement).

4. **Add a developer experience section.** Define the "inner loop" for bootstrap development:
   how to run a test turn, what failure output looks like, how to inspect graph state.

5. **Treat memory as a first-class design concern.** Write a section on bootstrap memory model
   before implementing `BootstrapMemory`.

6. **Revise Milestone 1 completion criteria.** Current Milestone 1 is not done. Completion should
   require: all six primitive types implemented, registered, and covered by unit tests.

7. **Add a synthetic test harness to the plan.** Testing emergence without a live LLM requires
   deterministic mock infrastructure. This should be an explicit milestone, not an afterthought.

---

The concept is worth building. The direction is right. But it needs more specificity at the
architectural level before coding proceeds, and the gap between "concept complete" and
"implementation ready" is larger than the current framing suggests.
