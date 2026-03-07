# Decisions: Background Scan Isolation

## D-001 (Provisional)
- Prefer a single, prioritized DB writer over multiple competing writers.
- Rationale: aligns with SQLite lock model and minimizes lock thrash.
- Status: provisional pending benchmark confirmation.

## D-002 (Provisional)
- Prefer parser isolation in a separate worker process for stronger runtime isolation.
- Rationale: avoids event-loop/thread-pool interference with interactive operations.
- Status: provisional pending implementation complexity review.

