# PROGRESS — LSP Startup Initial Connection

## Phase 1: Reproduce and Measure Startup Gap — IN PROGRESS
- [x] Create new project directory with standard files.
- [x] Import latest manual-run evidence into issue artifact folder.
- [ ] Re-run startup with fresh logs after this project handoff.
- [ ] Capture segmented latency metrics (setup->start->initialize->attach).

## Phase 2: Isolate Blocking Path — PENDING
- [ ] Determine why client shows repeated `NO remora clients found` before server starts.
- [ ] Confirm submit drop point in latest manual run (`buf_notify sent` but no server `on_input_submitted`).
- [ ] Confirm panel timeout correlation with scan write bursts.

## Phase 3: Implement Fixes — PENDING
- [ ] Implement startup attach reliability fix.
- [ ] Implement scan preemption improvements if still required.
- [ ] Implement/adjust panel recovery UX if still required.

## Phase 4: Validate and Close — PENDING
- [ ] Headless attach probe passes reliably.
- [ ] Manual startup+chat+panel workflow passes end-to-end.
- [ ] Finalize context for closeout.
