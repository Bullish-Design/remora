# PROGRESS — LSP Startup Initial Connection

## Phase 1: Reproduce and Measure Startup Gap — IN PROGRESS
- [x] Create new project directory with standard files.
- [x] Import latest manual-run evidence into issue artifact folder.
- [x] Create one-page startup audit checklist with file/line checkpoints.
- [ ] Re-run startup with fresh logs after this project handoff.
- [ ] Capture segmented latency metrics (setup->start->initialize->attach).

## Phase 2: Isolate Blocking Path — DONE
- [x] Determine why client shows repeated `NO remora clients found` before server starts.
- [x] Confirm submit drop point in latest manual run (`buf_notify sent` but no server `on_input_submitted`).
- [x] Confirm panel timeout correlation with scan write bursts.

## Phase 3: Implement Fixes — DONE
- [x] Implement startup attach reliability fix.
- [x] Implement scan preemption improvements if still required.
- [x] Implement/adjust panel recovery UX if still required.
- [x] Fix Neovim 0.11 `_uninitialized` flag in `get_client()` (all 3 `get_clients` call sites).
- [x] Clean up debug wrapper `tmp_bin/remora-lsp` (removed stdout redirect that broke LSP protocol).

## Phase 4: Validate and Close — IN PROGRESS
- [x] Unit tests pass (lock owner + server: 7/7).
- [ ] Headless attach probe passes reliably.
- [ ] Manual startup+chat+panel workflow passes end-to-end.
- [ ] Finalize context for closeout.
