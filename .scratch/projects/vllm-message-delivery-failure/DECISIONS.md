# DECISIONS — vLLM Message Delivery Failure

## 2026-03-05 — Isolate vLLM Delivery into Dedicated Project
- Decision: Create a separate project from background-scan/startup work.
- Rationale: Prevent mixed root-cause analysis and focus on end-to-end model delivery.

## 2026-03-05 — Prefer Lightweight/Lazy Workspace Initialization in Runner Path
- Decision: Initialize runner workspace service with `SyncMode.NONE` and reuse it across turns.
- Rationale: Failing runs were timing out before model dispatch in workspace initialization; lazy sync plus reuse removes the largest pre-model cost from each chat turn.

## 2026-03-05 — Add Explicit Model-Boundary Diagnostics
- Decision: Add logs immediately before/after `kernel.run` including target `base_url` and `model`.
- Rationale: Makes it unambiguous whether a failing turn reached the vLLM dispatch boundary.
