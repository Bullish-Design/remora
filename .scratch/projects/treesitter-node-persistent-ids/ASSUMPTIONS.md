# Assumptions

1. The scaffold is a template-only project under `.scratch/projects/treesitter-node-persistent-ids/template/` and is not yet wired into `src/remora`.
2. Durable IDs are source-of-truth identities embedded in declaration header lines as `graph:id=<id>`.
3. First-class languages in v1 are Python (`.py`) and Markdown (`.md`).
4. SQLite is the persistence layer with WAL mode and UPSERT-based idempotent writes.
5. Incremental parse support (`Tree.edit`, `old_tree`, `changed_ranges`) is a required phase-2 capability.
6. Writeback/auto-annotation is intentionally separated from read-only indexing for safer rollout.
