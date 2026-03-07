# DECISIONS

## 2026-03-07 — Start a dedicated follow-up project for cognitive-load reduction
- Decision: create a new `.scratch/projects/architecture-mental-model-simplification/` project rather than extending the previous refactor project.
- Rationale: this work is a new optimization pass (mental model and coupling pressure), not only continuation of earlier cycle-removal tasks.

## 2026-03-07 — Keep all architecture diagrams locally in project scope
- Decision: copy all current architecture graph artifacts into this project's `diagrams/` tree.
- Rationale: ensures next-session continuity and avoids dependency on external paths/history.

## 2026-03-07 — Prioritize rule enforcement before deep refactor
- Decision: execute Tach policy constraints first (W1) before large code moves.
- Rationale: guardrails prevent regressions while deeper decomposition work proceeds.

## 2026-03-07 — Pull event decomposition forward (W4 is highest value)
- Decision: original plan ordered W3 (events decomposition) after W2 (LSP/runner decoupling).
  Revised plan makes W4 (event hub decomposition) the highest-priority structural workstream.
- Rationale: core.events.events has in-degree 29 — more than any other module. No module can be
  understood in isolation while 29 others pull in the same mega-file. This is the primary cognitive
  load problem.

## 2026-03-07 — RewriteProposal moves to runner.models, not lsp.models
- Decision: create remora.runner.models and move RewriteProposal and generate_id there.
- Rationale: proposals are a runner domain concept (pending code changes the runner creates).
  They do not belong in the lsp adapter layer. lsp.models becomes a thin re-export for compat.

## 2026-03-07 — from_cst_node factory moves to code.discovery as node_to_event()
- Decision: remove NodeDiscoveredEvent.from_cst_node() classmethod; replace with a
  remora.core.code.discovery.node_to_event() module-level function.
- Rationale: event type definitions must not depend on domain services. The factory method was
  the sole cause of the events.events → code.discovery edge (in-degree source of the hub).

## 2026-03-07 — extensions is a confirmed leaf; no restructuring needed
- Decision: remora.extensions stays as-is (depends_on = []). No structural changes.
- Rationale: extensions has no remora dependencies. Multiple adapters depending on it is fine
  for a utility/plugin-host leaf. The rule to codify: extensions must remain depends_on = []
  and core must never depend on it.

## 2026-03-07 — Lsp* event aliases in lsp.models to be removed
- Decision: remove LspAgentEvent, LspHumanChatEvent, etc. re-export aliases from lsp.models.
- Rationale: they are type aliases with no semantic value. Callers should import directly
  from remora.core.events.events (or the bounded modules after W4).

## 2026-03-07 — Remove compatibility shims after W6/W7
- Decision: delete transitional compatibility modules/shims instead of preserving old import paths.
  - Deleted `remora.lsp.models`
  - Deleted `remora.core.events.events`
  - Removed `register_handlers` shim from `remora.lsp.server`
- Rationale: architecture clarity is prioritized over backwards compatibility. Tests were updated to
  target canonical modules so compatibility layers are unnecessary maintenance burden.
