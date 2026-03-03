# E2E Demo Tests — Progress

- [x] Plan architecture
- [x] Create project scaffold
- [x] Add asciinema + asciinema-agg to devenv.nix (already present)
- [x] Build core harness (TmuxDriver + AsciinemaRecorder)
- [x] Scenario: LSP startup + agent discovery
- [x] Scenario: Chat with agent
- [x] Scenario: Agent proposes rewrite
- [x] Scenario: Accept/Reject proposal
- [x] Scenario: Agent cascade
- [x] Full golden path scenario
- [x] GIF conversion step (cast_to_gif in harness.py)
- [x] Runner script (run.py)
- [x] Smoke test all scenarios (6/6 pass, no recording)

## Status: COMPLETE

All scenarios implemented and passing. Recording (asciinema) and GIF
conversion (agg) require running inside the devenv shell where those
tools are on PATH.
