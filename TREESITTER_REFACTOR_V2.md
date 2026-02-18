# Tree-sitter Refactor V2 — Overview & Development Guide

**Document Version:** 2.0
**Created:** 2026-02-18
**Status:** Ready for Implementation

---

## 1. Executive Summary

Remora's node discovery pipeline currently depends on [pydantree](https://github.com/Bullish-Design/pydantree), which shells out to a `pydantree run-query` CLI command that **was never implemented**. This refactor replaces pydantree entirely with **direct, in-process tree-sitter Python API** calls. The result is a faster, simpler, and fully functional discovery layer.

### What Changes

| Aspect | Before | After |
|---|---|---|
| Discovery engine | `PydantreeDiscoverer` (subprocess) | `TreeSitterDiscoverer` (in-process) |
| Dependencies | `pydantree` (broken) | `tree-sitter` + `tree-sitter-python` |
| CSTNode model | Pydantic `BaseModel` | Frozen `dataclass` |
| Node types | String literals `"file"`, `"class"`, `"function"` | `NodeType` enum: `FILE`, `CLASS`, `FUNCTION`, `METHOD` |
| Query location | Duplicated in `remora/queries/` and `queries/python/remora_core/` | Single location: `remora/queries/python/remora_core/` |
| Backward compat | N/A | **Clean break** — no legacy stubs |

### What Does NOT Change

- The **public API shape**: `discoverer.discover()` still returns `list[CSTNode]`
- The **CSTNode field names**: `node_id`, `text`, `name`, `node_type`, `file_path`, `start_byte`, `end_byte`
- The **config location**: `DiscoveryConfig` stays in `config.py` as a field of `RemoraConfig`
- The **query file format**: `.scm` files using tree-sitter query syntax

---

## 2. Aligned Design Decisions

These decisions were finalized during a clarification session and are **not open for debate** during implementation. If you encounter a situation that seems to conflict with one of these decisions, ask for guidance before deviating.

| # | Topic | Decision | Rationale |
|---|---|---|---|
| 1 | `node_id` / `text` field names | **Keep as-is** | Avoids unnecessary churn across all consumers |
| 2 | Method detection | **Tree-sitter parent inspection** — no new `.scm` files | Walking the parent chain at extraction time is simpler |
| 3 | Async functions | **`FUNCTION` covers both** sync and async | No consumer currently distinguishes them |
| 4 | `full_name` property | **Yes** — walk parent chain at extraction time | Enables qualified names like `Greeter.greet` |
| 5 | Query location | **Inside the package** at `remora/queries/python/remora_core/` | Queries ship with the package |
| 6 | Project-root `queries/` dir | **Delete it** | Eliminates duplication |
| 7 | `file.scm` | **One FILE node per module** (`(module) @file.def`) | Simplifies; old granular captures were unused |
| 8 | `DiscoveryConfig` location | **Stay in `config.py`** | It's a field of `RemoraConfig` |
| 9 | `node_id` hash | **`sha256(file_path:node_type:name)`** | Stable across reformatting |
| 10 | Parallelism | **Not in this refactor** — document where it would go | Keep scope small |
| 11 | `NodeType` enum values | `FILE`, `CLASS`, `FUNCTION`, `METHOD` | |
| 12 | New CSTNode fields | `start_line`, `end_line` added | Free from tree-sitter |
| 13 | Legacy stub | **None** — clean break | No backward compat needed |
| 14 | Tests | **Real tree-sitter** — no subprocess mocking | Tests should exercise real parsing |

---

## 3. Architecture Overview

### Current Architecture (Broken)

```
Source Files (.py)
       ↓
PydantreeDiscoverer
       ↓ subprocess call
pydantree run-query  ← DOES NOT EXIST
       ↓
JSON parsing
       ↓
CSTNode (Pydantic BaseModel)
       ↓
Consumers (analyzer, orchestrator, runner, subagent)
```

### New Architecture

```
Source Files (.py)
       ↓
TreeSitterDiscoverer           ← orchestrates everything
  ├── QueryLoader              ← loads & compiles .scm files
  ├── SourceParser             ← parses .py → tree-sitter Tree
  └── MatchExtractor           ← runs queries, builds CSTNode list
       ↓
CSTNode (frozen dataclass)
       ↓
Consumers (analyzer, orchestrator, runner, subagent)
```

### New Module Structure

```
remora/discovery/              ← NEW package (replaces remora/discovery.py)
├── __init__.py                ← public exports: TreeSitterDiscoverer, CSTNode, etc.
├── models.py                  ← CSTNode, NodeType, Capture, DiscoveryError
├── query_loader.py            ← QueryLoader class
├── source_parser.py           ← SourceParser class
└── match_extractor.py         ← MatchExtractor class
    (discoverer logic lives in __init__.py or a dedicated discoverer.py)
```

---

## 4. CSTNode Model — Before & After

### Current CSTNode (Pydantic BaseModel)

```python
# remora/discovery.py (CURRENT)
class CSTNode(BaseModel):
    node_id: str                                    # sha1(file_path::node_type::name)
    node_type: Literal["file", "class", "function"]
    name: str
    file_path: Path
    start_byte: int
    end_byte: int
    text: str
```

### New CSTNode (Frozen Dataclass)

```python
# remora/discovery/models.py (NEW)
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import hashlib

class NodeType(str, Enum):
    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"

@dataclass(frozen=True)
class CSTNode:
    node_id: str           # sha256(file_path:node_type:name) truncated to 16 hex chars
    node_type: NodeType    # Enum instead of string literal
    name: str              # Required; file stem for FILE nodes
    file_path: Path
    start_byte: int
    end_byte: int
    text: str              # Source text for the matched region
    start_line: int        # NEW — 1-indexed line number
    end_line: int          # NEW — 1-indexed line number

    @property
    def full_name(self) -> str:
        """Qualified name including parent class.
        Returns 'ClassName.method_name' for methods, just 'name' otherwise.
        Built at extraction time by walking the tree-sitter parent chain.
        This property returns a stored value set during construction.
        """
        return self._full_name

    def __init__(self, *, node_id, node_type, name, file_path,
                 start_byte, end_byte, text, start_line, end_line,
                 full_name: str | None = None):
        # Use object.__setattr__ because the dataclass is frozen
        object.__setattr__(self, 'node_id', node_id)
        object.__setattr__(self, 'node_type', node_type)
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'file_path', file_path)
        object.__setattr__(self, 'start_byte', start_byte)
        object.__setattr__(self, 'end_byte', end_byte)
        object.__setattr__(self, 'text', text)
        object.__setattr__(self, 'start_line', start_line)
        object.__setattr__(self, 'end_line', end_line)
        object.__setattr__(self, '_full_name', full_name or name)
```

> **Note on `full_name`:** The `full_name` is computed during extraction (Step 3) by examining the tree-sitter parent chain. It is stored as `_full_name` on the frozen dataclass instance. For a method `greet` inside class `Greeter`, `full_name` returns `"Greeter.greet"`. For top-level functions and classes, it returns the plain `name`.

### `node_id` Hashing

```python
def compute_node_id(file_path: Path, node_type: NodeType, name: str) -> str:
    """Stable hash: sha256(resolved_file_path:node_type_value:name), truncated to 16 hex chars."""
    digest_input = f"{file_path.resolve()}:{node_type.value}:{name}".encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()[:16]
```

**Key difference from current code:** Uses `sha256` (not `sha1`), uses `:` separator (not `::`), and truncates to 16 hex chars for readability. The hash does **not** include `start_byte`, so IDs are stable across reformatting.

---

## 5. Complete File Impact Map

Every file that needs to change, grouped by action:

### Files to CREATE

| File | Purpose |
|---|---|
| `remora/discovery/__init__.py` | Public exports (`TreeSitterDiscoverer`, `CSTNode`, `NodeType`, `DiscoveryError`) |
| `remora/discovery/models.py` | `CSTNode`, `NodeType`, `DiscoveryError`, `compute_node_id()` |
| `remora/discovery/query_loader.py` | `QueryLoader` — loads `.scm` files, compiles tree-sitter queries |
| `remora/discovery/source_parser.py` | `SourceParser` — parses `.py` files into tree-sitter Trees |
| `remora/discovery/match_extractor.py` | `MatchExtractor` — executes queries, builds `CSTNode` list |
| `remora/queries/python/remora_core/function_def.scm` | Rewritten: unified sync/async captures |
| `remora/queries/python/remora_core/file.scm` | Rewritten: single `(module) @file.def` |
| `tests/test_discovery.py` | Complete rewrite with real tree-sitter |
| `tests/fixtures/edge_cases.py` | New fixture: nested classes, async, decorators, etc. |
| `tests/fixtures/invalid_syntax.py` | New fixture: intentionally broken Python |
| `tests/roundtrip/` | New round-trip test harness directory |

### Files to MODIFY

