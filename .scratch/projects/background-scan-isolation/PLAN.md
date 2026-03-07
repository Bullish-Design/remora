# Plan: Background Scan Isolation

CRITICAL RULE: NO SUBAGENTS. All work in this project is done directly.

## Goal
Design and implement an architecture where parsing and scan ingestion do not materially degrade the main user interaction path.

## Ordered Steps
1. Capture baseline
- Measure current interactive latency under background scan load.
- Record DB lock/contention metrics and scan throughput.

2. Define architecture boundary
- Separate parse execution from DB write execution.
- Define explicit contracts for parsed payload handoff.

3. Implement low-risk v1
- Introduce parser isolation (worker process or dedicated worker runtime).
- Introduce prioritized DB write queue (interactive writes > scan writes).

4. Validate behavior and performance
- Add targeted load tests for scan + interactive operations.
- Verify correctness parity for nodes/edges/proposals/manifests.

5. Decide on v2 extensions
- Evaluate staged DB/log merge if write contention remains meaningful.
- Decide whether to keep single writer or graduate to staged ingestion.

## Acceptance Criteria
- Interactive p95 latency remains within target under active scan load.
- Background scan completes successfully with deterministic progress.
- No regressions in existing LSP/background-scan tests.
- Architecture boundaries are documented and test-enforced.

CRITICAL RULE: NO SUBAGENTS. Execute all steps directly.

