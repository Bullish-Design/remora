# Test Report: startup

## Run Info
- **Date**: 2026-03-03 12:16
- **Result**: PASS
- **Duration**: 10.9s
- **Cast file**: e2e/output/startup_20260303_121606.cast
- **Iteration**: 1

## 1. Pre-Test Expectations

- Expected nv2 to open `remora_demo/project/src/configlib/loader.py` within 5s
- Expected `def load_config` to be visible in the pane after file loads
- Expected `[Remora]` notification to appear within 15s of file open
- Expected pane to stabilize within 2s after LSP finishes
- Expected total scenario duration under 30s

## 2. Post-Test Observations

- **7 frames** recorded over 7.1s total
- nv2 opened the file and `def load_config` was visible by frame 4 (2.1s)
- `[Remora]` appeared at **2.1s** — well within the 15s timeout
- The notification text is: `[Remora] nv2 initialized remora pl` (truncated due to panel width)
- The notification appears in a **right-side panel** (after `│` separator), not as an inline Neovim message
- The status line shows `Normal  src/configlib/loader.py  python utf-8[unix] 1.09KiB`
- File content fully visible: lines 1-31 of loader.py showing all three functions (load_config, detect_format partially)
- Pane stabilized cleanly — no errors, no timeouts
- `assert "def load_config" in content` passed on the captured pane

## 3. Changes / Fixes / Improvements

- **No fixes needed** — scenario passes reliably on first attempt
- **Observation**: The `[Remora]` notification appears in a side panel area, not as a vim message. The `wait_for_text("[Remora]", timeout=15)` works because `capture_pane` captures the full terminal including the panel.
- **Potential improvement**: Could add a more specific assertion to check that the notification text indicates successful initialization (e.g., regex for `\[Remora\].*initializ`), but the current loose check is fine for a startup test.
- **Timing note**: 2.1s for [Remora] is fast — the `LSP_STARTUP_DELAY` of 3.0s in keys.py is appropriate as a conservative default.
