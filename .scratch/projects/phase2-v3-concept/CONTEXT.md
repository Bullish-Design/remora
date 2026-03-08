# Context: Phase 2 v3 Concept

## Status: COMPLETE (with extensions)

## What happened

### Session 1
Wrote PHASE2_V3_BOOTSTRAP_CONCEPT.md in bootstrap/.

### Session 2 (current)
1. Wrote RESEARCH.md — v1 AgentNode pattern analysis, AgentDefinition concept,
   Capability enum, BootstrapAgent model, capability ladder.

2. Updated PHASE2_V3_BOOTSTRAP_CONCEPT.md with new §6 "The Agent Model":
   - BootstrapAgent runtime model
   - Capability enum + mixin marker classes for composition
   - AgentDefinition authoring model with Pydantic mixin inheritance
   - Capability ladder (earn capabilities via RequestCapabilityEvent)
   - Developer visibility table (inspect/inject/pause/correct/observe/understand)
   - Renumbered §6-§8 → §7-§9

3. Wrote RESEARCH_2_MIXIN_ERGONOMICS.md — deep dive into:
   - Pydantic mixin baseclasses for capability composition (full analysis)
   - Other authoring patterns (decorators, builders, YAML, Protocol types)
   - Developer ergonomics (6 interaction operations: inspect, inject, pause, correct, observe, understand)
   - Schema diffusion as emergent inheritance (genome metaphor)
   - Recommended authoring stack synthesis

## Key decisions made

1. v3 is NOT "v2 + clarifications" — it's a fundamentally simpler document.
   The philosophy shift: specify the substrate only, let structure emerge.

2. The two clarifications that drove v3:
   - .pym scripts are the ONLY tool interface (enforced by Grail @external)
   - Agents need graph navigation (via new graph_* externals in BootstrapExternals)

3. Deliberately left unspecified: node kinds, edge kinds, protocol state
   machines, memory models, agent roles. These emerge from bootstrapping.

4. Graph library recommendation: SQLite (M0-M3) + Rustworkx (M4+)
   Options presented: Rustworkx+SQLite, NetworkX+SQLite, SQLite-only, Kuzu

5. CairnExternals grounding: the v1 CairnExternals.as_externals() dict is the
   exact enforcement mechanism. BootstrapExternals extends it with graph_* and
   event ops. Mutation ops are role-gated.

6. Agent model: BootstrapAgent (flat runtime) + Capability (enum) +
   AgentDefinition (Pydantic authoring model with mixin composition).
   Mixins are marker classes only (no fields) — clean diamond inheritance.
   `capabilities_from_definition()` derives frozenset from MRO at activation.

7. Developer ergonomics: 6 operations (inspect/inject/pause/correct/observe/understand)
   all work via graph queries + cairn workspace reads. No opaque state.
   AgentCatalog hot-reloads definitions from bootstrap/agents/*.py.

## Output files
/home/andrew/Documents/Projects/remora/bootstrap/PHASE2_V3_BOOTSTRAP_CONCEPT.md
/home/andrew/Documents/Projects/remora/.scratch/projects/phase2-v3-concept/RESEARCH.md
/home/andrew/Documents/Projects/remora/.scratch/projects/phase2-v3-concept/RESEARCH_2_MIXIN_ERGONOMICS.md
