# Assumptions: Background Scan Isolation

- Primary goal is to protect interactive user latency (chat, panel, edits) while preserving scan correctness.
- Event persistence should remain in the current primary EventStore DB unless there is a strong reason to add staging storage.
- SQLite write-lock behavior is a hard constraint: multiple concurrent writers will contend.
- Incremental adoption is preferred over a large rewrite.
- Existing behavior and data model semantics should remain compatible unless explicitly versioned.

