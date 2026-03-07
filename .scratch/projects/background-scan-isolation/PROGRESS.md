# Progress: Background Scan Isolation

## Setup
- [x] Create project template directory and standard files.
- [x] Create overview analysis (problem/options/ideas/recommendation).

## Phase 1: Baseline and Constraints
- [ ] Define measurable interactive latency targets.
- [ ] Capture baseline under scan load.
- [ ] Capture DB lock/contention baseline.

## Phase 2: Architecture and Design
- [ ] Choose parser isolation model (process/thread/in-loop).
- [ ] Design prioritized DB write path.
- [ ] Define failure/retry and backpressure behavior.

## Phase 3: Implementation
- [ ] Implement parser isolation v1.
- [ ] Implement prioritized writer queue v1.
- [ ] Add instrumentation.

## Phase 4: Verification
- [ ] Add/extend targeted tests.
- [ ] Run non-cairn suites.
- [ ] Summarize performance deltas and residual risks.

