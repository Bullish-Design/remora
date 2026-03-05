# DECISIONS — LSP Startup Initial Connection

## Decision 1: Split Startup Reliability Into Its Own Project
**Date:** 2026-03-05

The prior project (`lsp-chat-delivery-recovery`) accumulated multiple intertwined tracks (lock ownership, submit path, panel behavior, scan contention). Startup attach reliability remains unresolved, so this project isolates that objective with its own evidence and plan.

## Decision 2: Treat Startup As Failed Unless Headless Attach Probe Shows a Real Client
**Date:** 2026-03-05

`e2e.run --scenario startup` can false-pass on UI/init notifications. For this project, startup success requires direct client attach evidence (`REMORA_CLIENTS>=1` from `nv2 --headless` probe).

## Decision 3: Preserve Existing Lock-Owner Hardening; Do Not Roll It Back
**Date:** 2026-03-05

Lock-owner lifecycle protections are in place and address a prior failure mode. Further startup work should build on top, not revert, unless new evidence directly proves those changes cause regressions.
