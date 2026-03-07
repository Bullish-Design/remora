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
