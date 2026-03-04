# Documentation Rework — CONTEXT

## Current State: PROJECT COMPLETE

All 4 priority phases (P0, P1, P2, P3) have been implemented and committed.

## Commits
1. `4015ca1` — docs(P0): move 16 root files, delete stale docs, merge ARCHITECTURE.md
2. `cc08207` — docs(P1): fix stale references in README, HOW_TO_USE, INSTALLATION, UI API
3. `aa30c24` — docs(P2): archive old plans/training, delete SPEC.md, revise reference docs
4. `197c26d` — docs(P3): fix guides accuracy, revise architecture.md fields/schema, update server docs

## Summary of All Changes

### P0 (File restructuring)
- Moved 13 root-level historical .md files to .hidden/
- Moved 3 plan files to docs/plans/
- Deleted docs/CONCEPT.md and docs/reports/cairn_test_coverage.md
- Merged docs/ARCHITECTURE.md into docs/architecture.md

### P1 (Core doc fixes)
- README.md: SwarmState→AgentNode, pip→devenv/uv, doc link fix
- HOW_TO_USE_REMORA.md: SwarmState section replaced, --nvim→--lsp, endpoints added
- docs/INSTALLATION.md: complete rewrite for devenv/uv
- docs/REMORA_UI_API.md: complete rewrite with actual endpoints
- pyproject.toml: readme field and description fixed

### P2 (Archive and reference docs)
- Moved 10 old plans and training_examples/ to .hidden/ (untracked)
- Deleted docs/SPEC.md
- Rewrote TESTING_GUIDELINES.md, TROUBLESHOOTING.md, API_REFERENCE.md

### P3 (Guides and accuracy)
- getting-started.md: stale pip install → devenv/uv instructions
- customization.md: removed non-existent swarm_state.db
- programming-workflow.md: port 8000→8420
- architecture.md: fixed AgentNode fields table, events table schema, DB location claims, Grail tool example, complete built-in tools list
- server/README.md: added Qwen3 model info
- server/SERVER_DEV_GUIDE.md: added deprecation note, updated model reference

## No Further Work Required
This project is fully complete. All documentation has been audited and corrected.