| File | What Changes |
|---|---|
| `pyproject.toml` | Remove `pydantree`; add `tree-sitter>=0.24`, `tree-sitter-python>=0.23` |
| `remora/config.py` | Add `query_dir: Path` to `DiscoveryConfig` |
| `remora/errors.py` | Add new error codes (`DISC_003` for query syntax, `DISC_004` for parse errors) |
| `remora/analyzer.py` | Update import path; replace `PydantreeDiscoverer` → `TreeSitterDiscoverer` |
| `remora/orchestrator.py` | Update import path |
| `remora/runner.py` | Update import path |
| `remora/subagent.py` | Update import path; update Jinja2 template to handle `NodeType` enum |
| `remora/__init__.py` | Update import path |
| `scripts/remora_demo.py` | Update import path; replace `PydantreeDiscoverer` → `TreeSitterDiscoverer` |
| `tests/test_runner.py` | Update `_make_node()` to include `start_line`, `end_line`, use `NodeType` |
| `tests/test_orchestrator.py` | Update `_make_node()` same as above |
| `tests/test_subagent.py` | Update `CSTNode` construction |
| `tests/integration/test_runner_*.py` | Update `CSTNode` construction (4 files) |
| `tests/conftest.py` | Update if it references discovery |
| `remora/queries/python/remora_core/class_def.scm` | Keep as-is (already correct) |

### Files to DELETE

| File | Reason |
|---|---|
| `remora/discovery.py` | Replaced by `remora/discovery/` package |
| `queries/` (entire directory at project root) | Duplicates `remora/queries/`; queries belong inside the package |
| `remora/queries/class_def.scm` | Old flat query location; replaced by `remora/queries/python/remora_core/` |
| `remora/queries/file.scm` | Same as above |
| `remora/queries/function_def.scm` | Same as above |

### Documentation to UPDATE

| File | What Changes |
|---|---|
| `docs/ARCHITECTURE.md` | Update discovery pipeline description |
| `docs/SPEC.md` | Update discovery-related specs |
| `README.md` | Update any pydantree references |

---

## 6. Step-by-Step Implementation Plan

### Prerequisites

Before starting, make sure you can run the existing test suite:

```bash
uv run pytest tests/ -x -q
```

Some tests may already fail due to pydantree being broken — that's expected. The goal is to **not break anything that currently works** during the refactor.

---

### Step 1: Update Dependencies & Create Package Skeleton

**Goal:** Swap out pydantree for tree-sitter in `pyproject.toml`, create the new `remora/discovery/` package directory, and verify the environment resolves.

#### 1.1 Update `pyproject.toml`

Make these changes:

```diff
 dependencies = [
   "typer>=0.12",
   "rich>=13",
   "pydantic>=2",
   "pyyaml>=6",
   "jinja2>=3",
   "watchfiles>=0.21",
   "openai>=1.0",
   "cairn",
-  "pydantree",
-  # pydantree and cairn added as local or VCS dependencies
+  "tree-sitter>=0.24",
+  "tree-sitter-python>=0.23",
+  # cairn added as local or VCS dependency
 ]

 [tool.uv.sources]
 fsdantic = { git = "https://github.com/Bullish-Design/fsdantic.git" }
 grail = { git = "https://github.com/Bullish-Design/grail.git" }
 cairn = { git = "https://github.com/Bullish-Design/cairn.git" }
-pydantree = { git = "https://github.com/Bullish-Design/pydantree.git" }
```

#### 1.2 Create the package directory skeleton

