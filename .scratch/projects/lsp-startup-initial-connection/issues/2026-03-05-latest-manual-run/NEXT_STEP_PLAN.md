# NEXT STEP PLAN — 2026-03-05 Latest Manual Run

## Goal
Make startup attach deterministic and keep chat/panel interactive paths responsive during scan load.

## Step 1: Reproduce With Fresh Baseline
1. `devenv shell -- uv sync --extra dev`
2. Run headless attach probe:
   ```bash
   devenv shell -- nv2 --headless remora_demo/companion/demo/harness.py \
     "+lua vim.defer_fn(function() local clients=vim.lsp.get_clients({name='remora'}); print('REMORA_CLIENTS=' .. tostring(#clients)); vim.cmd('qa!') end, 10000)"
   ```
3. Run one manual startup + chat + panel loop and capture newest logs.

## Step 2: Add/Verify Startup Boundary Telemetry
- In `init.lua`, log explicit timestamps for:
  - first `vim.lsp.start` request
  - first observed remora client attach
  - attach delay duration in ms
- In server startup path, ensure lock-acquire/startup stage logs are visible and timestamped.

## Step 3: Add Submit Receipt Boundary Logging
- Add a server-side log at the earliest `$/remora/submitInput` receipt boundary (before normalization/branching).
- Validate marker chain:
  - client `buf_notify sent`
  - server receipt marker
  - `on_input_submitted: params=`

## Step 4: Strengthen Interactive Preemption During Scan
- Revisit scan loop in `__main__.py`:
  - pause sooner on recent user activity
  - yield between chunks and between files
  - keep chunk size conservative when interactive commands are active
- Re-run manual workflow to verify panel timeout reduction.

## Step 5: Validate and Record
- Required markers in final proving run:
  - startup: `REMORA_CLIENTS>=1`
  - chat: `cmd_chat: requestInput sent`, `on_input_submitted: params=`, `execute_turn: START`
  - panel: no repeated timeout storm
- Update `PROGRESS.md` and `CONTEXT.md` immediately after validation.

## Abort Conditions
If three consecutive attempts fail with no new evidence, create `ISSUE_002.md` with:
- exact commands run
- logs compared
- what changed vs prior attempt
- why each hypothesis was falsified.
