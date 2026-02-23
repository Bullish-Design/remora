# Language Expansion Refactor Plan - Final Implementation Guide

This document provides the complete, step-by-step implementation guide for refactoring Remora's discovery module from a Python-only parser to a generic, multi-language tree-sitter engine. This guide is designed for a junior developer to follow sequentially.

---

## Executive Summary

**Goal:** Transform Remora's discovery module into a language-agnostic engine that can parse any tree-sitter supported language by:

1. Replacing the `NodeType` enum with a simple string type alias
2. Making language grammar loading dynamic via `importlib`
3. Moving all extraction logic to `.scm` query files
4. Eliminating all Python-specific AST walking code

**Architecture Approach:** Option A - Pure Data-Driven "Smart Queries"

The `.scm` files become the single source of truth for:
- **What** nodes to capture (`@X.def`)
- **How** to name them (`@X.name`)
- **What type** they are (derived from capture prefix)

The Python engine becomes completely generic and language-agnostic.

---

## Before vs After Architecture

### Current (Python-Centric)
```
Config → Discoverer → [Hardcoded .py glob]
                    → SourceParser (hardcoded tree_sitter_python)
                    → QueryLoader (hardcoded PY_LANGUAGE)
                    → MatchExtractor
                       ├─ _PREFIX_TO_NODE_TYPE dict
                       ├─ _extract_name_from_node()
                       └─ _classify_function() ← Python AST walking
```

### Target (Language-Agnostic)
```
Config.LANGUAGES → Discoverer → [Loop over extensions]
                              → SourceParser(grammar_module) ← dynamic
                              → QueryLoader(language) ← dynamic
                              → MatchExtractor ← 50 lines, generic
                                 └─ Parse @X.def/@X.name captures only
```

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `src/remora/config.py` | **MODIFY** | Add `LANGUAGES` dict mapping extensions to grammar modules |
| `src/remora/discovery/models.py` | **MODIFY** | Replace `NodeType` enum with `NodeType = str` type alias |
| `src/remora/discovery/source_parser.py` | **MODIFY** | Dynamic language loading via `importlib` |
| `src/remora/discovery/query_loader.py` | **MODIFY** | Dynamic language loading via `importlib` |
| `src/remora/discovery/match_extractor.py` | **MODIFY** | Simplify to ~50 lines, remove Python-specific logic |
| `src/remora/discovery/discoverer.py` | **MODIFY** | Loop over `LANGUAGES` config |
| `src/remora/discovery/__init__.py` | **MODIFY** | Update exports if needed |
| `src/remora/testing/factories.py` | **MODIFY** | Use string literals for `node_type` |
| `src/remora/queries/python/remora_core/function_def.scm` | **RENAME/REWRITE** | Rename to `function.scm`, add nested method query |
| `src/remora/queries/python/remora_core/class_def.scm` | **RENAME/REWRITE** | Rename to `class.scm`, simplify |
| `src/remora/queries/python/remora_core/file.scm` | **KEEP** | No changes needed |
| `src/remora/queries/toml/remora_core/file.scm` | **CREATE** | Document capture |
| `src/remora/queries/toml/remora_core/table.scm` | **CREATE** | Table and array_table captures |
| `src/remora/queries/markdown/remora_core/file.scm` | **CREATE** | Document capture |
| `src/remora/queries/markdown/remora_core/section.scm` | **CREATE** | ATX heading captures |
| `tests/test_discovery.py` | **MODIFY** | Update tests for string `NodeType` |
| `tests/fixtures/sample.py` | **KEEP** | No changes needed |
| `tests/fixtures/sample.toml` | **CREATE** | TOML test fixture |
| `tests/fixtures/sample.md` | **CREATE** | Markdown test fixture |

---

## Implementation Steps

### Step 1: Add LANGUAGES Configuration

**File:** `src/remora/config.py`

**What:** Add a module-level constant mapping file extensions to tree-sitter grammar modules.

**Location:** Add after the imports, before `_default_cache_dir()` (around line 30).

```python
# Language extension to grammar module mapping
# Used by discovery to dynamically load tree-sitter parsers
LANGUAGES: dict[str, str] = {
    ".py": "tree_sitter_python",
    ".pyi": "tree_sitter_python",
    ".toml": "tree_sitter_toml",
    ".md": "tree_sitter_markdown",
}
```

**Why:** This single dict drives all language support. Adding a new language = adding one line here + writing `.scm` files.

**Test:**
```bash
python -c "from remora.config import LANGUAGES; print(LANGUAGES)"
```

---

### Step 2: Replace NodeType Enum with String Type Alias

**File:** `src/remora/discovery/models.py`

**What:** Replace the `NodeType` enum class with a simple type alias.

**Before (lines 11-17):**
```python
class NodeType(str, Enum):
    """Type of discovered code node."""

    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
```

**After:**
```python
# NodeType is now a simple string - any value is valid.
# The type is determined by the capture prefix in .scm files (e.g., @class.def → "class")
NodeType = str
```

**Also update `compute_node_id` function (around line 26):**

