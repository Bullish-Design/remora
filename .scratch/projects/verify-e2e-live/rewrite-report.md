# Test Report: rewrite

## Run Info
- **Date**: 2026-03-03 12:18
- **Result**: PASS (false positive — see observations)
- **Duration**: 19.3s
- **Cast file**: e2e/output/rewrite_20260303_121844.cast
- **Iteration**: 1

## 1. Pre-Test Expectations

- Expected nv2 to open `loader.py` and show `def load_config`
- Expected cursor to move to line 12 (load_config signature)
- Expected `<leader>rr` to trigger a rewrite request to the LSP
- Expected a diagnostic annotation or rewrite proposal to appear
- Expected pane to stabilize after the rewrite completes

## 2. Post-Test Observations

- **13 frames** recorded over 11.9s
- File loaded and `def load_config` visible
- `[Remora]` notification appeared around frame 4-5 (2.4-3.2s) with initialization info
- Cursor moved to line 12 (`:12` visible in command line at frame 12)
- **Critical**: At frame 10 (6.9s), after `<leader>rr`, a notification appeared:
  `[Remora] LSP not running — is this a supported filetype?`
- This means the **rewrite command did not work** — the Remora LSP was not recognized as running when the rewrite was triggered
- The scenario still PASSES because the only assertion is `wait_for_stable` + `capture_pane` — no actual verification that a rewrite occurred
- The breadcrumb shows `Fn load_config > Var path` — cursor is on the `path` parameter in the signature
- No diagnostic annotations, no rewrite proposal visible in the recording

## 3. Changes / Fixes / Improvements

- **False positive**: The scenario passes but the rewrite didn't actually happen. The scenario needs stronger assertions.
- **LSP issue**: The `[Remora] LSP not running` message suggests a timing issue. The LSP may need more startup time before rewrite commands work. The scenario's flow is:
  1. `open_nvim()` with 3s LSP_STARTUP_DELAY
  2. `goto_line(12)` 
  3. `leader_rewrite()` (sends `<Space>rr` then waits 5s)
  - The rewrite command fires at ~5.6-6.4s after nv2 opens. The LSP may not be fully ready.
- **Recommended fixes**:
  1. Add `driver.wait_for_text("[Remora]", timeout=15)` before the rewrite command to ensure LSP is running
  2. Add an assertion that checks for rewrite-specific content (diagnostic, proposal text, or diff markers)
  3. Increase the LSP startup delay or wait for a specific ready indicator
- **The "LSP not running" error** may indicate the nv2 plugin's rewrite handler checks LSP connection status and the connection hasn't stabilized by the time the command runs
