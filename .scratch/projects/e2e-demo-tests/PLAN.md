# E2E Demo Tests — Plan

**NEVER use subagents (the Task tool). Do ALL work directly. NO EXCEPTIONS.**

## Goal

Build an end-to-end test framework that drives the Neovim LSP demo via tmux
send-keys, records terminal output with asciinema, and converts to GIF via agg.

## Architecture

```
remora/e2e/
  harness.py          # TmuxDriver, AsciinemaRecorder, scenario base
  scenarios/
    __init__.py
    startup.py        # LSP startup + agent discovery
    chat.py           # Chat with an agent
    rewrite.py        # Agent proposes rewrite
    proposal.py       # Accept/reject proposal flow
    cascade.py        # Agent A messages Agent B
    golden_path.py    # Full demo combining all above
  run.py              # CLI entry point
  output/             # .cast and .gif output
```

## Components

### TmuxDriver
- Creates a tmux session with fixed geometry (120x35)
- send_keys(keys, enter=True) — types into the pane
- wait_for_text(pattern, timeout=30) — polls capture-pane until match
- capture_pane() — returns current pane content as string
- Cleanup: kills session on exit

### AsciinemaRecorder
- Starts `asciinema rec` in a subprocess recording the tmux session
- --cols/--rows match the tmux geometry
- Stops on scenario completion, producing a .cast file

### Scenarios
Each scenario is a function: `run(driver: TmuxDriver) -> None`
It sends keys, waits for expected text, and asserts state.

### Runner (run.py)
- CLI: `python -m e2e.run [--scenario NAME] [--mock|--real] [--gif] [--list]`
- Iterates selected scenarios
- For each: create tmux session, start recorder, run scenario, stop recorder
- If --gif: convert .cast to .gif via agg

## Scenarios

1. **startup** — Open nv2 on demo project, wait for LSP to connect and discover agents (code lenses appear)
2. **chat** — Open file, position cursor on a function, run :RemoraChat, type message, see response in panel
3. **rewrite** — Trigger :RemoraRewrite on a function, see diagnostic annotation appear
4. **proposal** — After rewrite, accept or reject the proposal via code action
5. **cascade** — Trigger a change that causes agent A to message agent B
6. **golden_path** — Full demo: startup → edit file → agent analyzes → messages test agent → test agent proposes rewrite → user accepts

## LLM Mode
- `--mock` (default): Uses MockLLMClient from remora_demo/neovim/mock_llm.py
- `--real`: Uses a real LLM server (must be running at REMORA_LLM_URL)
- The demo project's remora.yaml already has `model_default: ${REMORA_MODEL:-mock}`

## Dependencies (nix)
- tmux (already available)
- asciinema (nixpkgs)
- asciinema-agg (nixpkgs, for GIF conversion)

**NEVER use subagents (the Task tool). Do ALL work directly. NO EXCEPTIONS.**