**Before:**
```python
def compute_node_id(file_path: Path, node_type: NodeType, name: str) -> str:
    ...
    digest_input = f"{file_path.resolve()}:{node_type.value}:{name}".encode("utf-8")
```

**After:**
```python
def compute_node_id(file_path: Path, node_type: NodeType, name: str) -> str:
    """Compute a stable node ID.

    Hash: sha256(resolved_file_path:node_type:name), truncated to 16 hex chars.
    Stable across reformatting because it does NOT include byte offsets.
    """
    digest_input = f"{file_path.resolve()}:{node_type}:{name}".encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()[:16]
```

**Note:** We changed `node_type.value` to just `node_type` since it's now a plain string.

**Also remove the `Enum` import** from line 7:
```python
# Before
from enum import Enum

# After (remove this line entirely)
```

**Test:**
```bash
python -c "from remora.discovery.models import NodeType; print(type(NodeType), NodeType)"
# Expected: <class 'type'> <class 'str'>
```

---

### Step 3: Refactor SourceParser for Dynamic Language Loading

**File:** `src/remora/discovery/source_parser.py`

**What:** Replace hardcoded `tree_sitter_python` with dynamic `importlib` loading.

**Full replacement of file:**

```python
"""Source file parsing using tree-sitter."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from tree_sitter import Language, Parser, Tree

from remora.discovery.models import DiscoveryError

logger = logging.getLogger(__name__)


class SourceParser:
    """Parses source files into tree-sitter Trees.

    Dynamically loads the appropriate tree-sitter grammar based on the
    grammar_module parameter (e.g., "tree_sitter_python", "tree_sitter_toml").

    Usage:
        parser = SourceParser("tree_sitter_python")
        tree, source_bytes = parser.parse_file(Path("example.py"))
    """

    def __init__(self, grammar_module: str) -> None:
        """Initialize parser with a specific grammar module.

        Args:
            grammar_module: The tree-sitter grammar module name,
                           e.g., "tree_sitter_python", "tree_sitter_toml".
        """
        try:
            grammar_pkg = importlib.import_module(grammar_module)
        except ImportError as exc:
            raise DiscoveryError(
                f"Failed to import grammar module: {grammar_module}"
            ) from exc

        self._language = Language(grammar_pkg.language())
        self._parser = Parser(self._language)
        self._grammar_module = grammar_module

    @property
    def language(self) -> Language:
        """Return the tree-sitter Language object."""
        return self._language

    def parse_file(self, file_path: Path) -> tuple[Tree, bytes]:
        """Parse a source file and return (tree, source_bytes).

        Args:
            file_path: Path to the source file.

        Returns:
            Tuple of (parsed Tree, raw source bytes).

        Raises:
            DiscoveryError: If the file cannot be read.
        """
        resolved = file_path.resolve()
        try:
            source_bytes = resolved.read_bytes()
        except OSError as exc:
            raise DiscoveryError(f"Failed to read source file: {resolved}") from exc

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

**Key changes:**
- Constructor now takes `grammar_module: str` parameter
- Uses `importlib.import_module()` to dynamically load the grammar
- Exposes `language` property for use by QueryLoader

**Test:**
```bash
python -c "
from remora.discovery.source_parser import SourceParser
parser = SourceParser('tree_sitter_python')
print('Python parser OK')
parser = SourceParser('tree_sitter_toml')
print('TOML parser OK')
parser = SourceParser('tree_sitter_markdown')
print('Markdown parser OK')
"
```

---

### Step 4: Refactor QueryLoader for Dynamic Language Loading

**File:** `src/remora/discovery/query_loader.py`

**What:** Replace hardcoded `PY_LANGUAGE` with dynamic loading.

**Full replacement of file:**

```python
"""Query loading and compilation for tree-sitter."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from tree_sitter import Language, Query

from remora.discovery.models import DiscoveryError

logger = logging.getLogger(__name__)


class CompiledQuery:
    """A compiled tree-sitter query with metadata."""

    def __init__(self, query: Query, source_file: Path, query_text: str, query_name: str) -> None:
        self.query = query
        self.source_file = source_file
        self.query_text = query_text
        self._query_name = query_name

    @property
    def name(self) -> str:
        """Query name derived from filename (e.g. 'function' from 'function.scm')."""
        return self._query_name


class QueryLoader:
    """Loads and compiles tree-sitter queries from .scm files.

    Usage:
        loader = QueryLoader()
        queries = loader.load_query_pack(
            query_dir=Path("src/remora/queries"),
            language="python",
            query_pack="remora_core",
        )
    """

    def load_query_pack(
        self,
        query_dir: Path,
        language: str,
        query_pack: str,
    ) -> list[CompiledQuery]:
        """Load all .scm files from a query pack directory.

        Args:
            query_dir: Root query directory (e.g. src/remora/queries/).
            language: Language subdirectory (e.g. "python", "toml", "markdown").
            query_pack: Query pack subdirectory (e.g. "remora_core").

        Returns:
            List of compiled queries.

        Raises:
            DiscoveryError: If query pack directory doesn't exist or a query has syntax errors.
        """
        pack_dir = query_dir / language / query_pack
        if not pack_dir.is_dir():
            raise DiscoveryError(
                f"Query pack directory not found: {pack_dir}",
            )

        scm_files = sorted(pack_dir.glob("*.scm"))
        if not scm_files:
            raise DiscoveryError(
                f"No .scm query files found in: {pack_dir}",
            )

        # Dynamically load the language for query compilation
        grammar_module = f"tree_sitter_{language}"
        try:
            grammar_pkg = importlib.import_module(grammar_module)
        except ImportError as exc:
            raise DiscoveryError(
                f"Failed to import grammar module: {grammar_module}"
            ) from exc

        ts_language = Language(grammar_pkg.language())

        compiled: list[CompiledQuery] = []
        for scm_file in scm_files:
            compiled.append(self._compile_query(scm_file, ts_language))

        logger.info(
            "Loaded %d queries from %s/%s: %s",
            len(compiled),
            language,
            query_pack,
            [q.name for q in compiled],
        )
        return compiled

    def _compile_query(self, scm_file: Path, ts_language: Language) -> CompiledQuery:
        """Compile a single .scm file into a tree-sitter Query."""
        try:
            query_text = scm_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise DiscoveryError(f"Failed to read query file: {scm_file}") from exc

        try:
            query = Query(ts_language, query_text)
        except Exception as exc:
            raise DiscoveryError(f"Query syntax error in {scm_file.name}: {exc}") from exc

        return CompiledQuery(
            query=query,
            source_file=scm_file,
            query_text=query_text,
            query_name=scm_file.stem,
        )
```

**Key changes:**
- Removed hardcoded `PY_LANGUAGE`
- Dynamically loads grammar based on `language` parameter: `tree_sitter_{language}`
- `CompiledQuery` now stores `query_name` explicitly

**Test:**
```bash
python -c "
from pathlib import Path
from remora.discovery.query_loader import QueryLoader
loader = QueryLoader()
queries = loader.load_query_pack(Path('src/remora/queries'), 'python', 'remora_core')
print(f'Loaded {len(queries)} queries:', [q.name for q in queries])
"
```

---

### Step 5: Simplify MatchExtractor (The Core Refactor)

**File:** `src/remora/discovery/match_extractor.py`

**What:** Remove all Python-specific logic. The extractor now blindly trusts `.scm` captures.

**Full replacement of file:**

```python
"""Match extraction and CSTNode construction from tree-sitter queries."""

from __future__ import annotations

import logging
from pathlib import Path

from tree_sitter import QueryCursor, Tree

from remora.discovery.models import CSTNode, compute_node_id
from remora.discovery.query_loader import CompiledQuery

logger = logging.getLogger(__name__)


class MatchExtractor:
    """Executes compiled queries against parsed trees and builds CSTNode lists.

    This extractor is completely language-agnostic. It relies on the .scm query
    files to define:
    - What nodes to capture via @X.def
    - What names to extract via @X.name
    - What types nodes should have (derived from capture prefix X)

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

        nodes.sort(key=lambda n: (str(n.file_path), n.start_byte, n.node_type, n.name))
        return nodes

    def _run_query(
        self,
        file_path: Path,
        tree: Tree,
        source_bytes: bytes,
        compiled_query: CompiledQuery,
    ) -> list[CSTNode]:
        """Run a single query and extract CSTNodes from matches.

        The query file name determines the node type. For example:
        - function.scm → expects @function.def and @function.name captures
        - class.scm → expects @class.def and @class.name captures
        - file.scm → expects @file.def capture (name derived from file stem)

        For queries with multiple node types (e.g., function.scm with both
        @function.def and @method.def), each capture prefix defines its type.
        """
        cursor = QueryCursor(compiled_query.query)
        nodes: list[CSTNode] = []

        # Process matches (each match groups related captures)
        for match in cursor.matches(tree.root_node):
            # Group captures by their prefix (e.g., "function", "method", "class")
            captures_by_prefix: dict[str, dict[str, object]] = {}

            for capture_name, ts_node in match[1].items():
                parts = capture_name.split(".")
                if len(parts) != 2:
                    continue

                prefix, suffix = parts
                if prefix not in captures_by_prefix:
                    captures_by_prefix[prefix] = {}
                captures_by_prefix[prefix][suffix] = ts_node

            # Build nodes for each captured prefix that has a .def
            for prefix, captures in captures_by_prefix.items():
                def_node = captures.get("def")
                if def_node is None:
                    continue

                node_type = prefix  # e.g., "function", "method", "class", "table"

                # Extract name from @X.name capture, or use file stem for file nodes
                name_node = captures.get("name")
                if name_node is not None:
                    name = source_bytes[name_node.start_byte:name_node.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                elif node_type == "file":
                    name = file_path.stem
                else:
                    name = "unknown"

                text = source_bytes[def_node.start_byte:def_node.end_byte].decode(
                    "utf-8", errors="replace"
                )

                node_id = compute_node_id(file_path, node_type, name)

                nodes.append(
                    CSTNode(
                        node_id=node_id,
                        node_type=node_type,
                        name=name,
                        file_path=file_path,
                        start_byte=def_node.start_byte,
                        end_byte=def_node.end_byte,
                        text=text,
                        start_line=def_node.start_point.row + 1,
                        end_line=def_node.end_point.row + 1,
                    )
                )

        return nodes
```

**Key changes:**
- Removed `_PREFIX_TO_NODE_TYPE` dict (184 → ~80 lines)
- Removed `_build_node_from_capture()` method
- Removed `_extract_name_from_node()` method
- Removed `_classify_function()` method (no more Python AST walking!)
- Node type comes directly from capture prefix: `@function.def` → type `"function"`
- Name comes from `@X.name` capture, not from tree-sitter field inspection
- Uses `cursor.matches()` instead of `cursor.captures()` to properly group related captures

**Critical insight:** The `.scm` files now control everything. To distinguish methods from functions in Python, we use nested queries in the `.scm` file (see Step 7).

---

### Step 6: Update TreeSitterDiscoverer to Loop Over Languages

**File:** `src/remora/discovery/discoverer.py`

**What:** Replace hardcoded `.py` file collection with dynamic language iteration.

**Full replacement of file:**

```python
"""Tree-sitter backed node discovery for Remora."""

from __future__ import annotations

import concurrent.futures
import importlib.resources
import logging
import time
from pathlib import Path
from typing import Iterable

from remora.config import LANGUAGES
from remora.discovery.match_extractor import MatchExtractor
from remora.discovery.models import CSTNode, DiscoveryError
from remora.discovery.query_loader import QueryLoader
from remora.discovery.source_parser import SourceParser
from remora.events import EventName, EventStatus

logger = logging.getLogger(__name__)


def _default_query_dir() -> Path:
    """Return the built-in query directory inside the remora package."""
    return Path(importlib.resources.files("remora")) / "queries"  # type: ignore[arg-type]


class TreeSitterDiscoverer:
    """Discovers code nodes by parsing source files with tree-sitter.

    Supports multiple languages as configured in LANGUAGES dict.

    Note:
        Discovery is synchronous; use ``asyncio.to_thread`` if calling from
        an async workflow.

    Usage:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[Path("./src")],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()
    """

    def __init__(
        self,
        root_dirs: Iterable[Path],
        query_pack: str = "remora_core",
        *,
        query_dir: Path | None = None,
        event_emitter=None,
        languages: dict[str, str] | None = None,
    ) -> None:
        """Initialize the discoverer.

        Args:
            root_dirs: Directories or files to scan.
            query_pack: Query pack name (default: "remora_core").
            query_dir: Custom query directory (default: built-in queries).
            event_emitter: Optional event emitter for discovery events.
            languages: Override LANGUAGES dict (default: use remora.config.LANGUAGES).
        """
        self.root_dirs = [Path(p).resolve() for p in root_dirs]
        self.query_pack = query_pack
        self.query_dir = query_dir or _default_query_dir()
        self.event_emitter = event_emitter
        self._languages = languages or LANGUAGES

    def discover(self) -> list[CSTNode]:
        """Walk root_dirs, parse files, run queries, return CSTNodes.

        Iterates over all configured languages, collecting files by extension,
        parsing them with the appropriate tree-sitter grammar, and extracting
        nodes using the corresponding query pack.

        Emits a discovery event with timing if an event_emitter is set.
        """
        start = time.monotonic()
        status = EventStatus.OK

        try:
            all_nodes: list[CSTNode] = []

            # Group extensions by language for efficient processing
            ext_to_language: dict[str, str] = {}
            for ext, grammar_module in self._languages.items():
                # Extract language name from grammar module (e.g., "tree_sitter_python" → "python")
                language = grammar_module.replace("tree_sitter_", "")
                ext_to_language[ext] = language

            # Check which languages have query packs
            languages_with_queries: dict[str, list[str]] = {}  # language → [extensions]
            for ext, language in ext_to_language.items():
                pack_dir = self.query_dir / language / self.query_pack
                if pack_dir.is_dir():
                    if language not in languages_with_queries:
                        languages_with_queries[language] = []
                    languages_with_queries[language].append(ext)

            # Process each language
            for language, extensions in languages_with_queries.items():
                grammar_module = f"tree_sitter_{language}"
                files = self._collect_files(set(extensions))

                if not files:
                    continue

                # Load queries once per language
                loader = QueryLoader()
                try:
                    queries = loader.load_query_pack(self.query_dir, language, self.query_pack)
                except DiscoveryError as e:
                    logger.warning("Skipping language %s: %s", language, e)
                    continue

                # Parse files in parallel
                def _parse_single(file_path: Path) -> list[CSTNode]:
                    try:
                        parser = SourceParser(grammar_module)
                        extractor = MatchExtractor()
                        tree, source_bytes = parser.parse_file(file_path)
                        return extractor.extract(file_path, tree, source_bytes, queries)
                    except DiscoveryError:
                        logger.warning("Skipping %s due to parse error", file_path)
                        return []

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    results_generator = executor.map(_parse_single, files)
                    for nodes in results_generator:
                        all_nodes.extend(nodes)

            # Deduplicate and sort
            seen_ids: set[str] = set()
            unique_nodes: list[CSTNode] = []
            for node in all_nodes:
                if node.node_id not in seen_ids:
                    seen_ids.add(node.node_id)
                    unique_nodes.append(node)

            unique_nodes.sort(key=lambda n: (str(n.file_path), n.start_byte, n.node_type, n.name))
            return unique_nodes

        except Exception:
            status = EventStatus.ERROR
            raise
        finally:
            if self.event_emitter is not None:
                duration_ms = int((time.monotonic() - start) * 1000)
                self.event_emitter.emit(
                    {
                        "event": EventName.DISCOVERY,
                        "phase": "discovery",
                        "status": status,
                        "duration_ms": duration_ms,
                    }
                )

    def _collect_files(self, extensions: set[str]) -> list[Path]:
        """Walk root_dirs and collect files matching the given extensions."""
        files: list[Path] = []
        for root in self.root_dirs:
            if root.is_file() and root.suffix in extensions:
                files.append(root)
            elif root.is_dir():
                for ext in extensions:
                    files.extend(sorted(root.rglob(f"*{ext}")))
        return files
```

**Key changes:**
- Removed `language` parameter (no longer needed)
- Added optional `languages` parameter to override default LANGUAGES
- Loops over all configured languages
- Collects files by extension dynamically
- Only processes languages that have query packs
- Removed unused imports (`compute_node_id`, `NodeType`, `CompiledQuery`)

---

### Step 7: Rewrite Python .scm Query Files

**What:** Add nested queries to distinguish methods from standalone functions. Order matters!

#### 7a. Rename and Rewrite function_def.scm → function.scm

**File:** `src/remora/queries/python/remora_core/function.scm`

First, rename the file:
```bash
mv src/remora/queries/python/remora_core/function_def.scm \
   src/remora/queries/python/remora_core/function.scm
```

**New content:**
```scheme
; Capture Python functions and methods
;
; IMPORTANT: Methods (nested inside classes) come FIRST.
; This ensures we capture @method.def before the more general @function.def
; matches the same nodes.

; Methods: functions defined inside class bodies
(class_definition
  body: (block
    (function_definition
      name: (identifier) @method.name
    ) @method.def
  )
)

; Standalone functions: top-level function definitions
(function_definition
  name: (identifier) @function.name
) @function.def
```

**Why this works:** Tree-sitter matches patterns in order. By defining the nested class → method pattern first, methods are captured as `@method.def`. The generic function pattern still matches all functions, but deduplication by `node_id` in `MatchExtractor.extract()` ensures we keep the first (method) version.

**Note:** Due to how tree-sitter queries work, the standalone function query will also match methods. However, since methods are captured first with `@method.def/@method.name`, and we deduplicate by `node_id` in the extractor, methods won't be double-counted as functions.

#### 7b. Rename and Simplify class_def.scm → class.scm

**File:** `src/remora/queries/python/remora_core/class.scm`

First, rename:
```bash
mv src/remora/queries/python/remora_core/class_def.scm \
   src/remora/queries/python/remora_core/class.scm
```

**New content:**
```scheme
; Capture class definitions
(class_definition
  name: (identifier) @class.name
) @class.def
```

**Note:** Removed the `@class.body` capture since we don't use it.

#### 7c. Keep file.scm unchanged

**File:** `src/remora/queries/python/remora_core/file.scm`

```scheme
; Capture one FILE node per module
(module) @file.def
```

No changes needed. The extractor handles `file` type specially (uses file stem as name).

---

### Step 8: Create TOML Query Files

**What:** Create query files to extract TOML tables and array tables.

**Important tree-sitter-toml note:** The actual node types differ from what you might expect:
- Standard table `[name]` → node type `table`
- Array table `[[name]]` → node type `table_array_element`

#### 8a. Create directory structure

```bash
mkdir -p src/remora/queries/toml/remora_core
```

#### 8b. Create file.scm

**File:** `src/remora/queries/toml/remora_core/file.scm`

```scheme
; Capture the entire TOML document
(document) @file.def
```

#### 8c. Create table.scm

**File:** `src/remora/queries/toml/remora_core/table.scm`

```scheme
; Capture TOML tables
;
; Standard tables: [project], [tool.pytest], etc.
; Array tables: [[tool.mypy.overrides]], [[servers]], etc.

; Standard table with simple key: [project]
(table
  (bare_key) @table.name
) @table.def

; Standard table with dotted key: [tool.pytest]
(table
  (dotted_key) @table.name
) @table.def

; Array table with simple key: [[servers]]
(table_array_element
  (bare_key) @array_table.name
) @array_table.def

; Array table with dotted key: [[tool.mypy.overrides]]
(table_array_element
  (dotted_key) @array_table.name
) @array_table.def
```

---

### Step 9: Create Markdown Query Files

**What:** Create query files to extract Markdown headings and code blocks.

#### 9a. Create directory structure

```bash
mkdir -p src/remora/queries/markdown/remora_core
```

#### 9b. Create file.scm

**File:** `src/remora/queries/markdown/remora_core/file.scm`

```scheme
; Capture the entire Markdown document
(document) @file.def
```

#### 9c. Create section.scm

**File:** `src/remora/queries/markdown/remora_core/section.scm`

```scheme
; Capture Markdown sections (ATX headings)
;
; # Heading 1
; ## Heading 2
; ### Heading 3
; etc.

(atx_heading
  (inline) @section.name
) @section.def

; Capture fenced code blocks
; ```python
; code here
; ```

(fenced_code_block
  (info_string)? @code_block.lang
) @code_block.def
```

**Note:** For code blocks without an info string (language), the `@code_block.lang` capture will be empty, so `name` will be "unknown".

---

### Step 10: Update factories.py

**File:** `src/remora/testing/factories.py`

**What:** Update to use string literals for `node_type`.

**Before (lines 27-38):**
```python
def make_node() -> CSTNode:
    return CSTNode(
        node_id="node-1",
        node_type=NodeType.FUNCTION,
        name="hello",
        ...
    )
```

**After:**
```python
def make_node(node_type: str = "function") -> CSTNode:
    """Create a test CSTNode.

    Args:
        node_type: Node type string (default: "function").
    """
    return CSTNode(
        node_id="node-1",
        node_type=node_type,
        name="hello",
        file_path=Path("src/example.py"),
        start_byte=0,
        end_byte=10,
        text="def hello(): ...",
        start_line=1,
        end_line=1,
    )
```

**Also update the import at the top of the file:**

**Before:**
```python
from remora.discovery import CSTNode, NodeType
```

**After:**
```python
from remora.discovery import CSTNode
```

---

### Step 11: Update Tests

**File:** `tests/test_discovery.py`

#### 11a. Remove TestNodeType class entirely (lines 24-32)

The `TestNodeType` class tests enum behavior that no longer exists. Delete it entirely:

```python
# DELETE THIS CLASS ENTIRELY
class TestNodeType:
    def test_string_equality(self) -> None:
        assert NodeType.FUNCTION == "function"
        ...
```

#### 11b. Update imports

**Before:**
```python
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
```

**After:**
```python
from remora.discovery import (
    CSTNode,
    DiscoveryError,
    MatchExtractor,
    QueryLoader,
    SourceParser,
    TreeSitterDiscoverer,
    compute_node_id,
)
```

#### 11c. Update TestComputeNodeId

Replace `NodeType.FUNCTION` with `"function"` and `NodeType.METHOD` with `"method"`:

```python
class TestComputeNodeId:
    def test_deterministic(self) -> None:
        id1 = compute_node_id(Path("test.py"), "function", "hello")
        id2 = compute_node_id(Path("test.py"), "function", "hello")
        assert id1 == id2

    def test_length(self) -> None:
        nid = compute_node_id(Path("test.py"), "function", "hello")
        assert len(nid) == 16

    def test_different_types_differ(self) -> None:
        f_id = compute_node_id(Path("test.py"), "function", "hello")
        m_id = compute_node_id(Path("test.py"), "method", "hello")
        assert f_id != m_id

    def test_different_names_differ(self) -> None:
        id1 = compute_node_id(Path("test.py"), "function", "hello")
        id2 = compute_node_id(Path("test.py"), "function", "goodbye")
        assert id1 != id2
```

#### 11d. Update TestCSTNode

Replace `NodeType.FUNCTION` with `"function"` and `NodeType.METHOD` with `"method"`:

```python
class TestCSTNode:
    def test_frozen(self) -> None:
        node = CSTNode(
            node_id="test",
            node_type="function",
            name="hello",
            ...
        )
        ...

    def test_full_name_defaults_to_name(self) -> None:
        node = CSTNode(
            node_id="test",
            node_type="function",
            ...
        )
        ...

    def test_full_name_can_be_set(self) -> None:
        node = CSTNode(
            node_id="test",
            node_type="method",
            ...
        )
        ...
```

#### 11e. Update TestSourceParser

The `SourceParser` now requires a grammar module parameter:

```python
class TestSourceParser:
    def test_parse_file(self) -> None:
        parser = SourceParser("tree_sitter_python")
        tree, source = parser.parse_file(SAMPLE_PY)
        assert tree.root_node.type == "module"
        assert len(source) > 0

    def test_parse_bytes(self) -> None:
        parser = SourceParser("tree_sitter_python")
        source = b"def hello(): pass"
        tree = parser.parse_bytes(source)
        assert tree.root_node.type == "module"
        assert tree.root_node.child_count == 1

    def test_parse_invalid_syntax(self) -> None:
        parser = SourceParser("tree_sitter_python")
        tree = parser.parse_bytes(b"def broken(:\n  pass")
        assert tree.root_node.has_error

    def test_parse_nonexistent_file(self) -> None:
        parser = SourceParser("tree_sitter_python")
        with pytest.raises(DiscoveryError) as exc:
            parser.parse_file(Path("nonexistent_12345.py"))
        assert exc.value.code == DiscoveryError.code
```

#### 11f. Update TestMatchExtractor

Replace `NodeType.X` with string literals:

```python
class TestMatchExtractor:
    def test_extract_from_sample(self) -> None:
        parser = SourceParser("tree_sitter_python")
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("src/remora/queries"),
            "python",
            "remora_core",
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        assert len(nodes) >= 4

        node_types = {n.node_type for n in nodes}
        assert "file" in node_types
        assert "class" in node_types
        assert "method" in node_types
        assert "function" in node_types

    def test_method_has_full_name(self) -> None:
        parser = SourceParser("tree_sitter_python")
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("src/remora/queries"),
            "python",
            "remora_core",
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        method_nodes = [n for n in nodes if n.node_type == "method"]
        assert len(method_nodes) == 1
        assert method_nodes[0].name == "greet"
        # Note: full_name no longer includes class prefix automatically
        # The .scm query just captures the method name

    def test_function_not_method(self) -> None:
        parser = SourceParser("tree_sitter_python")
        loader = QueryLoader()
        extractor = MatchExtractor()

        tree, source = parser.parse_file(SAMPLE_PY)
        queries = loader.load_query_pack(
            Path("src/remora/queries"),
            "python",
            "remora_core",
        )
        nodes = extractor.extract(SAMPLE_PY, tree, source, queries)

        function_nodes = [n for n in nodes if n.node_type == "function"]
        assert len(function_nodes) == 1
        assert function_nodes[0].name == "add"
```

#### 11g. Update TestTreeSitterDiscoverer

Remove the `language` parameter:

```python
class TestTreeSitterDiscoverer:
    def test_discover_from_directory(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[FIXTURE_DIR],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        assert len(nodes) >= 4

        sample_nodes = [n for n in nodes if n.file_path.name == "sample.py"]
        assert len(sample_nodes) >= 4

        node_types = {n.node_type for n in sample_nodes}
        assert "file" in node_types
        assert "class" in node_types
        assert "method" in node_types
        assert "function" in node_types

    def test_discover_from_single_file(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_PY],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        assert len(nodes) >= 4
        assert all(n.file_path == SAMPLE_PY for n in nodes)

    # ... update all other tests similarly, removing language="python" parameter
```

#### 11h. Update sorting assertions

Since `node_type` is now a string, update the sorting key in assertions if needed:

**Before:**
```python
nodes.sort(key=lambda n: (str(n.file_path), n.start_byte, n.node_type.value, n.name))
```

**After:**
```python
nodes.sort(key=lambda n: (str(n.file_path), n.start_byte, n.node_type, n.name))
```

---

### Step 12: Update discovery/__init__.py exports

**File:** `src/remora/discovery/__init__.py`

Since `NodeType` is now a type alias (not a class), we should keep the export but it's now just `str`:

```python
"""Tree-sitter backed node discovery for Remora."""

from remora.discovery.discoverer import TreeSitterDiscoverer
from remora.discovery.match_extractor import MatchExtractor
from remora.discovery.models import CSTNode, DiscoveryError, NodeType, compute_node_id
from remora.discovery.query_loader import CompiledQuery, QueryLoader
from remora.discovery.source_parser import SourceParser

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

No changes needed - `NodeType` is still exported, it's just now `str` instead of an enum.

---

### Step 13: Create Test Fixtures

#### 13a. Create sample.toml

**File:** `tests/fixtures/sample.toml`

```toml
[project]
name = "sample"
version = "1.0.0"

[tool.pytest]
addopts = "-v"

[tool.ruff]
line-length = 100

[[tool.mypy.overrides]]
module = "tests.*"
ignore_errors = true

[[servers]]
name = "alpha"
port = 8080
```

#### 13b. Create sample.md

**File:** `tests/fixtures/sample.md`

```markdown
# Sample Document

This is a sample markdown file for testing.

## Introduction

Some introductory text here.

### Subsection

More details in the subsection.

## Code Examples

Here's some code:

```python
def hello():
    print("Hello, world!")
```

## Conclusion

That's all folks!


---

### Step 14: Add Multi-Language Tests

**File:** `tests/test_discovery.py`

Add new test classes for TOML and Markdown:

```python
SAMPLE_TOML = FIXTURE_DIR / "sample.toml"
SAMPLE_MD = FIXTURE_DIR / "sample.md"


class TestTOMLDiscovery:
    def test_parse_toml_file(self) -> None:
        parser = SourceParser("tree_sitter_toml")
        tree, source = parser.parse_file(SAMPLE_TOML)
        assert tree.root_node.type == "document"

    def test_discover_toml_tables(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_TOML],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        node_types = {n.node_type for n in nodes}
        assert "file" in node_types
        assert "table" in node_types

        table_nodes = [n for n in nodes if n.node_type == "table"]
        table_names = {n.name for n in table_nodes}
        assert "project" in table_names

    def test_discover_array_tables(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_TOML],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        array_table_nodes = [n for n in nodes if n.node_type == "array_table"]
        assert len(array_table_nodes) >= 1


class TestMarkdownDiscovery:
    def test_parse_markdown_file(self) -> None:
        parser = SourceParser("tree_sitter_markdown")
        tree, source = parser.parse_file(SAMPLE_MD)
        assert tree.root_node.type == "document"

    def test_discover_markdown_sections(self) -> None:
        discoverer = TreeSitterDiscoverer(
            root_dirs=[SAMPLE_MD],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        node_types = {n.node_type for n in nodes}
        assert "file" in node_types
        assert "section" in node_types

        section_nodes = [n for n in nodes if n.node_type == "section"]
        section_names = {n.name for n in section_nodes}
        assert "Sample Document" in section_names or any("Sample" in name for name in section_names)


class TestMultiLanguageDiscovery:
    def test_discover_mixed_directory(self) -> None:
        """Test discovering from a directory with multiple file types."""
        discoverer = TreeSitterDiscoverer(
            root_dirs=[FIXTURE_DIR],
            query_pack="remora_core",
        )
        nodes = discoverer.discover()

        # Should have nodes from multiple languages
        extensions = {n.file_path.suffix for n in nodes}
        assert ".py" in extensions
        # Note: .toml and .md only included if query packs exist
```

---

### Step 15: Update DiscoveryConfig (Optional Enhancement)

**File:** `src/remora/config.py`

The `DiscoveryConfig.language` field is no longer needed since we process all languages. You can either:

**Option A: Remove it entirely** (breaking change for existing configs):
```python
class DiscoveryConfig(BaseModel):
    query_pack: str = "remora_core"
    query_dir: Path | None = None
```

**Option B: Keep it but deprecate** (backwards compatible):
```python
class DiscoveryConfig(BaseModel):
    language: str = "python"  # Deprecated: all languages are now discovered
    query_pack: str = "remora_core"
    query_dir: Path | None = None
```

For this refactor, **we will choose Option A** since we don't care about backwards compatibility.

---

### Step 16: Final Validation

Run the full test suite:

```bash
# Run all tests
pytest tests/test_discovery.py -v

# Type check
mypy src/remora/discovery/

# Format check
ruff check src/remora/discovery/
ruff format src/remora/discovery/ --check

# Integration test: discover from multiple languages
python -c "
from pathlib import Path
from remora.discovery import TreeSitterDiscoverer

discoverer = TreeSitterDiscoverer(root_dirs=[Path('tests/fixtures')])
nodes = discoverer.discover()

print(f'Discovered {len(nodes)} nodes:')
for n in nodes:
    print(f'  {n.node_type}: {n.name} ({n.file_path.name})')
"
```

Expected output should include:
- Python: `file`, `class`, `method`, `function`
- TOML: `file`, `table`, `array_table`
- Markdown: `file`, `section`, `code_block`

---

## Verification Checklist

| Test | Expected Result |
|------|-----------------|
| `NodeType` is `str` | `type(NodeType) == type` and `NodeType == str` |
| Parse Python method | `node_type="method"`, `name="greet"` |
| Parse Python function | `node_type="function"`, `name="add"` |
| Parse `[project]` table | `node_type="table"`, `name="project"` |
| Parse `[tool.pytest]` table | `node_type="table"`, `name="tool.pytest"` |
| Parse `[[array]]` table | `node_type="array_table"` |
| Parse `# Title` | `node_type="section"`, `name="Title"` |
| Mixed directory discovery | Returns nodes from `.py`, `.toml`, `.md` |
| All existing tests pass | `pytest tests/test_discovery.py` green |

---

## Troubleshooting

### "Failed to import grammar module"
- Ensure the grammar module is installed: `pip install tree-sitter-toml`
- Check the module name matches exactly (e.g., `tree_sitter_toml` not `tree-sitter-toml`)

### "Query pack directory not found"
- Create the directory structure: `src/remora/queries/{language}/remora_core/`
- Ensure at least one `.scm` file exists in the directory

### "Query syntax error"
- Validate your `.scm` file syntax
- Check node type names match the tree-sitter grammar (use `tree-sitter parse` to inspect)

### Methods captured as functions
- Ensure the method query comes BEFORE the function query in `function.scm`
- Verify the nested pattern syntax is correct

### Wrong TOML node names
- Remember: tree-sitter-toml uses `table_array_element`, not `array_table` for the node type
- The capture name `@array_table.def` is what determines our node type, not the tree-sitter node type

---

## Adding a New Language

After this refactor, adding support for a new language requires only:

1. **Add dependency** to `pyproject.toml`:
   ```toml
   "tree-sitter-rust",
   ```

2. **Add to LANGUAGES** in `src/remora/config.py`:
   ```python
   LANGUAGES: dict[str, str] = {
       ...
       ".rs": "tree_sitter_rust",
   }
   ```

3. **Create query pack** at `src/remora/queries/rust/remora_core/`:
   - `file.scm` - Document/module capture
   - `function.scm` - Function/method captures
   - etc.

No Python code changes required!

---

## Architecture Benefits

1. **Single Source of Truth**: `.scm` files define all extraction logic
2. **Zero Python Logic**: No language-specific AST walking in Python
3. **Trivial Extensibility**: New language = config line + `.scm` files
4. **Type Flexibility**: String node types allow unlimited categories
5. **Cleaner Codebase**: `MatchExtractor` shrinks from 184 to ~80 lines
6. **Better Separation**: Parsing (tree-sitter) vs extraction (.scm) vs orchestration (Python)
