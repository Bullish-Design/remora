# DEV GUIDE STEP 3: Query Files + Node Discovery

## Goal
Load Tree-sitter queries and extract `CSTNode` objects from Python source files using Pydantree.

## Why This Matters
The node discovery step is the entry point for all analysis. Every FunctionGemma runner is scoped to a single `CSTNode`. If discovery is broken or produces incorrect node IDs, all downstream runner and workspace operations will be inconsistent.

## Implementation Checklist
- Bundle `.scm` query files in `remora/queries/`: `function_def.scm`, `class_def.scm`, `file.scm`.
- Implement `NodeDiscoverer` class that takes a list of root directories and a list of query names.
- Compute `node_id` as a stable hash of `(file_path, node_type, name)`.
- Return `list[CSTNode]` with all required fields populated.
- Map malformed `.scm` query errors to `DISC_002`.
- Map file-not-found errors to `DISC_001`.

## Suggested File Targets
- `remora/queries/function_def.scm`
- `remora/queries/class_def.scm`
- `remora/queries/file.scm`
- `remora/discovery.py`

## CSTNode Model

```python
class CSTNode(BaseModel):
    node_id: str        # Stable hash of (file_path, node_type, name)
    node_type: Literal["file", "class", "function"]
    name: str
    file_path: Path
    start_byte: int
    end_byte: int
    text: str           # Full source text of the node
```

## Implementation Notes
- Use Pydantree's query runner API to evaluate `.scm` files against parsed Python source.
- Node IDs must be stable across runs for the same source code. Use `hashlib.sha1` over the concatenated key fields.
- For file-level nodes, `name` should be the filename stem (e.g., `utils` for `src/utils.py`).
- Nodes at different granularities from the same file are all valid — a function inside a class produces both a class node and a function node.

## Testing Overview
- **Unit test:** Discovery on `tests/fixtures/sample.py` returns expected node count and types.
- **Unit test:** Node IDs are stable across two calls with the same input.
- **Unit test:** Overlapping queries (function inside class) produce distinct nodes with distinct IDs.
- **Unit test:** Malformed `.scm` query returns `DISC_002` error, not an unhandled exception.
- **Unit test:** Each returned `CSTNode.text` matches the actual source span in the file.
