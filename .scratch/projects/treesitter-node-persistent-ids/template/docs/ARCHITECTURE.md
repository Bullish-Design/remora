# Architecture Notes

## Layers
1. Parse layer: language-specific `Parser` objects + incremental tree cache.
2. Extract layer: Tree-sitter query captures for durable nodes only.
3. Identity layer: header-line scan for `graph:id` recovery.
4. Persistence layer: SQLite UPSERT into file/entity/entity_anchor/edge tables.
5. Writeback layer: optional mutation tool for adding missing IDs.

## Implementation Sequence
1. Implement Python extractor query capture mapping.
2. Implement Markdown section extraction + parent/child edge emission.
3. Add file hashing and upsert methods in `SQLiteStore`.
4. Add incremental parser edit flow in `ParserCache`.
5. Implement writeback with dry-run diff output before apply mode.

## Guardrails
- Never auto-write IDs when parse tree has syntax errors.
- Treat duplicate IDs as a blocking integrity error.
- Keep default mode read-only.
