# HYPOTHESIS REPORT — 2026-03-05 Latest Manual Run

## Primary Hypothesis
The system still has two coupled reliability gaps:
1. startup attach readiness is not deterministic (client retries long before server process appears), and
2. under background scan write pressure, interactive RPC paths (`submitInput`, panel fetch) can be starved long enough to appear dropped/timed-out.

## Why This Fits Current Evidence
- Client autostart logic executes immediately, but server process start is delayed by ~7s.
- Chat request path reaches server (`cmd_chat: requestInput sent`) but submit path never reaches server handler (`on_input_submitted=0`) in this run.
- Panel request timeouts and slow `batch_append` occur in same period.

## Alternative Hypotheses
- `vim.lsp.buf_notify(0, "$/remora/submitInput", params)` occasionally targets a buffer/client state that is not the active remora transport.
- Control-sequence pollution (`\f`) in fallback input callback may be corrupting submit payloads in edge cases.
- Logging noise/flush behavior hides late `on_input_submitted` events (less likely, because multiple downstream markers are also absent).

## Falsification Criteria
Primary hypothesis is wrong if, after startup-state instrumentation and scan preemption adjustments:
- startup still delays similarly but server process actually starts immediately (indicating timestamp/observation artifact), or
- submit still fails when scan is disabled/paused and transport confirms receipt attempt at server boundary, or
- panel timeouts persist with scan paused and low write load.

## Minimal Next Fix Direction
1. Add explicit startup-stage telemetry around client-side attach and server boot boundary.
2. Add explicit server-side receipt logging for `$/remora/submitInput` before handler body normalization.
3. Tighten interactive preemption rules during scan writes (pause/yield earlier and more often around append chunks).

## Code Focus Areas
- `src/remora/lsp/nvim/lua/remora/init.lua`
- `src/remora/lsp/notifications.py`
- `src/remora/lsp/__main__.py`
- `src/remora/lsp/nvim/lua/remora/panel.lua`

## Expected Success Evidence
- Startup: `REMORA_CLIENTS>=1` from headless probe, with reduced/no long retry streak.
- Submit: server logs `on_input_submitted: params=` after client `buf_notify sent`.
- Turn: server logs `execute_turn: START` and subsequent response markers.
- Panel: no repeated timeout warnings during normal cursor movement.