Create these **empty** files (we'll fill them in later steps):

```
remora/discovery/__init__.py   ← just "pass" for now
remora/discovery/models.py     ← just "pass" for now
remora/discovery/query_loader.py  ← just "pass" for now
remora/discovery/source_parser.py ← just "pass" for now
remora/discovery/match_extractor.py ← just "pass" for now
```

> **Important:** Do NOT delete `remora/discovery.py` yet. The old file must remain importable until Step 5 when we cut over all consumers.

#### 1.3 Run `uv sync`

```bash
uv sync
```

#### 1.4 Verify tree-sitter installs correctly

```bash
uv run python -c "import tree_sitter; import tree_sitter_python; print('OK')"
```

#### Verification Checklist — Step 1

- [ ] `uv sync` completes without errors
- [ ] `uv run python -c "import tree_sitter; import tree_sitter_python; print('OK')"` prints `OK`
- [ ] `remora/discovery/` directory exists with 5 stub files
- [ ] `remora/discovery.py` (the old file) is still present and importable
- [ ] Existing tests that don't depend on pydantree still pass

---

### Step 2: Implement Core Models (`models.py`)

**Goal:** Define `NodeType`, `CSTNode`, `DiscoveryError`, and helper functions in `remora/discovery/models.py`.

#### 2.1 Write `remora/discovery/models.py`

```python
"""Core data models for the tree-sitter discovery pipeline."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class NodeType(str, Enum):
    """Type of discovered code node."""
    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"


class DiscoveryError(RuntimeError):
    """Base exception for discovery errors."""
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def compute_node_id(file_path: Path, node_type: NodeType, name: str) -> str:
    """Compute a stable node ID.

    Hash: sha256(resolved_file_path:node_type_value:name), truncated to 16 hex chars.
    Stable across reformatting because it does NOT include byte offsets.
    """
    digest_input = f"{file_path.resolve()}:{node_type.value}:{name}".encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()[:16]


@dataclass(frozen=True)
class CSTNode:
    """A discovered code node (file, class, function, or method).

    This is a frozen dataclass — instances are immutable after creation.
    The `full_name` property returns a qualified name like 'ClassName.method_name'.
    """
    node_id: str
    node_type: NodeType
    name: str
    file_path: Path
    start_byte: int
    end_byte: int
    text: str
    start_line: int
    end_line: int
    _full_name: str = ""  # Set via __post_init__ or factory; hidden from repr

    def __post_init__(self) -> None:
        if not self._full_name:
            object.__setattr__(self, "_full_name", self.name)

    @property
    def full_name(self) -> str:
        """Qualified name including parent class, e.g. 'Greeter.greet'."""
        return self._full_name
```

> **Design note:** `_full_name` is a dataclass field with a default so that callers can omit it for simple cases (tests, FILE nodes). The `__post_init__` ensures it falls back to `name`.

#### 2.2 Update `remora/errors.py`

Add two new error codes:

```python
# ... existing codes ...
DISC_003 = "DISC_003"  # Query syntax error
DISC_004 = "DISC_004"  # Source file parse error
```

#### 2.3 Update `remora/discovery/__init__.py`

```python
"""Tree-sitter backed node discovery for Remora."""

from remora.discovery.models import CSTNode, DiscoveryError, NodeType, compute_node_id

__all__ = [
    "CSTNode",
    "DiscoveryError",
    "NodeType",
    "compute_node_id",
]
```

> **Note:** We'll add `TreeSitterDiscoverer` to the exports in Step 4 after it's implemented.

#### Verification Checklist — Step 2

- [ ] `uv run python -c "from remora.discovery.models import CSTNode, NodeType, DiscoveryError, compute_node_id; print('OK')"`
- [ ] Create a CSTNode in a Python REPL and verify all fields:
  ```python
  from remora.discovery.models import CSTNode, NodeType
  from pathlib import Path
  node = CSTNode(
      node_id="abc123", node_type=NodeType.FUNCTION, name="hello",
      file_path=Path("test.py"), start_byte=0, end_byte=10,
      text="def hello(): ...", start_line=1, end_line=1,
  )
  assert node.full_name == "hello"
  assert node.node_type == NodeType.FUNCTION
  assert node.node_type == "function"  # str(Enum) comparison works
  ```
- [ ] Verify `compute_node_id` is deterministic:
  ```python
  from remora.discovery.models import compute_node_id, NodeType
  from pathlib import Path
  id1 = compute_node_id(Path("test.py"), NodeType.FUNCTION, "hello")
  id2 = compute_node_id(Path("test.py"), NodeType.FUNCTION, "hello")
  assert id1 == id2
  assert len(id1) == 16
  ```
- [ ] Verify frozen dataclass: `node.name = "foo"` raises `FrozenInstanceError`
- [ ] `NodeType("function") == NodeType.FUNCTION` → `True`

---

### Step 3: Implement Source Parser (`source_parser.py`)

**Goal:** Build a class that parses Python source files into tree-sitter `Tree` objects. This is the simplest component and has no dependency on queries.

#### 3.1 Write `remora/discovery/source_parser.py`

```python
"""Source file parsing using tree-sitter."""

from __future__ import annotations

import logging
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Tree

from remora.discovery.models import DiscoveryError
from remora.errors import DISC_004

logger = logging.getLogger(__name__)

PY_LANGUAGE = Language(tspython.language())


class SourceParser:
    """Parses Python source files into tree-sitter Trees.

    Usage:
        parser = SourceParser()
        tree, source_bytes = parser.parse_file(Path("example.py"))
        # tree is a tree_sitter.Tree
        # source_bytes is the raw file content as bytes
    """

    def __init__(self) -> None:
        self._parser = Parser(PY_LANGUAGE)

    def parse_file(self, file_path: Path) -> tuple[Tree, bytes]:
        """Parse a Python file and return (tree, source_bytes).

        Args:
            file_path: Path to a .py file.

        Returns:
            Tuple of (parsed Tree, raw source bytes).

        Raises:
            DiscoveryError: If the file cannot be read.
        """
        resolved = file_path.resolve()
        try:
            source_bytes = resolved.read_bytes()
        except OSError as exc:
            raise DiscoveryError(
                DISC_004, f"Failed to read source file: {resolved}"
            ) from exc

        tree = self._parser.parse(source_bytes)
        if tree.root_node.has_error:
            logger.warning("Parse errors in %s (continuing with partial tree)", resolved)

        return tree, source_bytes

    def parse_bytes(self, source_bytes: bytes) -> Tree:
        """Parse raw bytes and return a tree-sitter Tree.

        Useful for testing without writing to disk.
        """
        return self._parser.parse(source_bytes)
```

> **Design note:** tree-sitter is **error-tolerant** — it always produces a tree even for invalid syntax. We log a warning but don't raise. The `has_error` check on the root node detects if any `ERROR` nodes exist in the tree.

> **Where parallelism would go:** If you later need to parse many files in parallel, wrap calls to `parse_file` in a `ThreadPoolExecutor`. The `Parser` is NOT thread-safe, so each thread would need its own `SourceParser` instance. A factory function like `create_parser()` could be used to create per-thread instances.

#### Verification Checklist — Step 3

- [ ] Parse the existing fixture file:
  ```python
  from remora.discovery.source_parser import SourceParser
  from pathlib import Path

  parser = SourceParser()
  tree, source = parser.parse_file(Path("tests/fixtures/sample.py"))
  print(tree.root_node.type)       # Should print "module"
  print(tree.root_node.child_count)  # Should be > 0
  print(len(source))               # Should match file size
  ```
- [ ] Parse invalid syntax without crashing:
  ```python
  parser = SourceParser()
  tree = parser.parse_bytes(b"def broken(:\n  pass")
  assert tree.root_node.has_error  # True — partial parse
  ```
- [ ] `parse_file` on non-existent path raises `DiscoveryError` with code `DISC_004`

---

### Step 4: Implement Query Loader (`query_loader.py`)

**Goal:** Build a class that discovers `.scm` files from a query pack directory and compiles them into tree-sitter `Query` objects.

#### 4.1 Write `remora/discovery/query_loader.py`

```python
"""Query loading and compilation for tree-sitter."""

from __future__ import annotations

import logging
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Query

from remora.discovery.models import DiscoveryError
from remora.errors import DISC_001, DISC_003

logger = logging.getLogger(__name__)

PY_LANGUAGE = Language(tspython.language())


class CompiledQuery:
    """A compiled tree-sitter query with metadata."""

    def __init__(self, query: Query, source_file: Path, query_text: str) -> None:
        self.query = query
        self.source_file = source_file
        self.query_text = query_text

    @property
    def name(self) -> str:
        """Query name derived from filename (e.g. 'function_def' from 'function_def.scm')."""
        return self.source_file.stem


class QueryLoader:
    """Loads and compiles tree-sitter queries from .scm files.

    Usage:
        loader = QueryLoader()
        queries = loader.load_query_pack(
            query_dir=Path("remora/queries"),
            language="python",
            query_pack="remora_core",
        )
        # queries is a list of CompiledQuery objects
    """

    def load_query_pack(
        self,
        query_dir: Path,
        language: str,
        query_pack: str,
    ) -> list[CompiledQuery]:
        """Load all .scm files from a query pack directory.

        Args:
            query_dir: Root query directory (e.g. remora/queries/).
            language: Language subdirectory (e.g. "python").
            query_pack: Query pack subdirectory (e.g. "remora_core").

        Returns:
            List of compiled queries.

        Raises:
            DiscoveryError: If query pack directory doesn't exist or a query has syntax errors.
        """
        pack_dir = query_dir / language / query_pack
        if not pack_dir.is_dir():
            raise DiscoveryError(
                DISC_001,
                f"Query pack directory not found: {pack_dir}",
            )

        scm_files = sorted(pack_dir.glob("*.scm"))
        if not scm_files:
            raise DiscoveryError(
                DISC_001,
                f"No .scm query files found in: {pack_dir}",
            )

        compiled: list[CompiledQuery] = []
        for scm_file in scm_files:
            compiled.append(self._compile_query(scm_file))

        logger.info(
            "Loaded %d queries from %s/%s: %s",
            len(compiled),
            language,
            query_pack,
            [q.name for q in compiled],
        )
        return compiled

    def _compile_query(self, scm_file: Path) -> CompiledQuery:
        """Compile a single .scm file into a tree-sitter Query."""
        try:
            query_text = scm_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise DiscoveryError(
                DISC_003,
                f"Failed to read query file: {scm_file}",
            ) from exc

        try:
            query = PY_LANGUAGE.query(query_text)
        except Exception as exc:
            raise DiscoveryError(
                DISC_003,
                f"Query syntax error in {scm_file.name}: {exc}",
            ) from exc

        return CompiledQuery(query=query, source_file=scm_file, query_text=query_text)
```

#### 4.2 Update the query `.scm` files

The queries in `remora/queries/python/remora_core/` need to be updated to match our decisions.

**`remora/queries/python/remora_core/file.scm`** — Simplify to one FILE node per module:

```scheme
; Capture one FILE node per module
(module) @file.def
```

> This is already the content in the project-root `queries/python/remora_core/file.scm`. The version in `remora/queries/file.scm` (flat location) is the old granular version — we'll delete that in Step 6.

**`remora/queries/python/remora_core/function_def.scm`** — Unify sync/async captures:

```scheme
; Capture all function definitions (sync and async)
(function_definition
  name: (identifier) @function.name
) @function.def
```

> This removes the separate `@async_function.name` / `@async_function.def` captures. Method vs. function distinction is handled by parent inspection in the `MatchExtractor`, not by the query.

**`remora/queries/python/remora_core/class_def.scm`** — Keep as-is:

```scheme
; Capture class definitions
(class_definition
  name: (identifier) @class.name
  body: (block) @class.body
) @class.def
```

#### Verification Checklist — Step 4

- [ ] Load the query pack successfully:
  ```python
  from remora.discovery.query_loader import QueryLoader
  from pathlib import Path

  loader = QueryLoader()
  queries = loader.load_query_pack(
      query_dir=Path("remora/queries"),
      language="python",
      query_pack="remora_core",
  )
  print([q.name for q in queries])
  # Should print: ['class_def', 'file', 'function_def']
  assert len(queries) == 3
  ```
- [ ] Non-existent pack raises `DiscoveryError` with code `DISC_001`
- [ ] Verify that a broken `.scm` file raises `DiscoveryError` with code `DISC_003` (temporarily create a bad `.scm` file to test, then delete it)
- [ ] Run queries against a parsed tree to confirm they compile correctly:
  ```python
  from remora.discovery.source_parser import SourceParser
  parser = SourceParser()
  tree, source = parser.parse_file(Path("tests/fixtures/sample.py"))
  for q in queries:
      matches = q.query.matches(tree.root_node)
      print(f"{q.name}: {len(matches)} matches")
  # Expected: class_def: 1, file: 1, function_def: 2 (greet + add)
  ```

---

### Step 5: Implement Match Extractor (`match_extractor.py`)

**Goal:** Build the component that executes compiled queries against parsed trees and constructs `CSTNode` instances. This is the most complex component because it handles:
- Extracting capture names and mapping them to node types
- Detecting METHOD vs. FUNCTION by inspecting tree-sitter parent nodes
- Computing `full_name` by walking the parent chain
- Deduplicating overlapping matches

#### 5.1 Understanding tree-sitter query matches

When you run a tree-sitter query, each match returns a **pattern index** and a dictionary of **captures**. For example, with `class_def.scm`:

```
(class_definition
  name: (identifier) @class.name
  body: (block) @class.body
) @class.def
```

A match produces captures like:
- `"class.name"` → the `identifier` node (e.g., text = `"Greeter"`)
- `"class.body"` → the `block` node
- `"class.def"` → the entire `class_definition` node

Our convention:
- `@X.name` → extract the node's `name` from this capture's text
- `@X.def` → extract the node's byte range and source text from this capture
- The prefix `X` determines the base `NodeType` (`function` → `FUNCTION`, `class` → `CLASS`, `file` → `FILE`)

#### 5.2 Write `remora/discovery/match_extractor.py`

```python
"""Match extraction and CSTNode construction from tree-sitter queries."""

from __future__ import annotations

import logging
from pathlib import Path

from tree_sitter import Node, Tree

from remora.discovery.models import CSTNode, NodeType, compute_node_id
from remora.discovery.query_loader import CompiledQuery

logger = logging.getLogger(__name__)

# Map capture-name prefixes to base NodeType.
_PREFIX_TO_NODE_TYPE: dict[str, NodeType] = {
    "file": NodeType.FILE,
    "class": NodeType.CLASS,
    "function": NodeType.FUNCTION,
}


class MatchExtractor:
    """Executes compiled queries against parsed trees and builds CSTNode lists.

    Usage:
        extractor = MatchExtractor()
        nodes = extractor.extract(
            file_path=Path("example.py"),
            tree=tree,
            source_bytes=source_bytes,
            queries=[compiled_query_1, compiled_query_2],
        )
    """

    def extract(
        self,
        file_path: Path,
        tree: Tree,
        source_bytes: bytes,
        queries: list[CompiledQuery],
    ) -> list[CSTNode]:
        """Run all queries against a tree and return discovered CSTNodes.

        Args:
            file_path: Path to the source file (for node_id and file_path fields).
            tree: Parsed tree-sitter tree.
            source_bytes: Raw source bytes (for text extraction).
            queries: List of compiled queries to execute.

        Returns:
            Deduplicated, sorted list of CSTNode instances.
        """
        nodes: list[CSTNode] = []
        seen_ids: set[str] = set()

        for compiled_query in queries:
            new_nodes = self._run_query(file_path, tree, source_bytes, compiled_query)
            for node in new_nodes:
                if node.node_id not in seen_ids:
                    seen_ids.add(node.node_id)
                    nodes.append(node)

        nodes.sort(key=lambda n: (str(n.file_path), n.start_byte, n.node_type.value, n.name))
        return nodes

    def _run_query(
        self,
        file_path: Path,
        tree: Tree,
        source_bytes: bytes,
        compiled_query: CompiledQuery,
    ) -> list[CSTNode]:
        """Run a single query and extract CSTNodes from matches."""
        matches = compiled_query.query.matches(tree.root_node)
        nodes: list[CSTNode] = []

        for _pattern_index, captures_dict in matches:
            node = self._build_node_from_captures(file_path, source_bytes, captures_dict)
            if node is not None:
                nodes.append(node)

        return nodes

    def _build_node_from_captures(
        self,
        file_path: Path,
        source_bytes: bytes,
        captures_dict: dict[str, list[Node]],
    ) -> CSTNode | None:
        """Build a CSTNode from a single match's captures dictionary.

        The captures_dict maps capture names (e.g. "class.name", "class.def")
        to lists of tree-sitter Node objects.
        """
        # Find the .def capture to get the overall node span
        def_node: Node | None = None
        name_text: str | None = None
        base_type: NodeType | None = None

        for capture_name, ts_nodes in captures_dict.items():
            if not ts_nodes:
                continue
            ts_node = ts_nodes[0]  # Take first node in capture list

            parts = capture_name.split(".")
            if len(parts) != 2:
                continue
            prefix, suffix = parts

            if suffix == "def":
                def_node = ts_node
                base_type = _PREFIX_TO_NODE_TYPE.get(prefix)
            elif suffix == "name":
                name_text = source_bytes[ts_node.start_byte:ts_node.end_byte].decode(
                    "utf-8", errors="replace"
                )
                if base_type is None:
                    base_type = _PREFIX_TO_NODE_TYPE.get(prefix)

        if def_node is None or base_type is None:
            return None

        # For FILE nodes, use file stem as name
        if base_type == NodeType.FILE:
            name_text = file_path.stem

        if name_text is None:
            name_text = "unknown"

        # Determine if a FUNCTION is actually a METHOD by inspecting parents
        actual_type = base_type
        full_name = name_text
        if base_type == NodeType.FUNCTION:
            actual_type, full_name = self._classify_function(
                def_node, name_text, source_bytes
            )

        text = source_bytes[def_node.start_byte:def_node.end_byte].decode(
            "utf-8", errors="replace"
        )

        node_id = compute_node_id(file_path, actual_type, name_text)

        return CSTNode(
            node_id=node_id,
            node_type=actual_type,
            name=name_text,
            file_path=file_path,
            start_byte=def_node.start_byte,
            end_byte=def_node.end_byte,
            text=text,
            start_line=def_node.start_point.row + 1,   # tree-sitter is 0-indexed
            end_line=def_node.end_point.row + 1,
            _full_name=full_name,
        )

    def _classify_function(
        self,
        def_node: Node,
        name: str,
        source_bytes: bytes,
    ) -> tuple[NodeType, str]:
        """Determine if a function_definition is a METHOD or FUNCTION.

        Walk the tree-sitter parent chain. If any ancestor is a class_definition,
        this is a METHOD and we build a qualified full_name.

        Returns:
            Tuple of (NodeType, full_name).
        """
        parent = def_node.parent
        while parent is not None:
            if parent.type == "class_definition":
                # Extract the class name
                class_name_node = parent.child_by_field_name("name")
                if class_name_node is not None:
                    class_name = source_bytes[
                        class_name_node.start_byte:class_name_node.end_byte
                    ].decode("utf-8", errors="replace")
                    return NodeType.METHOD, f"{class_name}.{name}"
                return NodeType.METHOD, name
            parent = parent.parent

        return NodeType.FUNCTION, name
```

> **Key behaviors:**
> - `_classify_function` walks up the tree-sitter parent chain. If it finds a `class_definition` ancestor, the function is classified as `METHOD` and `full_name` becomes `ClassName.method_name`.
> - Deduplication uses `node_id` (which is a hash of `file_path:node_type:name`). If two queries match the same node, only the first is kept.
> - Sorting matches the current `PydantreeDiscoverer.discover()` sort order: `(file_path, start_byte, node_type, name)`.

#### Verification Checklist — Step 5

- [ ] End-to-end extraction on `tests/fixtures/sample.py`:
  ```python
  from remora.discovery.source_parser import SourceParser
  from remora.discovery.query_loader import QueryLoader
  from remora.discovery.match_extractor import MatchExtractor
  from pathlib import Path

  parser = SourceParser()
  loader = QueryLoader()
  extractor = MatchExtractor()

  tree, source = parser.parse_file(Path("tests/fixtures/sample.py"))
  queries = loader.load_query_pack(Path("remora/queries"), "python", "remora_core")
  nodes = extractor.extract(Path("tests/fixtures/sample.py"), tree, source, queries)

  for n in nodes:
      print(f"{n.node_type.value:8s} {n.full_name:20s} L{n.start_line}-{n.end_line}")

  # Expected output (order may vary by sort):
  # file     sample               L1-8
  # class    Greeter               L1-3
  # method   Greeter.greet         L2-3
  # function add                   L6-7
  ```
- [ ] Verify `greet` is classified as `METHOD` (not `FUNCTION`)
- [ ] Verify `add` is classified as `FUNCTION`
- [ ] Verify `full_name` for `greet` is `"Greeter.greet"`
- [ ] Verify `node_id` values are stable (re-run and compare)
- [ ] Verify nodes are sorted by `(file_path, start_byte, node_type, name)`

---

### Step 6: Build the TreeSitterDiscoverer & Wire Up Exports

**Goal:** Create the top-level discoverer class that ties SourceParser + QueryLoader + MatchExtractor together, then export it from `remora/discovery/__init__.py`.

#### 6.1 Add `TreeSitterDiscoverer` to `remora/discovery/__init__.py`

Replace the stub `__init__.py` with the full discoverer implementation. The discoverer is small enough to live directly in `__init__.py` rather than a separate file.

```python
"""Tree-sitter backed node discovery for Remora."""

from __future__ import annotations

import importlib.resources
import logging
import time
from pathlib import Path
from typing import Iterable

from remora.discovery.match_extractor import MatchExtractor
from remora.discovery.models import CSTNode, DiscoveryError, NodeType, compute_node_id
from remora.discovery.query_loader import CompiledQuery, QueryLoader
from remora.discovery.source_parser import SourceParser
from remora.events import EventEmitter

logger = logging.getLogger(__name__)


def _default_query_dir() -> Path:
    """Return the built-in query directory inside the remora package."""
    return Path(importlib.resources.files("remora")) / "queries"  # type: ignore[arg-type]


class TreeSitterDiscoverer:
    """Discovers code nodes by parsing Python files with tree-sitter.

    Usage:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[Path("./src")],
            language="python",
            query_pack="remora_core",
        )
        nodes = discoverer.discover()
    """

    def __init__(
        self,
        root_dirs: Iterable[Path],
        language: str,
        query_pack: str,
        *,
        query_dir: Path | None = None,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        self.root_dirs = [Path(p).resolve() for p in root_dirs]
        self.language = language
        self.query_pack = query_pack
        self.query_dir = query_dir or _default_query_dir()
        self.event_emitter = event_emitter

        self._parser = SourceParser()
        self._loader = QueryLoader()
        self._extractor = MatchExtractor()

    def discover(self) -> list[CSTNode]:
        """Walk root_dirs, parse .py files, run queries, return CSTNodes.

        Emits a discovery event with timing if an event_emitter is set.
        """
        start = time.monotonic()
        status = "ok"
        try:
            queries = self._loader.load_query_pack(
                self.query_dir, self.language, self.query_pack
            )
            py_files = self._collect_files()
            all_nodes: list[CSTNode] = []
            for file_path in py_files:
                try:
                    tree, source_bytes = self._parser.parse_file(file_path)
                    nodes = self._extractor.extract(
                        file_path, tree, source_bytes, queries
                    )
                    all_nodes.extend(nodes)
                except DiscoveryError:
                    logger.warning("Skipping %s due to parse error", file_path)
                    continue
            all_nodes.sort(
                key=lambda n: (str(n.file_path), n.start_byte, n.node_type.value, n.name)
            )
            return all_nodes
        except Exception:
            status = "error"
            raise
        finally:
            if self.event_emitter is not None:
                duration_ms = int((time.monotonic() - start) * 1000)
                self.event_emitter.emit(
                    {
                        "event": "discovery",
                        "phase": "discovery",
                        "status": status,
                        "duration_ms": duration_ms,
                    }
                )

    def _collect_files(self) -> list[Path]:
        """Walk root_dirs and collect all .py files."""
        files: list[Path] = []
        for root in self.root_dirs:
            if root.is_file() and root.suffix == ".py":
                files.append(root)
            elif root.is_dir():
                files.extend(sorted(root.rglob("*.py")))
        return files


__all__ = [
    "CSTNode",
    "CompiledQuery",
    "DiscoveryError",
    "MatchExtractor",
    "NodeType",
    "QueryLoader",
    "SourceParser",
    "TreeSitterDiscoverer",
    "compute_node_id",
]
```

#### Verification Checklist — Step 6

- [ ] End-to-end discovery on fixtures:
  ```python
  from remora.discovery import TreeSitterDiscoverer
  from pathlib import Path

  discoverer = TreeSitterDiscoverer(
      root_dirs=[Path("tests/fixtures")],
      language="python",
      query_pack="remora_core",
  )
  nodes = discoverer.discover()
  for n in nodes:
      print(f"{n.node_type.value:8s} {n.full_name:20s} L{n.start_line}-{n.end_line}  {n.file_path.name}")
  assert len(nodes) >= 4  # file, class, method, function from sample.py
  ```
- [ ] Discovery on a non-existent directory raises no crash (returns empty list)
- [ ] Discovery on a single file:
  ```python
  discoverer = TreeSitterDiscoverer(
      root_dirs=[Path("tests/fixtures/sample.py")],
      language="python",
      query_pack="remora_core",
  )
  nodes = discoverer.discover()
  assert any(n.name == "Greeter" for n in nodes)
  ```
- [ ] Event emitter receives a discovery event when provided

---

### Step 7: Update All Consumers (The Cutover)

**Goal:** Update every file that imports from `remora.discovery` or references `PydantreeDiscoverer` / `CSTNode`. After this step, the old `remora/discovery.py` is no longer imported by anything.

> **Important:** Do all of these changes together as a single commit. Do NOT try to do a "gradual" cutover — since we're doing a clean break, update everything at once.

#### 7.1 Update `remora/config.py`

Add `query_dir` to `DiscoveryConfig`:

```python
class DiscoveryConfig(BaseModel):
    language: str = "python"
    query_pack: str = "remora_core"
    query_dir: Path | None = None  # None = use built-in queries inside the package
```

> `None` means "use the default built-in query directory". This can be overridden in `remora.yaml` for custom query packs.

#### 7.2 Update `remora/analyzer.py`

```diff
-from remora.discovery import CSTNode, PydantreeDiscoverer
+from remora.discovery import CSTNode, TreeSitterDiscoverer
```

And in the `analyze` method:

```diff
-        # Discover nodes using Pydantree
-        discoverer = PydantreeDiscoverer(
-            root_dirs=paths,
-            language=self.config.discovery.language,
-            query_pack=self.config.discovery.query_pack,
-            event_emitter=self._event_emitter,
-        )
+        # Discover nodes using tree-sitter
+        discoverer = TreeSitterDiscoverer(
+            root_dirs=paths,
+            language=self.config.discovery.language,
+            query_pack=self.config.discovery.query_pack,
+            query_dir=self.config.discovery.query_dir,
+            event_emitter=self._event_emitter,
+        )
```

#### 7.3 Update `remora/orchestrator.py`

```diff
-from remora.discovery import CSTNode
+from remora.discovery import CSTNode
```

> The import path stays the same since the new `remora/discovery/__init__.py` exports `CSTNode`. No code changes needed beyond verifying the import works.

#### 7.4 Update `remora/runner.py`

```diff
-from remora.discovery import CSTNode
+from remora.discovery import CSTNode
```

> Same — import path unchanged. The `CSTNode` fields used by runner (`node_id`, `text`, `name`, `node_type`, `file_path`) all exist on the new model.

**However**, the Jinja2 template rendering in `subagent.py` passes `node_type` to a template. Since `node_type` is now a `NodeType` enum, we need to verify this still works:

- `node.node_type` is a `NodeType` which inherits from `str`, so `{{ node_type }}` in Jinja2 will render as `"function"`, `"method"`, etc.
- **No code change needed** — `str(NodeType.FUNCTION)` == `"NodeType.FUNCTION"` but since `NodeType(str, Enum)`, the `.value` is what Jinja2 uses. **Actually, verify this.**

#### 7.5 Update `remora/subagent.py`

The `InitialContext.render()` method passes `node.node_type` to a Jinja2 template:

```python
def render(self, node: CSTNode) -> str:
    template = jinja2.Template(self.node_context)
    return template.render(
        node_text=node.text,
        node_name=node.name,
        node_type=node.node_type,  # This is now a NodeType enum
        file_path=str(node.file_path),
    )
```

Since `NodeType` inherits from `str`, Jinja2 will render it as the string value (e.g., `"function"`). **Test this to be sure.** If Jinja2 renders it as `"NodeType.FUNCTION"` instead, change the line to:

```python
        node_type=node.node_type.value,  # Explicit .value to get "function"
```

Update the import:

```diff
-from remora.discovery import CSTNode
+from remora.discovery import CSTNode
```

> Import path unchanged.

#### 7.6 Update `remora/__init__.py`

```diff
-from remora.discovery import CSTNode
+from remora.discovery import CSTNode, NodeType, TreeSitterDiscoverer
```

Add to `__all__`:

```python
__all__ = [
    "RemoraAnalyzer",
    "ResultPresenter",
    "WorkspaceState",
    "RemoraConfig",
    "load_config",
    "CSTNode",
    "NodeType",               # NEW
    "TreeSitterDiscoverer",   # NEW
    "AgentResult",
    "AnalysisResults",
    "NodeResult",
]
```

#### 7.7 Update `scripts/remora_demo.py`

```diff
-from remora.discovery import CSTNode, PydantreeDiscoverer
+from remora.discovery import CSTNode, TreeSitterDiscoverer
```

Update `_collect_nodes`:

```diff
 def _collect_nodes(config: RemoraConfig, demo_root: Path, event_emitter=None) -> list[CSTNode]:
-    discoverer = PydantreeDiscoverer(
-        [demo_root],
-        config.discovery.language,
-        config.discovery.query_pack,
+    discoverer = TreeSitterDiscoverer(
+        root_dirs=[demo_root],
+        language=config.discovery.language,
+        query_pack=config.discovery.query_pack,
+        query_dir=config.discovery.query_dir,
         event_emitter=event_emitter,
     )
     return discoverer.discover()
```

#### 7.8 Delete the old discovery module

```bash
# After all imports are updated:
rm remora/discovery.py
```

> **Critical check:** After deleting, run `uv run python -c "from remora.discovery import CSTNode, TreeSitterDiscoverer; print('OK')"` to confirm the new package is being resolved.

#### 7.9 Update test files

Every test file that constructs a `CSTNode` needs to be updated because the new model requires `start_line` and `end_line` fields and uses `NodeType` enum.

**Pattern for updating `_make_node()` helpers** (used in `test_runner.py`, `test_orchestrator.py`, integration tests):

```python
# BEFORE:
from remora.discovery import CSTNode

def _make_node() -> CSTNode:
    return CSTNode(
        node_id="node-1",
        node_type="function",
        name="hello",
        file_path=Path("src/example.py"),
        start_byte=0,
        end_byte=10,
        text="def hello(): ...",
    )

# AFTER:
from remora.discovery import CSTNode, NodeType

def _make_node() -> CSTNode:
    return CSTNode(
        node_id="node-1",
        node_type=NodeType.FUNCTION,
        name="hello",
        file_path=Path("src/example.py"),
        start_byte=0,
        end_byte=10,
        text="def hello(): ...",
        start_line=1,
        end_line=1,
    )
```

**Files requiring this update:**
- `tests/test_runner.py` — `_make_node()` on line 162
- `tests/test_orchestrator.py` — `_make_node()` on line 22
- `tests/test_subagent.py` — CSTNode construction around line 113
- `tests/integration/test_runner_test.py` — `_function_node()` on line 29
- `tests/integration/test_runner_lint.py` — CSTNode construction on line 31
- `tests/integration/test_runner_errors.py` — `_function_node()` on line 36
- `tests/integration/test_runner_docstring.py` — `_function_node()` on line 29

#### Verification Checklist — Step 7

- [ ] `uv run python -c "from remora.discovery import CSTNode, TreeSitterDiscoverer, NodeType; print('OK')"` → `OK`
- [ ] `uv run python -c "from remora import CSTNode, TreeSitterDiscoverer; print('OK')"` → `OK`
- [ ] No file in `remora/` imports from the deleted `remora/discovery.py`:
  ```bash
  grep -r "PydantreeDiscoverer" remora/
  # Should return NO results
  ```
- [ ] All existing tests pass:
  ```bash
  uv run pytest tests/ -x -q --ignore=tests/integration --ignore=tests/acceptance
  ```
- [ ] Jinja2 template rendering works with `NodeType` enum — the subagent test should pass

---

### Step 8: Rewrite Discovery Tests with Real Tree-sitter

**Goal:** Completely rewrite `tests/test_discovery.py` to test the new pipeline using real tree-sitter parsing (no subprocess mocking).

#### 8.1 Write the new `tests/test_discovery.py`

```python
"""Tests for the tree-sitter discovery pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.discovery import (
    CSTNode,
    DiscoveryError,
    MatchExtractor,
    NodeType,
    QueryLoader,
    SourceParser,
    TreeSitterDiscoverer,
    compute_node_id,
)
from remora.errors import DISC_001, DISC_003, DISC_004

FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PY = FIXTURE_DIR / "sample.py"


# --- NodeType and compute_node_id ---

class TestNodeType:
    def test_string_equality(self) -> None:
        assert NodeType.FUNCTION == "function"
        assert NodeType.METHOD == "method"
        assert NodeType.CLASS == "class"
        assert NodeType.FILE == "file"

    def test_from_string(self) -> None:
        assert NodeType("function") == NodeType.FUNCTION


class TestComputeNodeId:
    def test_deterministic(self) -> None:
        id1 = compute_node_id(Path("test.py"), NodeType.FUNCTION, "hello")
        id2 = compute_node_id(Path("test.py"), NodeType.FUNCTION, "hello")
        assert id1 == id2

    def test_length(self) -> None:
        nid = compute_node_id(Path("test.py"), NodeType.FUNCTION, "hello")
        assert len(nid) == 16

    def test_different_types_differ(self) -> None:
        f_id = compute_node_id(Path("test.py"), NodeType.FUNCTION, "hello")
        m_id = compute_node_id(Path("test.py"), NodeType.METHOD, "hello")
        assert f_id != m_id


# --- SourceParser ---

class TestSourceParser:
    def test_parse_valid_file(self) -> None:
        parser = SourceParser()
        tree, source = parser.parse_file(SAMPLE_PY)
        assert tree.root_node.type == "module"
        assert len(source) > 0

    def test_parse_nonexistent_raises_disc_004(self) -> None:
        parser = SourceParser()
        with pytest.raises(DiscoveryError) as exc:
            parser.parse_file(Path("nonexistent.py"))
        assert exc.value.code == DISC_004

    def test_parse_invalid_syntax_succeeds(self) -> None:
        parser = SourceParser()
        tree = parser.parse_bytes(b"def broken(:\n  pass")
        assert tree.root_node.has_error


# --- QueryLoader ---

class TestQueryLoader:
    def test_load_query_pack(self) -> None:
        loader = QueryLoader()
        queries = loader.load_query_pack(
            Path("remora/queries"), "python", "remora_core"
        )
        assert len(queries) >= 3
        names = {q.name for q in queries}
        assert "class_def" in names
        assert "file" in names
        assert "function_def" in names

    def test_missing_pack_raises_disc_001(self) -> None:
        loader = QueryLoader()
        with pytest.raises(DiscoveryError) as exc:
            loader.load_query_pack(Path("remora/queries"), "python", "nonexistent")
        assert exc.value.code == DISC_001


# --- MatchExtractor ---

class TestMatchExtractor:
    def test_extract_sample_fixture(self) -> None:
        parser = SourceParser()
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("remora/queries"), "python", "remora_core"
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        types_and_names = {(n.node_type, n.name) for n in nodes}
        assert (NodeType.FILE, "sample") in types_and_names
        assert (NodeType.CLASS, "Greeter") in types_and_names
        assert (NodeType.METHOD, "greet") in types_and_names
        assert (NodeType.FUNCTION, "add") in types_and_names

    def test_method_has_full_name(self) -> None:
        parser = SourceParser()
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("remora/queries"), "python", "remora_core"
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        greet = next(n for n in nodes if n.name == "greet")
        assert greet.full_name == "Greeter.greet"
        assert greet.node_type == NodeType.METHOD

    def test_text_matches_source_span(self) -> None:
        parser = SourceParser()
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("remora/queries"), "python", "remora_core"
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        for node in nodes:
            expected = source[node.start_byte:node.end_byte].decode("utf-8")
            assert node.text == expected

    def test_node_ids_are_stable(self) -> None:
        parser = SourceParser()
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("remora/queries"), "python", "remora_core"
        )

        first = [n.node_id for n in extractor.extract(SAMPLE_PY, tree, source, queries)]
        second = [n.node_id for n in extractor.extract(SAMPLE_PY, tree, source, queries)]
        assert first == second

    def test_overlapping_queries_produce_distinct_nodes(self) -> None:
        parser = SourceParser()
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("remora/queries"), "python", "remora_core"
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        class_node = next(n for n in nodes if n.node_type == NodeType.CLASS)
        method_node = next(n for n in nodes if n.name == "greet")
        assert class_node.node_id != method_node.node_id


# --- TreeSitterDiscoverer (end-to-end) ---

class TestTreeSitterDiscoverer:
    def test_discover_returns_expected_nodes(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[FIXTURE_DIR],
            language="python",
            query_pack="remora_core",
        )
        nodes = discoverer.discover()
        types_and_names = {(n.node_type, n.name) for n in nodes}
        assert (NodeType.FILE, "sample") in types_and_names
        assert (NodeType.CLASS, "Greeter") in types_and_names
        assert (NodeType.METHOD, "greet") in types_and_names
        assert (NodeType.FUNCTION, "add") in types_and_names

    def test_discover_single_file(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_PY],
            language="python",
            query_pack="remora_core",
        )
        nodes = discoverer.discover()
        assert all(n.file_path == SAMPLE_PY for n in nodes)

    def test_node_ids_stable_across_runs(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_PY],
            language="python",
            query_pack="remora_core",
        )
        first = [n.node_id for n in discoverer.discover()]
        second = [n.node_id for n in discoverer.discover()]
        assert first == second
```

#### 8.2 Add new test fixture: `tests/fixtures/edge_cases.py`

```python
"""Edge case fixture for discovery testing."""

import asyncio


class OuterClass:
    class InnerClass:
        def inner_method(self) -> None:
            pass

    def outer_method(self) -> str:
        return "outer"

    @staticmethod
    def static_method() -> None:
        pass


async def async_function(x: int) -> int:
    await asyncio.sleep(0)
    return x * 2


def _private_function() -> None:
    pass


class EmptyClass:
    pass


def function_with_lambda():
    return lambda x: x + 1
```

#### 8.3 Add new test fixture: `tests/fixtures/invalid_syntax.py`

```python
# This file intentionally has syntax errors for testing
def broken(:
    pass

class Incomplete
```

#### Verification Checklist — Step 8

- [ ] All new discovery tests pass:
  ```bash
  uv run pytest tests/test_discovery.py -v
  ```
- [ ] Edge cases are discovered correctly:
  ```python
  discoverer = TreeSitterDiscoverer(
      root_dirs=[Path("tests/fixtures/edge_cases.py")],
      language="python", query_pack="remora_core",
  )
  nodes = discoverer.discover()
  types = {(n.node_type.value, n.name) for n in nodes}
  assert ("method", "inner_method") in types
  assert ("method", "outer_method") in types
  assert ("function", "async_function") in types
  assert ("class", "InnerClass") in types
  ```
- [ ] Invalid syntax file doesn't crash discovery but does produce a partial result:
  ```python
  discoverer = TreeSitterDiscoverer(
      root_dirs=[Path("tests/fixtures/invalid_syntax.py")],
      language="python", query_pack="remora_core",
  )
  nodes = discoverer.discover()
  # Should get at least a FILE node; may get partial results for the broken code
  assert len(nodes) >= 1
  ```
- [ ] Full test suite still passes:
  ```bash
  uv run pytest tests/ -x -q --ignore=tests/integration --ignore=tests/acceptance
  ```

---

### Step 9: Build the Round-Trip Test Harness

**Goal:** Create a standalone test harness that takes Python files from an `input/` directory, runs discovery against each, and writes the results to an `output/` directory. This makes it easy to add new test cases and visually inspect what the discovery pipeline produces.

#### 9.1 Create the harness directory structure

```
tests/roundtrip/
├── run_harness.py      ← The harness script
├── input/              ← Drop .py files here
│   ├── sample.py       ← Copy of tests/fixtures/sample.py
│   ├── edge_cases.py   ← Copy of tests/fixtures/edge_cases.py
│   └── (add more .py files as needed)
└── output/             ← Generated by the harness (gitignored)
    ├── sample_out
    ├── edge_cases_out
    └── ...
```

#### 9.2 Write `tests/roundtrip/run_harness.py`

```python
#!/usr/bin/env python3
"""Round-trip test harness for the discovery pipeline.

For each .py file in input/, runs tree-sitter discovery and writes the
matched text (or error output) to output/<filename>_out.

If a file produces multiple matches of the same node type, each match is
saved as <filename>_out-<num> (1-indexed).

Usage:
    uv run python tests/roundtrip/run_harness.py
    uv run python tests/roundtrip/run_harness.py --node-type function
    uv run python tests/roundtrip/run_harness.py --node-type method --node-type class

Check the output/ directory to see what was discovered.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from pathlib import Path

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from remora.discovery import TreeSitterDiscoverer, NodeType


HARNESS_DIR = Path(__file__).resolve().parent
INPUT_DIR = HARNESS_DIR / "input"
OUTPUT_DIR = HARNESS_DIR / "output"


def main() -> None:
    parser = argparse.ArgumentParser(description="Round-trip discovery test harness")
    parser.add_argument(
        "--node-type",
        action="append",
        choices=[nt.value for nt in NodeType],
        help="Filter by node type (can specify multiple). Default: all types.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove output/ directory before running.",
    )
    args = parser.parse_args()

    filter_types: set[str] | None = set(args.node_type) if args.node_type else None

    if not INPUT_DIR.is_dir():
        print(f"ERROR: Input directory not found: {INPUT_DIR}")
        print("Create it and add .py files to test against.")
        sys.exit(1)

    # Clean output
    if args.clean and OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(exist_ok=True)

    input_files = sorted(INPUT_DIR.glob("*.py"))
    if not input_files:
        print(f"No .py files found in {INPUT_DIR}")
        sys.exit(0)

    print(f"Harness: {len(input_files)} input file(s)")
    print(f"Filter: {filter_types or 'all node types'}")
    print(f"Output: {OUTPUT_DIR}\n")

    total_matches = 0

    for input_file in input_files:
        stem = input_file.stem
        print(f"── {input_file.name} ", end="")

        try:
            discoverer = TreeSitterDiscoverer(
                root_dirs=[input_file],
                language="python",
                query_pack="remora_core",
            )
            nodes = discoverer.discover()

            # Apply filter
            if filter_types:
                nodes = [n for n in nodes if n.node_type.value in filter_types]

            if not nodes:
                # Write empty output file
                out_path = OUTPUT_DIR / f"{stem}_out"
                out_path.write_text("(no matches)\n", encoding="utf-8")
                print(f"→ 0 matches")
                continue

            if len(nodes) == 1:
                # Single match → <stem>_out
                out_path = OUTPUT_DIR / f"{stem}_out"
                out_path.write_text(
                    _format_node(nodes[0]),
                    encoding="utf-8",
                )
                total_matches += 1
            else:
                # Multiple matches → <stem>_out-1, <stem>_out-2, ...
                for i, node in enumerate(nodes, start=1):
                    out_path = OUTPUT_DIR / f"{stem}_out-{i}"
                    out_path.write_text(
                        _format_node(node),
                        encoding="utf-8",
                    )
                total_matches += len(nodes)

            print(f"→ {len(nodes)} match(es)")

        except Exception as exc:
            # Write error output
            out_path = OUTPUT_DIR / f"{stem}_out"
            out_path.write_text(
                f"ERROR: {exc}\n\n{traceback.format_exc()}",
                encoding="utf-8",
            )
            print(f"→ ERROR: {exc}")

    print(f"\nDone. {total_matches} total match(es) written to {OUTPUT_DIR}")


def _format_node(node) -> str:
    """Format a CSTNode for output."""
    header = (
        f"node_type: {node.node_type.value}\n"
        f"name: {node.name}\n"
        f"full_name: {node.full_name}\n"
        f"node_id: {node.node_id}\n"
        f"file_path: {node.file_path}\n"
        f"lines: {node.start_line}-{node.end_line}\n"
        f"bytes: {node.start_byte}-{node.end_byte}\n"
        f"---\n"
    )
    return header + node.text + "\n"


if __name__ == "__main__":
    main()
```

#### 9.3 Seed the input directory

Copy the fixture files into the harness input:

```bash
mkdir -p tests/roundtrip/input tests/roundtrip/output
cp tests/fixtures/sample.py tests/roundtrip/input/
cp tests/fixtures/edge_cases.py tests/roundtrip/input/
```

#### 9.4 Add `.gitignore` for output

Create `tests/roundtrip/output/.gitignore`:

```
*
!.gitignore
```

#### Verification Checklist — Step 9

- [ ] Run the harness:
  ```bash
  uv run python tests/roundtrip/run_harness.py --clean
  ```
- [ ] Check output files exist under `tests/roundtrip/output/`
- [ ] Verify output format for `sample_out-*` files contains the expected header + source text
- [ ] Filter by node type:
  ```bash
  uv run python tests/roundtrip/run_harness.py --clean --node-type function
  # Only function/method nodes should appear
  ```
- [ ] Add a new `.py` file to `tests/roundtrip/input/`, re-run the harness, and verify output appears
- [ ] Verify error handling: add a file that can't be parsed (binary file renamed to `.py`) and check the `_out` file contains the error message

---

### Step 10: Cleanup & Delete Legacy Files

**Goal:** Remove all traces of pydantree from the codebase.

#### 10.1 Delete old files

```bash
# Delete the old flat discovery module (should already be done in Step 7)
rm -f remora/discovery.py

# Delete the project-root queries directory
rm -rf queries/

# Delete the old flat query files inside the package
rm -f remora/queries/class_def.scm
rm -f remora/queries/file.scm
rm -f remora/queries/function_def.scm

# Delete the manifest.json from the new location (it was a pydantree artifact)
rm -f remora/queries/python/remora_core/manifest.json
```

#### 10.2 Verify no pydantree references remain

```bash
grep -r "pydantree" --include="*.py" --include="*.toml" --include="*.yaml" --include="*.md" .
```

The only results should be in:
- `TREESITTER_REFACTOR.md` (historical reference)
- `TREESITTER_REFACTOR_CLARIFICATION.md` (historical reference)
- `TREESITTER_REFACTOR_V2.md` (this document)

No results should appear in `remora/`, `tests/`, `scripts/`, or `pyproject.toml`.

#### 10.3 Clean up error codes

In `remora/errors.py`, verify that `DISC_001` and `DISC_002` are still meaningful:

- `DISC_001` — Previously "Pydantree CLI not found". Repurpose to "Query pack not found" (already done in QueryLoader).
- `DISC_002` — Previously "Unexpected Pydantree output format". This can be repurposed into an unexpected treesitter output.

Check if `DISC_002` is still referenced:

```bash
grep -r "DISC_002" remora/ tests/
```

If nothing references it, leave it (it's just a constant string) 

#### Verification Checklist — Step 10

- [ ] `grep -r "pydantree" remora/ tests/ scripts/ pyproject.toml` → No results
- [ ] `queries/` directory at project root no longer exists
- [ ] `remora/discovery.py` (the old file) no longer exists
- [ ] `remora/queries/class_def.scm`, `remora/queries/file.scm`, `remora/queries/function_def.scm` no longer exist
- [ ] `remora/queries/python/remora_core/` contains exactly: `class_def.scm`, `file.scm`, `function_def.scm`
- [ ] Full test suite passes:
  ```bash
  uv run pytest tests/ -x -q --ignore=tests/integration --ignore=tests/acceptance
  ```
- [ ] Round-trip harness still works:
  ```bash
  uv run python tests/roundtrip/run_harness.py --clean
  ```

---

### Step 11: Update Documentation

**Goal:** Update all documentation to reflect the new architecture.

#### 11.1 Update `docs/ARCHITECTURE.md`

Search for any references to:
- `PydantreeDiscoverer` → replace with `TreeSitterDiscoverer`
- `pydantree` → replace with `tree-sitter`
- `discovery.py` → update to `discovery/` package
- Old subprocess-based discovery → update to in-process tree-sitter

#### 11.2 Update `docs/SPEC.md`

Search for any references to discovery and update them.

#### 11.3 Update `README.md`

If the README mentions pydantree as a dependency, update it to mention `tree-sitter` and `tree-sitter-python`.

#### 11.4 Update `remora.yaml.example`

If the example config needs a `query_dir` field in the `discovery:` section, add it:

```yaml
discovery:
  language: python
  query_pack: remora_core
  # query_dir: null  # Use built-in queries (default). Set to override.
```

#### Verification Checklist — Step 11

- [ ] `grep -r "pydantree" docs/` → No results (except historical references if any)
- [ ] `grep -r "PydantreeDiscoverer" docs/` → No results
- [ ] Documentation accurately describes the new tree-sitter discovery pipeline

---

## 7. Round-Trip Test Harness — Usage Reference

The harness at `tests/roundtrip/run_harness.py` is your primary debugging tool during development. Here's how to use it effectively:

### Basic usage

```bash
# Run against all input files, all node types
uv run python tests/roundtrip/run_harness.py --clean

# Filter by specific node type(s)
uv run python tests/roundtrip/run_harness.py --clean --node-type method
uv run python tests/roundtrip/run_harness.py --clean --node-type function --node-type method
```

### Adding new test cases

1. Drop a `.py` file into `tests/roundtrip/input/`
2. Run the harness
3. Check the output in `tests/roundtrip/output/`

### Output format

Each output file contains a header with metadata followed by the matched source text:

```
node_type: method
name: greet
full_name: Greeter.greet
node_id: a1b2c3d4e5f67890
file_path: tests/roundtrip/input/sample.py
lines: 2-3
bytes: 19-71
---
def greet(self, name: str) -> str:
    return f"Hello, {name}!"
```

### Naming convention

| Scenario | Output filename |
|---|---|
| Single match | `<input_filename>_out` |
| Multiple matches | `<input_filename>_out-1`, `<input_filename>_out-2`, ... |
| Error | `<input_filename>_out` (contains error message) |
| No matches | `<input_filename>_out` (contains "(no matches)") |

---

## 8. Future Enhancements (Out of Scope)

These are explicitly **not** part of this refactor but are documented here for when they become relevant:

### Parallelism

**Where to add it:** In `TreeSitterDiscoverer._collect_files()` and the file processing loop in `discover()`.

**How:** Use `concurrent.futures.ThreadPoolExecutor` to parse files in parallel. Each thread needs its own `SourceParser` instance (tree-sitter `Parser` is not thread-safe).

```python
# Pseudocode for future parallelism:
from concurrent.futures import ThreadPoolExecutor

def discover(self) -> list[CSTNode]:
    queries = self._loader.load_query_pack(...)
    py_files = self._collect_files()

    def process_file(file_path: Path) -> list[CSTNode]:
        parser = SourceParser()  # Per-thread instance
        tree, source = parser.parse_file(file_path)
        return self._extractor.extract(file_path, tree, source, queries)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = pool.map(process_file, py_files)
    # Flatten and deduplicate...
```

### Tree Caching

**Where to add it:** In `SourceParser`, keyed by `(file_path, mtime)`.

**How:** Use `functools.lru_cache` or a custom dict cache. Re-parse only if `mtime` has changed.

### Incremental Discovery

**Where to add it:** In `TreeSitterDiscoverer`, tracking file modification times between runs.

### Multi-Language Support

**Where to add it:** `SourceParser` would accept a language parameter and initialize the appropriate parser. `QueryLoader` already supports language subdirectories.

---

## 9. Complete Migration Checklist

Use this to track overall progress across all steps:

### Step 1: Dependencies & Skeleton
- [ ] Update `pyproject.toml`
- [ ] Run `uv sync`
- [ ] Create `remora/discovery/` package with stub files
- [ ] Verify tree-sitter imports

### Step 2: Core Models
- [ ] Implement `models.py` (CSTNode, NodeType, DiscoveryError, compute_node_id)
- [ ] Add DISC_003, DISC_004 to `errors.py`
- [ ] Update `discovery/__init__.py` exports
- [ ] Verify model creation and hashing

### Step 3: Source Parser
- [ ] Implement `source_parser.py`
- [ ] Verify parsing of valid, invalid, and nonexistent files

### Step 4: Query Loader
- [ ] Implement `query_loader.py`
- [ ] Update `.scm` files (`file.scm`, `function_def.scm`)
- [ ] Verify query loading and compilation

### Step 5: Match Extractor
- [ ] Implement `match_extractor.py`
- [ ] Verify extraction, METHOD detection, full_name, dedup, sorting

### Step 6: TreeSitterDiscoverer
- [ ] Implement discoverer in `__init__.py`
- [ ] Verify end-to-end discovery

### Step 7: Consumer Cutover
- [ ] Update `config.py` (add query_dir)
- [ ] Update `analyzer.py`
- [ ] Update `orchestrator.py`
- [ ] Update `runner.py`
- [ ] Update `subagent.py` (verify NodeType in Jinja2)
- [ ] Update `__init__.py`
- [ ] Update `scripts/remora_demo.py`
- [ ] Delete `remora/discovery.py`
- [ ] Update all test `_make_node()` helpers (7+ files)
- [ ] All tests pass

### Step 8: Rewrite Discovery Tests
- [ ] Write new `test_discovery.py`
- [ ] Create `edge_cases.py` and `invalid_syntax.py` fixtures
- [ ] All discovery tests pass

### Step 9: Round-Trip Harness
- [ ] Create `tests/roundtrip/` directory structure
- [ ] Write `run_harness.py`
- [ ] Seed input files
- [ ] Verify harness output

### Step 10: Cleanup
- [ ] Delete `queries/` at project root
- [ ] Delete old flat `.scm` files in `remora/queries/`
- [ ] Delete `manifest.json`
- [ ] Verify no pydantree references remain
- [ ] Full test suite passes

### Step 11: Documentation
- [ ] Update `docs/ARCHITECTURE.md`
- [ ] Update `docs/SPEC.md`
- [ ] Update `README.md`
- [ ] Update `remora.yaml.example`

### Final Smoke Test
- [ ] `uv sync` clean
- [ ] `uv run pytest tests/ -x -q` (all non-integration tests pass)
- [ ] `uv run python tests/roundtrip/run_harness.py --clean` (harness works)
- [ ] `grep -r "pydantree" remora/ tests/ scripts/ pyproject.toml` (no results)
- [ ] `uv run python -c "from remora import CSTNode, TreeSitterDiscoverer; print('OK')"` (OK)

---

## Appendix A: tree-sitter Python API Quick Reference

### Installing

```bash
uv add "tree-sitter>=0.24" "tree-sitter-python>=0.23"
```

### Basic parsing

```python
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)

source = b"def hello(): pass"
tree = parser.parse(source)
root = tree.root_node

print(root.type)            # "module"
print(root.child_count)     # 1
print(root.children[0].type)  # "function_definition"
```

### Running queries

```python
query = PY_LANGUAGE.query("""
(function_definition
  name: (identifier) @func.name
) @func.def
""")

matches = query.matches(root)
for pattern_index, captures_dict in matches:
    for capture_name, nodes in captures_dict.items():
        for node in nodes:
            text = source[node.start_byte:node.end_byte].decode()
            print(f"{capture_name}: {text}")
```

### Node properties

```python
node = root.children[0]  # function_definition
node.type           # "function_definition"
node.start_byte     # 0
node.end_byte       # 17
node.start_point    # Point(row=0, column=0) — 0-indexed!
node.end_point      # Point(row=0, column=17)
node.has_error      # False
node.parent         # The parent node
node.children       # List of child nodes
node.child_by_field_name("name")  # The identifier node
```

### Important notes

- **Line numbers are 0-indexed** in tree-sitter. Add 1 to get human-readable line numbers.
- **`Parser` is NOT thread-safe.** Create one per thread if parallelizing.
- **tree-sitter is error-tolerant.** It always produces a tree, even for invalid syntax. Check `root_node.has_error` to detect parse errors.
- **`query.matches()` returns `list[tuple[int, dict[str, list[Node]]]]`** — pattern index + captures dictionary.

---

## Appendix B: Development Commands

```bash
# Setup
uv sync

# Run all non-integration tests
uv run pytest tests/ -x -q --ignore=tests/integration --ignore=tests/acceptance

# Run discovery tests specifically
uv run pytest tests/test_discovery.py -v

# Run round-trip harness
uv run python tests/roundtrip/run_harness.py --clean

# Run round-trip harness filtered by node type
uv run python tests/roundtrip/run_harness.py --clean --node-type method

# Type check the discovery package
uv run mypy remora/discovery/

# Lint the discovery package
uv run ruff check remora/discovery/

# Format the discovery package
uv run ruff format remora/discovery/

# Verify no pydantree references
grep -r "pydantree" remora/ tests/ scripts/ pyproject.toml
```

---

**Document Version:** 2.0
**Created:** 2026-02-18
**Status:** Ready for Implementation
