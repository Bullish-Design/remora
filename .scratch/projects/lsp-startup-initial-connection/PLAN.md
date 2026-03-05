# PLAN — LSP Startup Initial Connection

**ABSOLUTE RULE: NO SUBAGENTS — NEVER use the Task tool. Do ALL work directly.**

## Phase 1: Reproduce and Measure Startup Gap
1. Capture a fresh startup run and record exact timestamps from:
   - client log (`M.setup`, `kick_lsp_start`, `get_client` transitions)
   - server log (`remora-lsp starting`, `INITIALIZED`)
   - Neovim LSP transport log (`~/.local/state/nvim/lsp.log`)
2. Quantify startup latency segments:
   - setup -> first `vim.lsp.start`
   - first `vim.lsp.start` -> server process start
   - server start -> `initialize`/`initialized`
3. Run headless attach probe and require `REMORA_CLIENTS>=1`.

## Phase 2: Isolate Blocking Path
1. Confirm whether startup delay is in client attach logic vs server process boot.
2. Confirm whether interactive stalls correlate with `_background_scan` `batch_append` slow windows.
3. Verify submit path under load:
   - `$/remora/requestInput` handled on client
   - `$/remora/submitInput` reaches server
   - `on_input_submitted` executes.

## Phase 3: Implement Targeted Fixes
1. Startup attach hardening:
   - tighten startup state machine so attach completion is explicit and deterministic.
   - avoid duplicate/thrashing `vim.lsp.start` retries if they delay attach.
2. Interactive preemption:
   - increase scan yielding/pausing around writes to prevent chat/panel starvation.
3. Panel resilience:
   - keep clear user-visible state for busy/timeouts and recover quickly after stall.

## Phase 4: Validate and Close
1. Validate with both:
   - manual run
   - headless attach probe (`nv2 --headless ... REMORA_CLIENTS=`)
2. Validate chat markers and panel cursor-follow behavior in the same session.
3. Update project docs (`CONTEXT`, `PROGRESS`, `ISSUES`) with final status.

## Acceptance Criteria
- Startup connection available without first chat/file-trigger workaround.
- Chat submit and response path proven in logs.
- Panel refresh no longer repeatedly times out during normal interaction.

**ABSOLUTE RULE: NO SUBAGENTS — NEVER use the Task tool. Do ALL work directly.**
