# Overview: Scan Parsing Isolation

## Problem
- Background scan work can delay or interfere with user-facing interactions.
- Even when parsing and DB writes are logically separate steps, they still compete for runtime and storage resources.
- Current SQLite-backed write path is sensitive to contention and scheduling behavior.

## Constraints
- Same primary DB is currently required.
- SQLite allows only one writer at a time.
- Existing behavior and schema compatibility must be preserved.
- Solution should be incremental and low-risk.

## Options
1. Keep current in-loop scan, tune sleeps/chunk sizes only.
- Pros: minimal engineering cost.
- Cons: does not provide robust isolation; prone to regressions.

2. Parser worker isolation + prioritized single DB writer.
- Pros: strong separation of CPU-bound parse work; clean write arbitration.
- Cons: moderate implementation complexity and queue/backpressure design needed.

3. Parser worker + staging storage + async merge into primary DB.
- Pros: strongest interaction-path isolation.
- Cons: highest complexity and more failure/reconciliation paths.

4. Multiple direct DB writers with retries/backoff.
- Pros: low upfront refactor in code shape.
- Cons: worst fit for SQLite lock model; can increase jitter and tail latencies.

## Brainstorm Ideas
- Add a bounded queue between parser output and DB ingestion.
- Tag writes with priority classes (`interactive`, `scan`).
- Enforce fairness policy to avoid starving scan.
- Add lock wait and queue depth metrics.
- Introduce kill-switch config to disable background scan dynamically.
- Emit periodic progress checkpoints independent of parse completion.

## Recommendation
- Implement Option 2 first:
  - isolate parsing from main interaction runtime,
  - funnel all writes through one prioritized writer queue.
- This yields the best balance of isolation, correctness, and incremental delivery.

## Next Steps
1. Define measurable SLOs (interactive p95 latency under scan load).
2. Prototype parser worker + prioritized writer queue.
3. Add load tests with concurrent chat/panel + scan ingestion.
4. Compare against current behavior and decide on staging-db v2 only if needed.

