# Phase 2 Bootstrap Concept: Emergent Graph/Swarm Remora

## Table of Contents

1. Vision and Problem Statement
   Defines what Phase 2 is trying to change and why the bootstrap approach matters now.
2. Design Principles
   Establishes strict rules to keep the new architecture clean, composable, and emergent.
3. Scope and Boundaries
   Clarifies what is in scope for bootstrap Phase 2 and what remains out of scope.
4. Target Architecture
   Describes the layered architecture: graph substrate, swarm runtime, and product surfaces.
5. Core Bootstrap Primitives
   Defines the minimum set of node, event, memory, and capability primitives needed to start.
6. Emergence Model
   Explains how local agent rules produce global behavior without hardcoded orchestration paths.
7. Initial Bootstrap Stack (Tools, Agents, Templates)
   Proposes the first practical bootstrap-native components to implement.
8. Runtime Flow for a User Message
   Walks through end-to-end message processing in the new model.
9. Incremental Delivery Plan
   Breaks the concept into pragmatic milestones that can ship independently.
10. Risks and Mitigations
    Identifies major technical and product risks with concrete mitigations.
11. Success Metrics
    Defines measurable outcomes for validating the Phase 2 direction.
12. Open Questions
    Lists unresolved decisions that need fast alignment early in execution.

## 1. Vision and Problem Statement

Phase 2 reframes Remora as a bootstrap-native multi-agent platform that uses Remora itself as the substrate for building Remora. The immediate goal is not just "better chat" or "better tools"; it is a cleaner system model where:

- The graph is the primary source of structure.
- The swarm is the primary source of behavior.
- Product surfaces (Neovim panel, CLI, web) are adapters, not architectural anchors.

Current pain points this addresses:

- Too many implicit pathways between UI, runner, and execution internals.
- Tool use is brittle when models drift into text-only pseudo-calls.
- Agent behavior is often prompt-coupled instead of state-coupled.
- Architectural intent (event-driven swarm) is stronger than current implementation boundaries.

Phase 2 concept: bootstrap a new core in `bootstrap/` that treats `remora` as a library and builds an explicit graph/swarm runtime from first principles.

## 2. Design Principles

1. Graph-first, not file-first.
- Files are one projection. The core model is a graph of nodes and relations.

2. Event-sourced runtime, not hidden state mutation.
- Durable events are authoritative; projections and UI state are derivative.

3. Local rules, global emergence.
- Agents follow local policies and capabilities; system-level behavior emerges from interactions.

4. Capability-based execution.
- Agents can only execute declared capabilities. No hidden "magic" control paths.

5. Deterministic observability.
- Every important decision point emits structured events and diagnostics.

6. No backward-compatibility burden for Phase 2 core.
- Phase 2 is a new clean path. Adapters can exist later, but core design should not inherit old constraints.

## 3. Scope and Boundaries

In scope:

- Bootstrap-native tool contracts, agent contracts, and template contracts.
- Graph node identity and relationship model for code + swarm artifacts.
- Event bus, subscription/routing model, and swarm trigger semantics.
- Phase 2 runtime flow from user intent to tool execution and feedback.

Out of scope (initially):

- Reusing existing `agents/*` bundle behavior as a dependency.
- Grail `.pym` runtime as a required execution path.
- Full migration of every existing Remora feature on day one.

## 4. Target Architecture

### Layer A: Graph Substrate

Responsibilities:

- Node identity, attributes, relationships, and lifecycle.
- Typed edges (contains, references, depends_on, coordinates, proposes_change_to).
- Event projections into query-optimized views.

Core idea: the graph is not just code indexing data. It is the coordination fabric for swarm behavior.

### Layer B: Swarm Runtime

Responsibilities:

- Agent instantiation from graph nodes + policies.
- Trigger matching and routing (events -> candidate agents).
- Turn execution with explicit capability checks.

Core idea: the swarm runtime consumes graph and events, then produces new events and graph updates.

### Layer C: Emergence Engine

Responsibilities:

- Priority/scoring strategies for which agents activate.
- Budgeting (turn budgets, token budgets, retry budgets).
- Stability controls (cooldowns, cycle detection, convergence checks).

Core idea: emergence is enabled by policy and constrained by guardrails.

### Layer D: Product Adapters

Responsibilities:

- Neovim panel, CLI, web, API integrations.
- Request/response shaping only.
- No domain logic that bypasses graph/swarm runtime.

Core idea: every surface is thin and replaceable.

## 5. Core Bootstrap Primitives

Minimum primitives to make Phase 2 real:

1. `BootstrapNode`
- Stable `node_id`, kind, labels, metadata, optional source anchor.

2. `BootstrapEdge`
- `from_id`, `to_id`, typed relation, optional weight/confidence.

3. `BootstrapEvent`
- Typed event envelope with correlation id, causal parent, payload.

4. `BootstrapCapability`
- Named executable operation with schema, policy constraints, and handler.

5. `BootstrapAgentProfile`
- Agent identity, role, allowed capabilities, goals, and operating policy.

