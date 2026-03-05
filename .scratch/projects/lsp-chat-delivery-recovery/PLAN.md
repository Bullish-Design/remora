# PLAN — lsp-chat-delivery-recovery

**ABSOLUTE RULE: NO SUBAGENTS — NEVER use the Task tool. Do ALL work directly.**

## Phase 1: Forensics Baseline
1. Capture exact morning timeline and map commits to runtime logs.
2. Separate fixes into categories: lock-contention, startup-race, observability, process-isolation.
3. Record repeated loops and non-falsifiable experiments.

## Phase 2: Controlled Reproduction
1. Define a short baseline runbook (start server, submit N chats, collect log counters).
2. Capture metrics per run: submit count, emitted count, execute_turn count, calling LLM count, lock warnings/errors.
3. Confirm whether failures happen pre-runner or at LLM boundary.

## Phase 3: Targeted Remediation
1. Prioritize structural contention fixes over additional timeout/backoff tuning.
2. Ensure single-writer guarantees for event DB lifecycle.
3. Gate/pace background scanning during interactive chat windows.

## Phase 4: Verification and Closeout
1. Run baseline runbook after each change-set.
2. Update project docs with what worked, what did not, and why.
3. Keep an explicit “do-not-repeat” list to prevent circular debugging.

**ABSOLUTE RULE: NO SUBAGENTS — NEVER use the Task tool. Do ALL work directly.**
