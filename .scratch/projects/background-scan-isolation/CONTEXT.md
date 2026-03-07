# Context: Background Scan Isolation

## Why This Project Exists
- Background scan timeout behavior was traced to scan execution-path instability under threaded offload.
- Immediate stabilization was done by moving scan read/parse back to synchronous execution in the scan task.
- This improved determinism, but does not fully separate scan workload from interactive-path performance risk.

## Current State
- We need an explicit architecture for isolation between:
  - parse workload,
  - scan ingestion workload,
  - user-interaction workload.
- We must preserve current EventStore correctness while reducing interaction-path contention.

## Next Work Item
- Decide and prototype the lowest-risk isolation pattern:
  - parser worker isolation + prioritized single DB writer.