6. `BootstrapMemory`
- Short-horizon interaction memory plus durable event-linked memory entries.

These primitives should remain implementation-agnostic enough to support Python-only runtime now and distributed runtime later.

## 6. Emergence Model

Emergence in Phase 2 should be intentional, not accidental.

Local rules:

- Agents respond only to subscribed event patterns.
- Agents act only through allowed capabilities.
- Agents produce proposals/messages/events instead of direct global mutation.

Global behaviors expected to emerge:

- Automatic propagation from source changes to tests/docs/consumers.
- Multi-agent decomposition of broad user objectives.
- Self-stabilizing execution via cooldown/depth/budget controls.

Required guardrails:

- Hard limits on chain depth and per-correlation activations.
- Duplicate-trigger suppression windows.
- Per-agent and per-capability quotas.
- Termination diagnostics when convergence fails.

## 7. Initial Bootstrap Stack (Tools, Agents, Templates)

### Tools (initial)

- `echo`: round-trip diagnostics and plumbing validation.
- `plan_stub`: objective-to-plan scaffolding.
- `inspect_node`: graph introspection for local reasoning.
- `emit_event`: explicit event generation for controlled swarm testing.
- `propose_patch_stub`: proposal envelope generation before full rewrite tooling.

### Agents (initial)

- `bootstrap_orchestrator`
  - Objective decomposition and routing.
- `bootstrap_editor`
  - Patch proposal synthesis.
- `bootstrap_reviewer`
  - Constraint and regression review on proposals.
- `bootstrap_maintainer`
  - Graph hygiene, stale edge cleanup, policy tuning suggestions.

### Templates (initial)

- `phase2_system`: hard boundary rules for bootstrap mode.
- `task_intake`: normalize intent into objective/constraints/output contract.
- `proposal_review`: structured review rubric.
- `handoff_message`: canonical inter-agent message format.

## 8. Runtime Flow for a User Message

Target end-to-end path:

1. Adapter receives user message.
2. Message normalized into `UserIntentEvent`.
3. Graph lookup identifies anchor node(s) and relevant neighborhood.
4. Swarm runtime scores candidate agents for activation.
5. Selected agent executes one bounded turn using allowed capabilities.
6. Tool results and agent outputs are emitted as events.
7. Projection updates graph/materialized state.
8. Adapter streams deterministic event timeline + final response.

Key property: if no valid capability invocation occurs, the system should emit a typed failure reason (parser mismatch, schema mismatch, policy denial, runtime error) rather than generic "no tool calls" ambiguity.

## 9. Incremental Delivery Plan

Milestone 1: Bootstrap Contracts + Registry

- Finalize core contracts and registry APIs in `bootstrap/`.
- Add unit tests for registration and capability lookup.

Milestone 2: Event + Runtime Skeleton

- Add event envelopes, subscriptions, and trigger routing in bootstrap runtime.
- Add deterministic trace IDs and lifecycle logging.

Milestone 3: Agent Turn Engine

- Add bounded turn executor with capability gating.
- Support at least one real capability invocation path end-to-end.

Milestone 4: Emergence Guardrails

- Add depth/cooldown/quota policies and convergence diagnostics.

Milestone 5: Adapter Integration

- Route Neovim/CLI message handling through Phase 2 runtime path behind a feature flag.

Milestone 6: Progressive Migration

- Migrate selected high-value workflows from legacy paths into bootstrap-native equivalents.

## 10. Risks and Mitigations

Risk: Dual runtime confusion during migration.
- Mitigation: explicit feature flag + explicit telemetry tags per runtime path.

Risk: Emergence turns into nondeterministic churn.
- Mitigation: strict budgets, termination reasons, and replayable event traces.

Risk: Over-design before proving value.
- Mitigation: ship minimal vertical slices per milestone with measurable outcomes.

Risk: Model/tool-call inconsistency persists.
- Mitigation: parser hardening, strict response contracts, and capability-level diagnostics.

## 11. Success Metrics

1. Reliability
- Tool-capable turns that successfully execute at least one capability: target > 95% on golden flows.

2. Observability
- 100% of failed turns produce typed failure classification.

3. Architectural cleanliness
- Reduction in cross-layer coupling points between adapters and runtime.

4. Emergence quality
- At least two multi-agent cascades that complete with bounded convergence and no manual orchestration.

5. Developer velocity
- Time from idea -> new bootstrap capability -> tested runtime path measured and trending down.

## 12. Open Questions

1. Should bootstrap graph identities be fully independent from legacy node IDs, or mapped bi-directionally?
2. What is the minimal policy language for capability gating in Phase 2?
3. How should we represent confidence/uncertainty on emergent decisions?
4. Which adapter (Neovim vs CLI) should be the first default surface for bootstrap runtime?
5. What replay/debug tooling is required before broader rollout?

---

This document is an initial concept draft for alignment. It should be followed by:

- A concrete execution plan (`PHASE2_BOOTSTRAP_PLAN.md`)
- A runtime data contract spec (`PHASE2_BOOTSTRAP_CONTRACTS.md`)
- A first vertical-slice implementation checklist with tests
