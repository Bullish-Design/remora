# Hypothesis Report — Real Run Lock Owner Failure

## Problem Statement
On `2026-03-05 13:10-13:11`, chat commands in a real Neovim session failed before request-input because no remora LSP client could attach. Client retries repeatedly reported active lock ownership by `pid=250354`.

## Leading Hypothesis
A prior remora-lsp server process became orphaned/stuck as lock owner and did not terminate when its original client lifecycle ended. The stale owner remains alive and keeps workspace lock ownership, so all subsequent Neovim sessions fail to attach and abort commands.

## Why This Fits Evidence
- Current run repeatedly reports lock-owner hint `pid=250354` and no clients attached.
  - `client-2026-03-05_131041.log:146-148, 274-275, 458-460`
- Global LSP log shows concurrent startup collisions against same pid.
  - `~/.local/state/nvim/lsp.log:219550-219553`
- Lock file metadata matches that pid.
  - `.remora/lsp.pid:1`
- Owner process is still running long after original startup.
  - `ps -p 250354` (`elapsed ~1h40m`, high CPU usage)
- Owner's startup log exists, but no clean shutdown marker.
  - `server-2026-03-05_113451.log:2` start marker, tail has no shutdown message.

## Competing Hypotheses (Lower Confidence)
1. The owner process is healthy but all new sessions are in a different root/client scope and cannot discover it.
   - Less likely: lock hint and collision messages indicate shared workspace lock state.
2. PID metadata is stale while process is unrelated.
   - Less likely: live process command line is `remora-lsp` for the same repo environment.

## Most Likely Root Cause Category
- **Lifecycle management gap** in remora-lsp ownership model:
  - lock ownership persists without robust client-disconnect detection and shutdown,
  - plus insufficient stale-owner recovery logic when owner is alive but not serving current session.

## Immediate Operational Mitigation (Not a code fix)
- Terminate stale owner process `pid=250354` and rerun chat.
- Validate that a fresh server starts and emits normal submit/runner markers.
