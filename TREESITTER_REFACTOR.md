# Tree-sitter Refactor Plan

## Executive Summary

We're replacing the broken pydantree dependency with direct tree-sitter Python API usage. This eliminates a broken CLI dependency, improves performance, and gives us full control over the discovery pipeline.

**Current State:** Remora calls `pydantree run-query` which doesn't exist (documented but never implemented).  
**Target State:** Direct tree-sitter Python API with in-process parsing and query execution.  
**Breaking Changes:** Yes - we're taking this opportunity to improve the API since backward compatibility is not a concern.

---

## Why We're Changing

### Problems with Current Approach

1. **Broken Dependency:** pydantree's `run-query` command is documented in README but never implemented in the actual CLI
2. **Subprocess Overhead:** Spawning external processes for every discovery operation is slow and fragile
3. **Poor Error Handling:** Subprocess failures give limited context, hard to debug
4. **Unnecessary Abstraction:** pydantree was designed for codegen workflows (generating Pydantic models from .scm files), not for runtime query execution
5. **Maintenance Burden:** External dependency with its own bugs and versioning issues

### Benefits of Direct Tree-sitter

1. **Performance:** In-process execution, no subprocess overhead
2. **Reliability:** Direct API calls with proper error handling
3. **Flexibility:** Full access to tree-sitter features (tree caching, incremental parsing, etc.)
4. **Simplicity:** Remove an entire layer of abstraction
5. **Maintainability:** Pure Python codebase, easier to debug and extend

---

## Architecture Overview

### New Architecture

```
Source Files (.py)
       ↓
Tree-sitter Parser (in-process)
       ↓
Query Engine (loads .scm files)
       ↓
Match Extraction
       ↓
CSTNode Models (simplified)
       ↓
Consumers (analyzer, orchestrator, etc.)
```

### Key Components

1. **TreeSitterDiscoverer** (replaces PydantreeDiscoverer)
   - Manages parser lifecycle
   - Loads and caches queries
   - Orchestrates file discovery
   - Emits events for observability

2. **QueryLoader**
   - Discovers .scm files from query packs
   - Compiles tree-sitter queries
   - Validates query syntax
   - Provides query metadata

3. **SourceParser**
   - Parses source files into tree-sitter trees
   - Handles parse errors gracefully
   - Supports tree caching for performance

4. **MatchExtractor**
   - Executes queries against parsed trees
   - Extracts captures and metadata
   - Builds CSTNode instances

5. **CSTNode** (simplified model)
   - Core data structure for discovered nodes
   - Reduced field set, clearer semantics
   - Factory methods from tree-sitter matches

---

## Step-by-Step Implementation Plan

### Phase 1: Foundation (Setup & Dependencies)

**Goal:** Establish new dependencies and basic structure without breaking existing code.

1. **Add Dependencies**
   - Add `tree-sitter` and `tree-sitter-python` to pyproject.toml
   - Remove `pydantree` dependency
   - Run `uv sync` to update lock file

2. **Create New Module Structure**
   ```
   remora/discovery/
   ├── __init__.py
   ├── discoverer.py       # TreeSitterDiscoverer
   ├── query_loader.py     # Query loading and compilation
   ├── source_parser.py    # File parsing
   ├── match_extractor.py  # Query execution
   └── models.py           # CSTNode and related models
   ```

3. **Define Core Models** (`models.py`)
   - Define simplified CSTNode dataclass
   - Define Capture model for query captures
   - Define QueryMetadata for query pack info

4. **Stub Old Discovery Module**
   - Keep `remora/discovery.py` temporarily
   - Have it import from new location with deprecation warnings
   - Or move to `discovery_legacy.py` for reference

**Success Criteria:**
- `uv sync` completes successfully
- Can import new modules without errors
- Dependencies resolved

---

### Phase 2: Core Implementation

**Goal:** Build the actual tree-sitter integration components.

1. **Implement QueryLoader** (`query_loader.py`)
   - Load .scm files from `queries/<language>/<pack>/`
   - Compile queries using tree-sitter Query API
   - Handle query syntax errors with clear messages
   - Support metadata extraction (query name, description)
   - Cache compiled queries

2. **Implement SourceParser** (`source_parser.py`)
   - Initialize tree-sitter parser for Python
   - Parse file contents to Tree
   - Handle parse errors (log warning, return None)
   - Optional: Implement tree caching with LRU cache

3. **Implement MatchExtractor** (`match_extractor.py`)
   - Execute compiled queries against trees
   - Extract capture groups
   - Map captures to CSTNode fields
   - Handle overlapping matches
   - Filter duplicate nodes

