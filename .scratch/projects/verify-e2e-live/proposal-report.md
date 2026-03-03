# Test Report: proposal

## Run Info
- **Date**: 2026-03-03 12:20
- **Result**: PASS (false positive)
- **Duration**: 27.7s
- **Cast file**: e2e/output/proposal_20260303_122006.cast
- **Iteration**: 1

## 1. Pre-Test Expectations

- Expected nv2 to open `test_loader.py` and show `test_load_yaml`
- Expected cursor to move to line 13
- Expected `<leader>rr` to trigger a rewrite proposal
- Expected `<leader>ry` to accept the proposal
- Expected file content to change after acceptance

## 2. Post-Test Observations

- **18 frames** over 17.6s
- File loaded correctly, `test_load_yaml` visible, cursor at line 13
- `[Remora]` appeared at 2.1s
- At frame 10 (6.3s), the which-key popup showed the `<leader>r` submenu (with "proposal", "accept" text)
- At frame 11 (6.6s): **`[Remora] LSP not running`** — same issue as rewrite scenario
- The rewrite + accept sequence did NOT actually work
- Final file state unchanged — `test_load_yaml` function is identical to the original
- Status line shows `E1 W2 H1` — these are standard pyright diagnostics, not Remora
- Scenario passes only because no assertions check for actual proposal/acceptance behavior

## 3. Changes / Fixes / Improvements

- **Same root cause as rewrite**: The Remora LSP is not recognized as running when `<leader>rr` fires
- **Pattern**: Both rewrite and proposal scenarios fire the rewrite command ~5-6s after nv2 opens. The startup scenario shows `[Remora]` at 2.1s, but the rewrite/proposal scenarios get "LSP not running" at ~6.5s. This could mean:
  1. The LSP initializes but then disconnects
  2. The rewrite command has a different LSP check than the notification system
  3. The working directory matters — `run_scenario` uses `DEMO_PROJECT` as working_dir
- **Need to investigate**: Why the LSP shows as "not running" for rewrite/proposal but chat works fine. The chat scenario successfully shows the agent panel with agent info.
- **Recommended**: Add `wait_for_text("[Remora]")` before rewrite commands and investigate the LSP readiness check
