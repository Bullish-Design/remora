# Progress

- [x] Implement semantic node identity as `sha256(file_path:node_type:full_name)[:16]` in core discovery.
- [x] Add shared `compute_source_hash()` in core discovery and replace duplicate hash helpers/usages.
- [x] Refactor LSP watcher to stateless `parse(uri, text)` conversion with deterministic IDs from parse output.
- [x] Remove save-time source mutation and inline ID injection flow from LSP document handlers/server path.
- [x] Rewire background scan and server reparse to use watcher parse + orphan diffing in caller logic.
- [x] Update spawn_child and reconciler to use unified identity/hash primitives.
- [x] Update exports and all affected tests for new APIs and semantic ID behavior.
- [x] Verify with targeted + integration tests covering discovery, watcher, background scan, reconcile, and spawn_child paths.