4. **Implement TreeSitterDiscoverer** (`discoverer.py`)
   - Initialize components (loader, parser, extractor)
   - Walk directory tree for source files
   - Parse each file
   - Run all queries
   - Collect and return CSTNode list
   - Emit events via existing event emitter
   - Handle errors gracefully (don't fail entire discovery on one bad file)

**Success Criteria:**
- Can discover nodes from a test Python file
- All components unit tested independently
- Error handling works correctly

---

### Phase 3: Migration & Integration

**Goal:** Replace old discovery with new, update all consumers.

1. **Update Import Statements**
   - `remora/analyzer.py`
   - `remora/orchestrator.py`
   - `remora/runner.py`
   - `remora/subagent.py`
   - `remora/__init__.py`
   - `scripts/remora_demo.py`

2. **Update Configuration** (`remora/config.py`)
   - Remove pydantree-specific config
   - Update DiscoveryConfig for new approach
   - Update validation rules

3. **Remove Old Discovery Code**
   - Delete `remora/discovery.py` (or move to `discovery_legacy.py`)
   - Remove pydantree-specific error codes
   - Clean up imports

4. **Update Tests**
   - Rewrite `tests/test_discovery.py`
   - Use real tree-sitter instead of mocks
   - Add tests for new components
   - Update fixtures if needed

**Success Criteria:**
- All existing tests pass
- Integration tests work
- No references to pydantree remain

---

### Phase 4: Cleanup & Optimization

**Goal:** Polish and optimize the implementation.

1. **Performance Optimization**
   - Add tree caching (parse once, query multiple times)
   - Add parallel file processing (ThreadPoolExecutor)
   - Profile and optimize hot paths

2. **Enhanced Error Reporting**
   - Add source location context to errors
   - Improve error messages with suggestions
   - Add query validation on load

3. **Documentation**
   - Update docstrings
   - Update README with new architecture
   - Add developer docs for adding new queries

4. **Final Cleanup**
   - Remove pydantree from pyproject.toml entirely
   - Delete any remaining pydantree references
   - Clean up __pycache__ and .pyc files

**Success Criteria:**
- Performance benchmarks show improvement
- Documentation complete
- Ready for release

---

## Detailed API Changes

### Old API (PydantreeDiscoverer)

```python
from remora.discovery import PydantreeDiscoverer
from remora.config import DiscoveryConfig

config = DiscoveryConfig(
    language="python",
    query_pack="remora_core",
    include_patterns=["*.py"],
    exclude_patterns=["test_*"],
)

discoverer = PydantreeDiscoverer(
    root_dirs=[Path("./src")],
    config=config,
    event_emitter=emitter,
)

nodes = discoverer.discover()  # Called pydantree CLI via subprocess
```

### New API (TreeSitterDiscoverer)

```python
from remora.discovery import TreeSitterDiscoverer
from remora.discovery.models import DiscoveryConfig

config = DiscoveryConfig(
    language="python",
    query_pack="remora_core",
    include_patterns=["*.py"],
    exclude_patterns=["test_*"],
)

discoverer = TreeSitterDiscoverer(
    root_dirs=[Path("./src")],
    config=config,
    event_emitter=emitter,
)

nodes = discoverer.discover()  # In-process tree-sitter execution
```

### CSTNode Changes

**Old Model:**
```python
class CSTNode(BaseModel):
    id: str                    # Stable hash ID
    file_path: str
    node_type: str            # "file", "class", "function"
    name: Optional[str]
    start_byte: int
    end_byte: int
    captures: List[Capture]    # Detailed capture info
```

**New Model:**
```python
@dataclass(frozen=True)
class CSTNode:
    id: str                    # Stable hash: hashlib.sha256(f"{file}:{name}:{start_byte}").hexdigest()[:16]
    file_path: Path            # Path object instead of string
    node_type: NodeType        # Enum: FILE, CLASS, FUNCTION, METHOD
    name: str                  # Required, empty string if anonymous
    start_byte: int
    end_byte: int
    start_line: int            # NEW: Human-readable line number
    end_line: int              # NEW: Human-readable line number
    source_text: str           # NEW: Extracted source snippet
    
    @property
    def full_name(self) -> str:
        """Qualified name including parent classes/modules"""
        ...
```

### Configuration Changes

**Old:**
```python
class DiscoveryConfig(BaseModel):
    language: str = "python"
    query_pack: str = "remora_core"
    pydantree_timeout: int = 30  # pydantree-specific
```

**New:**
```python
@dataclass
class DiscoveryConfig:
    language: str = "python"
    query_pack: str = "remora_core"
    query_dir: Path = Path("queries")  # NEW: Configurable query location
    cache_trees: bool = True           # NEW: Enable tree caching
    max_workers: int = 4               # NEW: Parallel processing
    fail_fast: bool = False            # NEW: Stop on first error vs continue
```

---

## File-by-File Changes

### New Files to Create

1. **`remora/discovery/__init__.py`**
   - Public exports
   - Backward compatibility aliases (if any)

2. **`remora/discovery/models.py`**
   - CSTNode dataclass
   - Capture dataclass
   - QueryMetadata dataclass
   - NodeType enum
   - DiscoveryConfig dataclass

3. **`remora/discovery/query_loader.py`**
   - QueryLoader class
   - .scm file discovery
   - Query compilation
   - Syntax validation

4. **`remora/discovery/source_parser.py`**
   - SourceParser class
   - Tree-sitter parser initialization
   - File parsing with error handling
   - Tree caching

5. **`remora/discovery/match_extractor.py`**
   - MatchExtractor class
   - Query execution
   - Capture extraction
   - CSTNode construction

6. **`remora/discovery/discoverer.py`**
   - TreeSitterDiscoverer class
   - Orchestration logic
   - Event emission
   - Error handling

### Files to Modify

1. **`pyproject.toml`**
   - Remove: `"pydantree"` from dependencies
   - Remove: `[tool.uv.sources]` pydantree entry
   - Add: `"tree-sitter>=0.20", "tree-sitter-python>=0.20"`

2. **`remora/config.py`**
   - Update DiscoveryConfig class
   - Remove pydantree-specific settings
   - Add new tree-sitter settings

3. **`remora/analyzer.py`**
   - Update import: `from remora.discovery import TreeSitterDiscoverer`
   - Update instantiation

4. **`remora/orchestrator.py`**
   - Update import
   - Update discovery instantiation

5. **`remora/runner.py`**
   - Update import
   - Update discovery instantiation

6. **`remora/subagent.py`**
   - Update import
   - Update discovery instantiation

7. **`remora/__init__.py`**
   - Update exports if needed

8. **`scripts/remora_demo.py`**
   - Update import
   - Update discovery instantiation

### Files to Delete

1. **`remora/discovery.py`**
   - Move to `remora/discovery_legacy.py` temporarily for reference
   - Delete after migration complete

### Files to Update (Tests)

1. **`tests/test_discovery.py`**
   - Complete rewrite
   - Use real tree-sitter
   - Test new components individually
   - Integration tests

---

## Testing Strategy

### Unit Tests

Test each component in isolation:

1. **QueryLoader Tests**
   - Load queries from directory
   - Handle missing query pack
   - Validate query syntax
   - Test caching

2. **SourceParser Tests**
   - Parse valid Python
   - Handle syntax errors
   - Test tree caching
   - Handle binary files

3. **MatchExtractor Tests**
   - Execute simple query
   - Handle multiple captures
   - Handle overlapping matches
   - Construct CSTNode correctly

4. **TreeSitterDiscoverer Tests**
   - Discover nodes from directory
   - Handle empty directory
   - Handle permission errors
   - Test event emission

### Integration Tests

1. **End-to-End Discovery**
   - Full discovery on test fixture
   - Verify node count and types
   - Verify byte ranges
   - Verify source text extraction

2. **Error Scenarios**
   - Invalid query syntax
   - Unparseable source file
   - Missing query pack
   - Permission denied

3. **Performance Tests**
   - Benchmark vs old implementation
   - Test with large codebase
   - Memory usage profiling

### Test Fixtures

Keep existing `tests/fixtures/sample.py` but may add:
- `tests/fixtures/invalid_syntax.py` - For error handling tests
- `tests/fixtures/edge_cases.py` - Anonymous functions, nested classes, etc.

---

## Error Handling Strategy

### Error Types

Create specific exception classes:

```python
class DiscoveryError(Exception):
    """Base exception for discovery errors"""
    pass

class QuerySyntaxError(DiscoveryError):
    """Invalid tree-sitter query syntax"""
    def __init__(self, query_file: Path, line: int, message: str):
        ...

class SourceParseError(DiscoveryError):
    """Failed to parse source file"""
    def __init__(self, file_path: Path, error: str):
        ...

class QueryPackNotFound(DiscoveryError):
    """Query pack directory doesn't exist"""
    def __init__(self, pack_path: Path):
        ...
```

### Error Behavior

**By Default (fail_fast=False):**
- Log warnings for individual file errors
- Continue processing other files
- Return successfully discovered nodes
- Emit error events for observability

**With fail_fast=True:**
- Raise exception on first error
- Useful for CI/CD pipelines

### Error Context

Include in error messages:
- File path
- Line number (where applicable)
- Query name (if query-related)
- Suggestion for fix

---

## Migration Checklist

### Pre-Migration
- [ ] Review all files that import from `remora.discovery`
- [ ] Identify custom query packs beyond `remora_core`
- [ ] Document current behavior for edge cases
- [ ] Backup working state

### Phase 1: Foundation
- [ ] Update pyproject.toml dependencies
- [ ] Run `uv sync`
- [ ] Create new directory structure
- [ ] Define core models
- [ ] Verify imports work

### Phase 2: Core Implementation
- [ ] Implement QueryLoader with tests
- [ ] Implement SourceParser with tests
- [ ] Implement MatchExtractor with tests
- [ ] Implement TreeSitterDiscoverer with tests
- [ ] All unit tests passing

### Phase 3: Migration
- [ ] Update all import statements
- [ ] Update config.py
- [ ] Move discovery.py to discovery_legacy.py
- [ ] Create new discovery package
- [ ] Update integration tests
- [ ] Run full test suite

### Phase 4: Cleanup
- [ ] Remove discovery_legacy.py
- [ ] Clean up pydantree references
- [ ] Update documentation
- [ ] Performance benchmarks
- [ ] Final review

### Post-Migration
- [ ] Verify no pydantree references remain (`grep -r pydantree .`)
- [ ] Run full test suite
- [ ] Test on real codebase
- [ ] Update CHANGELOG
- [ ] Tag release

---

## Risks and Mitigations

### Risk: Performance Regression
**Mitigation:** Implement tree caching and parallel processing in Phase 4

### Risk: Query Syntax Differences
**Mitigation:** Validate all existing .scm files work with tree-sitter Python API

### Risk: Different Match Behavior
**Mitigation:** Comprehensive integration tests comparing old vs new output

### Risk: Dependency Issues
**Mitigation:** Pin tree-sitter versions, test on clean environment

### Risk: Breaking Changes for Users
**Mitigation:** Since backward compatibility isn't required, focus on clear documentation

---

## Open Questions

1. **Query Pack Structure:** Should we add a `manifest.json` to query packs to declare metadata (query name, description, target node types)?

2. **Multi-Language Support:** How should we structure the code to easily add TypeScript, Go, etc. later?

3. **Incremental Discovery:** Should we support incremental discovery (only re-parse changed files) for large codebases?

4. **Query Composition:** Should we support query composition (e.g., combining function_def.scm + class_def.scm)?

---

## Appendix A: Query Pack Format

### Directory Structure

```
queries/
└── python/
    └── remora_core/
        ├── __manifest__.json    # Optional: Query pack metadata
        ├── function_def.scm     # Function definitions
        ├── class_def.scm        # Class definitions
        ├── method_def.scm       # Method definitions
        └── file.scm             # File-level nodes
```

### Query File Format

```scheme
;; function_def.scm
;; Captures: function.name, function.body
(function_definition
  name: (identifier) @function.name
  body: (block) @function.body) @function.def
```

### Manifest Format (Optional)

```json
{
  "name": "remora_core",
  "language": "python",
  "version": "1.0.0",
  "queries": [
    {
      "file": "function_def.scm",
      "target": "function",
      "captures": ["function.name", "function.body"]
    }
  ]
}
```

---

## Appendix B: Performance Considerations

### Tree Caching Strategy

- Parse tree stored in LRU cache keyed by file path + mtime
- Cache size: 100 trees (configurable)
- Benefits: Re-query same file without re-parsing

### Parallel Processing

- Use ThreadPoolExecutor for I/O-bound file reading
- Use ProcessPoolExecutor for CPU-bound parsing (if needed)
- Default: 4 workers (configurable)

### Memory Management

- Stream large directories (don't load all files at once)
- Extract only needed capture text (not full source)
- Use generators where possible

---

## Appendix C: Development Commands

```bash
# Setup
uv sync

# Run tests
uv run pytest tests/test_discovery.py -v

# Run specific test
uv run pytest tests/test_discovery.py::test_discovery_returns_expected_nodes -v

# Type check
uv run pyright remora/discovery/

# Lint
uv run ruff check remora/discovery/

# Format
uv run ruff format remora/discovery/

# Performance benchmark
uv run python -m pytest tests/test_discovery.py --benchmark-only
```

---

**Document Version:** 1.0  
**Created:** 2026-02-18  
**Status:** Ready for Implementation
