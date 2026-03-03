# ASSUMPTIONS: E2E Harness Review

## Audience

The primary consumer of `E2E_HARNESS_UPDATES.md` is the developer(s) who will implement fixes to the E2E harness, keys.py, and scenario files. The document should be actionable — specific enough to implement from without needing to re-read the individual reports.

## Constraints

- Changes should be backward-compatible with existing scenario patterns
- The harness (`e2e/harness.py`) and keys API (`e2e/keys.py`) are the shared infrastructure; scenario files are consumers
- The demo project (`remora_demo/project/`) is fixed — test infrastructure adapts to it, not vice versa
- Backend bugs (like `to_llm_tool`) are documented but not fixed by this review — they belong to separate projects

## Key Context

- All 12 scenarios currently PASS, even though many are false positives
- The vLLM server works (model responds) — the issues are in test infrastructure and timing
- The Remora LSP does initialize (startup scenario proves it) but `<leader>rr` fails with "LSP not running"
- Panel and chat commands (`<leader>ra`, `<leader>rc`) generally work; rewrite (`<leader>rr`) does not
- Agent discovery takes time — early file opens may show "No agent at cursor"

## Invariants

- DemoProjectGuard must always restore files (it does)
- Scenarios should be independent (currently violated by chat state leaking)
- Every scenario should have at least one meaningful assertion
