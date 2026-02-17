# DEV GUIDE STEP 3: Query Files + Node Discovery

## Goal
Load Tree-sitter queries and extract `CSTNode` objects from Python files.

## Why This Matters
Node discovery is the entrypoint for the entire analysis pipeline.

## Implementation Checklist
- Add `.scm` query files for `function_def`, `class_def`, and `file`.
- Implement query loader and file discovery.
- Build `NodeDiscoverer` that returns `CSTNode` objects.

## Suggested File Targets
- `remora/queries/function_def.scm`
- `remora/queries/class_def.scm`
- `remora/queries/file.scm`
- `remora/discovery.py`

## Implementation Notes
- Follow query definitions in `SPEC.md` section 5.
- Use Pydantree APIs to evaluate queries and map results to `CSTNode`.
- Ensure node IDs are deterministic hashes of path/type/name.

## Testing Overview
- **Unit test:** Query loader returns expected captures.
- **Unit test:** Discovery on fixture code returns correct nodes.
- **Error test:** Malformed query returns `DISC_002`.
- **Error test:** No nodes returns `DISC_004`.
