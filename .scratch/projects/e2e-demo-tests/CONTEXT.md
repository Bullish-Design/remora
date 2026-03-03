# E2E Demo Tests — Context

## Status: COMPLETE

## What Was Done

Built a complete E2E test framework that drives the Neovim LSP demo via
tmux send-keys, records terminal output with asciinema, and converts
recordings to GIF via agg.

### Files Created

| File | Purpose |
|------|---------|
| `e2e/__init__.py` | Package init |
| `e2e/harness.py` | Core: TmuxDriver, AsciinemaRecorder, cast_to_gif, Scenario protocol, run_scenario |
| `e2e/run.py` | CLI runner: `python -m e2e.run [--scenario NAME] [--mock/--real] [--gif] [--list] [--no-record]` |
| `e2e/scenarios/__init__.py` | Scenario registry (ALL_SCENARIOS dict) |
| `e2e/scenarios/startup.py` | LSP startup + agent discovery |
| `e2e/scenarios/chat.py` | Chat with load_config agent |
| `e2e/scenarios/rewrite.py` | Trigger rewrite, verify diagnostic |
| `e2e/scenarios/proposal.py` | Accept proposal via code action |
| `e2e/scenarios/cascade.py` | Edit triggers cascade: source agent -> test agent |
| `e2e/scenarios/golden_path.py` | Full demo flow (all beats) |
| `e2e/output/` | Directory for .cast and .gif files |

### Test Results

All 6 scenarios pass (no-record mode, ~110s total):
- startup: 8.9s
- chat: 13.9s
- rewrite: 12.7s
- proposal: 16.2s
- cascade: 17.7s
- golden_path: 39.7s

### Usage

```bash
# Inside devenv shell:
python -m e2e.run --list                    # List scenarios
python -m e2e.run --no-record               # Run all without recording
python -m e2e.run --scenario startup        # Run one scenario
python -m e2e.run --gif                     # Record + convert to GIF
python -m e2e.run --real                    # Use real LLM
```

### Notes
- asciinema and agg are in devenv.nix packages but only available inside `devenv shell`
- The current opencode bash session doesn't have devenv PATH, so recording tests require manual devenv entry
- All scenarios use mock LLM by default (REMORA_MODEL=mock)
- TmuxDriver properly cleans up sessions on exit (verified: no leftover sessions)
