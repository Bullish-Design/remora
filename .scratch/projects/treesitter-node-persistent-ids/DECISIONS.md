# Decisions

1. Scaffold is isolated under `template/`.
Reason: avoids accidental coupling with current Remora runtime while design stabilizes.

2. Keep writeback as a separate module and CLI path.
Reason: safer rollout; read-only indexing can be validated before code mutation is enabled.

3. Use relational schema (entity/entity_anchor/edge/file) instead of a generic JSON node table.
Reason: aligns with performance and query clarity goals from the concept doc.

4. Include both query files and raw line scanning support in the scaffold.
Reason: extraction should be language-aware, while ID recovery should remain language-agnostic.
