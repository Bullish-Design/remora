# ASSUMPTIONS — LSP Startup Initial Connection

## Purpose
Fix startup behavior so Remora LSP is actually connected from Neovim launch time (without first command/file dance), while preserving chat delivery and panel responsiveness.

## User-Priority Outcomes
- `remora` client is attached shortly after Neovim startup, before first `RemoraChat` command.
- Chat submit reaches server (`on_input_submitted`) and turn execution starts (`execute_turn: START`).
- Agent panel updates with cursor movement instead of timing out under scan load.

## Constraints
- Keep lock-owner lifecycle hardening intact (`src/remora/lsp/__init__.py`).
- Do not regress deterministic chat-submit path already added in e2e.
- Use `devenv shell --` for project runtime/test commands.
- Prefer minimal, falsifiable changes (one causal lever per pass).
- NO SUBAGENTS.

## Definitions of Done
- Manual run logs show startup attach without waiting for first command.
- Headless probe prints `REMORA_CLIENTS>=1` reliably.
- At least one manual chat run contains markers:
  - `cmd_chat: requestInput sent`
  - `on_input_submitted: params=`
  - `execute_turn: START`
- Panel no longer stuck on repeated request timeouts during normal cursor movement.

## Non-Goals (for this project)
- Broad architecture rewrite of EventStore/event bus.
- Tuning model quality or prompt behavior.
- Reworking all scan/indexing behavior beyond what is required for interactive responsiveness.
