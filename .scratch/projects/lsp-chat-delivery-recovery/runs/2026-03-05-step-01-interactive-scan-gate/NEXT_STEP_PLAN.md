# Next Step Plan — Step 01 (Interactive Scan Gate)

## Goal
Run one minimal, falsifiable remediation focused on structural contention: suspend or strongly pace background `NodeDiscoveredEvent` writes while an interactive chat window is active.

## Exact Change Set (single hypothesis)
1. In LSP startup/background-scan flow, add a strict gate:
- If recent user interaction exists (chat submit / command activity inside the current window), do not emit scan-driven node-discovery events.
- Resume scan emission only after a quiet interval.
2. Keep all retry/backoff settings unchanged in this step.
3. Keep Neovim startup/retry wiring unchanged in this step.

## Why This Step
- Current logs show very large `NodeDiscoveredEvent` storms (`matched 0 agents`, `0 handlers`) during chat windows.
- This step isolates whether reducing concurrent scan writes improves the submit -> emit -> runner -> LLM chain reliability.

## Expected Log Outcomes After Change
1. During interactive windows:
- Large reductions in repeated `NodeDiscoveredEvent` triplets.
- Lower/no `append: database locked` and `batch_append: database locked` bursts.
2. Per chat submission:
- `on_input_submitted` appears.
- `HumanChatEvent emitted` appears for the same submission window.
- `execute_turn: START` appears.
- `execute_turn: ... calling LLM` appears.
3. After quiet window:
- Background scan logs may resume, but without starving chat path writes.

## Falsification Criteria
- If lock storms and missing `HumanChatEvent emitted` still occur at similar rates despite scan gating, this hypothesis is rejected and we move to a different structural writer-ownership change.

## Input Logs Simplified In This Step
- `server-2026-03-05_092528.log`
- `client-2026-03-05_092508.log`
- `server-2026-03-05_094004.log`
- `client-2026-03-05_093938.log`
- `server-2026-03-05_094547.log`
- `client-2026-03-05_094526.log`
- `server-2026-03-05_105316.log`
- `client-2026-03-05_105301.log`
