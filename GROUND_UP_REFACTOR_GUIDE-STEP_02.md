# GROUND_UP_REFACTOR_GUIDE-STEP_02.md

## Implementation Guide for Step 2: Discovery Consolidation

**Reference Document:** `.context/GROUND_UP_REFACTOR_IDEAS.md` (Idea 9)

---

## Overview

This step consolidates the 5-file `discovery/` package into a single focused `discovery.py` module. The goal is to reduce complexity while preserving all existing functionality. This is a **consolidation, not a rewrite** — the tree-sitter parsing logic must remain identical.

---

## What This Step Does

### Current State (5 Files)

```
src/remora/discovery/
├── __init__.py         # Re-exports all submodules
├── discoverer.py       # TreeSitterDiscoverer class (180 lines)
├── models.py           # CSTNode dataclass, compute_node_id (57 lines)
├── match_extractor.py  # MatchExtractor class (140 lines)
├── query_loader.py     # QueryLoader, CompiledQuery (114 lines)
└── source_parser.py    # SourceParser class (78 lines)
```

### Target State (1 File + queries/ directory)

```
src/remora/
├── discovery.py        # Single consolidated module (~250 lines)
└── queries/            # .scm files (UNCHANGED)
```

---

## Implementation Plan

### Phase 1: Create `src/remora/discovery.py`

Create a new file consolidating all logic from the 5 files. The structure should be:

```python
# src/remora/discovery.py
"""
Tree-sitter backed node discovery for Remora.

This module consolidates discovery functionality from the former discovery/ package.
Provides CSTNode dataclass and discover() function for scanning source code.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.resources
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from tree_sitter import Language, Parser, Query, QueryCursor, Tree

from remora.config import LANGUAGES
from remora.errors import DiscoveryError as BaseDiscoveryError

logger = logging.getLogger(__name__)

# ============================================================================
# Data Models
# ============================================================================

NodeType = str


class DiscoveryError(BaseDiscoveryError):
    pass


def compute_node_id(file_path: Path, node_type: NodeType, name: str) -> str:
    """Compute a stable node ID.
    
    Hash: sha256(resolved_file_path:node_type:name), truncated to 16 hex chars.
    Stable across reformatting because it does NOT include byte offsets.
    """
    digest_input = f"{file_path.resolve()}:{node_type}:{name}".encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class CSTNode:
    """A discovered code node (file, class, function, or method).
    
    This is a frozen dataclass with slots — instances are immutable after creation.
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
    _full_name: str = ""
    
    def __post_init__(self) -> None:
        if not self._full_name:
            object.__setattr__(self, "_full_name", self.name)
    
    @property
    def full_name(self) -> str:
        return self._full_name


# ============================================================================
# Query Loading (from query_loader.py)
# ============================================================================

class CompiledQuery:
    """A compiled tree-sitter query with metadata."""
    
    def __init__(self, query: Query, source_file: Path, query_text: str, query_name: str) -> None:
        self.query = query
        self.source_file = source_file
        self.query_text = query_text
        self._query_name = query_name
    
    @property
    def name(self) -> str:
        return self._query_name


def _load_queries(query_dir: Path, language: str, query_pack: str) -> list[CompiledQuery]:
    """Load and compile .scm query files for a language/pack combination."""
    pack_dir = query_dir / language / query_pack
    if not pack_dir.is_dir():
        raise DiscoveryError(f"Query pack directory not found: {pack_dir}")
    
    scm_files = sorted(pack_dir.glob("*.scm"))
    if not scm_files:
        raise DiscoveryError(f"No .scm query files found in: {pack_dir}")
    
    grammar_module = f"tree_sitter_{language}"
    try:
        grammar_pkg = importlib.import_module(grammar_module)
    except ImportError as exc:
        raise DiscoveryError(f"Failed to import grammar module: {grammar_module}") from exc
    
    ts_language = Language(grammar_pkg.language())
    
    compiled: list[CompiledQuery] = []
    for scm_file in scm_files:
        compiled.append(_compile_query(scm_file, ts_language))
    
    logger.info(
        "Loaded %d queries from %s/%s: %s",
        len(compiled),
        language,
        query_pack,
        [q.name for q in compiled],
    )
    return compiled


def _compile_query(scm_file: Path, ts_language: Language) -> CompiledQuery:
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


# ============================================================================
# Source Parsing (from source_parser.py)
# ============================================================================

class SourceParser:
    """Parses source files into tree-sitter Trees."""
    
    def __init__(self, grammar_module: str) -> None:
        try:
            grammar_pkg = importlib.import_module(grammar_module)
        except ImportError as exc:
            raise DiscoveryError(f"Failed to import grammar module: {grammar_module}") from exc
        
        self._language = Language(grammar_pkg.language())
        self._parser = Parser(self._language)
        self._grammar_module = grammar_module
    
    @property
    def language(self) -> Language:
        return self._language
    
    def parse_file(self, file_path: Path) -> tuple[Tree, bytes]:
        """Parse a source file and return (tree, source_bytes)."""
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
        """Parse raw bytes and return a tree-sitter Tree."""
        return self._parser.parse(source_bytes)


# ============================================================================
# Match Extraction (from match_extractor.py)
# ============================================================================

def _extract_matches(
    file_path: Path,
    tree: Tree,
    source_bytes: bytes,
    queries: list[CompiledQuery],
) -> list[CSTNode]:
    """Run queries against a tree and extract CSTNodes."""
    nodes: list[CSTNode] = []
    seen_ids: set[str] = set()
    
    for compiled_query in queries:
        new_nodes = _run_single_query(file_path, tree, source_bytes, compiled_query)
        for node in new_nodes:
            if node.node_id not in seen_ids:
                seen_ids.add(node.node_id)
                nodes.append(node)
    
    nodes.sort(key=lambda n: (str(n.file_path), n.start_byte, n.node_type, n.name))
    return nodes


def _run_single_query(
    file_path: Path,
    tree: Tree,
    source_bytes: bytes,
    compiled_query: CompiledQuery,
) -> list[CSTNode]:
    """Run a single query and extract CSTNodes from matches."""
    cursor = QueryCursor(compiled_query.query)
    nodes: list[CSTNode] = []
    
    for match in cursor.matches(tree.root_node):
        captures_by_prefix: dict[str, dict[str, list]] = {}
        
        for capture_name, ts_nodes in match[1].items():
            parts = capture_name.split(".")
            if len(parts) != 2:
                continue
            
            prefix, suffix = parts
            if prefix not in captures_by_prefix:
                captures_by_prefix[prefix] = {}
            if suffix not in captures_by_prefix[prefix]:
                captures_by_prefix[prefix][suffix] = []
            captures_by_prefix[prefix][suffix].extend(ts_nodes)
        
        for prefix, captures in captures_by_prefix.items():
            def_nodes = captures.get("def", [])
            name_nodes = captures.get("name", [])
            
            for i, def_node in enumerate(def_nodes):
                node_type = prefix
                
                if i < len(name_nodes):
                    name_node = name_nodes[i]
                    name = source_bytes[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")
                elif node_type == "file":
                    name = file_path.stem
                else:
                    name = "unknown"
                
                text = source_bytes[def_node.start_byte : def_node.end_byte].decode("utf-8", errors="replace")
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


# ============================================================================
# Language Detection
# ============================================================================

def _detect_language(file_path: Path, languages: dict[str, str] | None) -> str | None:
    """Detect language from file extension."""
    ext = file_path.suffix
    grammar_module = languages.get(ext) if languages else LANGUAGES.get(ext)
    if grammar_module:
        return grammar_module.replace("tree_sitter_", "")
    return None


# ============================================================================
# File Collection
# ============================================================================

def _collect_files(root_dirs: list[Path], extensions: set[str]) -> list[Path]:
    """Walk root_dirs and collect files matching extensions."""
    files: list[Path] = []
    for root in root_dirs:
        if root.is_file() and root.suffix in extensions:
            files.append(root)
        elif root.is_dir():
            for ext in extensions:
                files.extend(sorted(root.rglob(f"*{ext}")))
    return files


# ============================================================================
# Main Discovery Function
# ============================================================================

def _default_query_dir() -> Path:
    """Return the built-in query directory inside the remora package."""
    return Path(importlib.resources.files("remora")) / "queries"


def discover(
    paths: list[Path],
    languages: dict[str, str] | None = None,
    node_types: list[str] | None = None,
    query_pack: str = "remora_core",
    query_dir: Path | None = None,
    max_workers: int = 4,
) -> list[CSTNode]:
    """Scan source paths with tree-sitter and return discovered nodes.
    
    Args:
        paths: Directories or files to scan.
        languages: Override language extension mapping (default: remora.config.LANGUAGES).
        node_types: Filter to specific node types (currently unused, for future).
        query_pack: Query pack name (default: "remora_core").
        query_dir: Custom query directory (default: built-in queries).
        max_workers: Thread pool size for parallel parsing.
    
    Returns:
        Deduplicated, sorted list of CSTNode instances.
    
    Usage:
        nodes = discover([Path("./src")])
        nodes = discover([Path("./src")], languages={".py": "tree_sitter_python"})
    """
    languages = languages or LANGUAGES
    query_dir = query_dir or _default_query_dir()
    root_dirs = [Path(p).resolve() for p in paths]
    
    ext_to_language: dict[str, str] = {}
    for ext, grammar_module in languages.items():
        language = grammar_module.replace("tree_sitter_", "")
        ext_to_language[ext] = language
    
    languages_with_queries: dict[str, list[str]] = {}
    for ext, language in ext_to_language.items():
        pack_dir = query_dir / language / query_pack
        if pack_dir.is_dir():
            if language not in languages_with_queries:
                languages_with_queries[language] = []
            languages_with_queries[language].append(ext)
    
    all_nodes: list[CSTNode] = []
    
    for language, extensions in languages_with_queries.items():
        grammar_module = f"tree_sitter_{language}"
        files = _collect_files(root_dirs, set(extensions))
        
        if not files:
            continue
        
        try:
            queries = _load_queries(query_dir, language, query_pack)
        except DiscoveryError as e:
            logger.warning("Skipping language %s: %s", language, e)
            continue
        
        def _parse_single(file_path: Path) -> list[CSTNode]:
            try:
                parser = SourceParser(grammar_module)
                tree, source_bytes = parser.parse_file(file_path)
                return _extract_matches(file_path, tree, source_bytes, queries)
            except DiscoveryError:
                logger.warning("Skipping %s due to parse error", file_path)
                return []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results_generator = executor.map(_parse_single, files)
            for nodes in results_generator:
                all_nodes.extend(nodes)
    
    seen_ids: set[str] = set()
    unique_nodes: list[CSTNode] = []
    for node in all_nodes:
        if node.node_id not in seen_ids:
            seen_ids.add(node.node_id)
            unique_nodes.append(node)
    
    unique_nodes.sort(key=lambda n: (str(n.file_path), n.start_byte, n.node_type, n.name))
    return unique_nodes


# ============================================================================
# Backward Compatibility: Keep TreeSitterDiscoverer for existing code
# ============================================================================

class TreeSitterDiscoverer:
    """Backward-compatible wrapper that uses the new discover() function."""
    
    def __init__(
        self,
        root_dirs: Iterable[Path: str = "remora_core",
],
        query_pack        *,
        query_dir: Path | None = None,
        event_emitter=None,
        languages: dict[str, str] | None = None,
    ) -> None:
        self.root_dirs = [Path(p).resolve() for p in root_dirs]
        self.query_pack = query_pack
        self.query_dir = query_dir or _default_query_dir()
        self.event_emitter = event_emitter
        self._languages = languages or LANGUAGES
    
    def discover(self) -> list[CSTNode]:
        return discover(
            paths=self.root_dirs,
            languages=self._languages,
            query_pack=self.query_pack,
            query_dir=self.query_dir,
        )
    
    def _collect_files(self, extensions: set[str]) -> list[Path]:
        return _collect_files(self.root_dirs, extensions)
```

### Phase 2: Update Imports in `remora/__init__.py`

The main `__init__.py` should import from the new consolidated module:

```python
# Update this line in src/remora/__init__.py
from remora.discovery import CSTNode, TreeSitterDiscoverer, discover
```

### Phase 3: Delete the Old Package

After confirming all imports work:

```bash
rm -rf src/remora/discovery/
```

### Phase 4: Update All Files That Import from `remora.discovery`

Update imports in these files to use `remora.discovery` (not `remora.discovery.*`):

| File | Old Import | New Import |
|------|------------|------------|
| `src/remora/__init__.py` | `from remora.discovery import` | `from remora.discovery import` |
| `src/remora/agent_graph.py` | `from remora.discovery.discoverer import` | `from remora.discovery import` |
| `tests/test_discovery.py` | `from remora.discovery import (` | `from remora.discovery import (` |
| `tests/test_properties.py` | `from remora.discovery import compute_node_id` | `from remora.discovery import compute_node_id` |
| `tests/benchmarks/test_discovery_performance.py` | `from remora.discovery import` | `from remora.discovery import` |
| `tests/roundtrip/run_harness.py` | `from remora.discovery import` | `from remora.discovery import` |
| `scripts/ast_summary_demo.py` | `from remora.discovery.source_parser import` | `from remora.discovery import SourceParser` |
| `scripts/remora_demo.py` | `from remora.discovery import` | `from remora.discovery import` |
| `scripts/stress_vllm.py` | `from remora.discovery import` | `from remora.discovery import` |

---

## Key Changes from Original Code

1. **`CSTNode` dataclass**: Added `slots=True` for memory efficiency (per Idea 9)
2. **Function-based API**: New `discover()` function as the primary API (stateless, works better with refactored graph system)
3. **Backward compatibility**: `TreeSitterDiscoverer` class kept as wrapper for existing code
4. **Private functions**: All internal functions prefixed with `_` (`_load_queries`, `_extract_matches`, etc.)
5. **DiscoveryError**: Subclass of `remora.errors.DiscoveryError` maintained

---

## What to Preserve

- All tree-sitter parsing logic (identical behavior)
- Multi-language support (.py, .pyi, .toml, .md)
- Thread pool for parallel processing (`concurrent.futures.ThreadPoolExecutor`)
- SHA256-based deterministic node IDs
- Custom `.scm` query files in `queries/` directory
- Language auto-detection from file extensions

---

## Verification Commands

```bash
# Test basic import
python -c "from remora import discover, CSTNode; print('OK')"

# Test backward-compatible class
python -c "from remora import TreeSitterDiscoverer; print('OK')"

# Run discovery tests (if they exist)
python -m pytest tests/test_discovery.py -v

# Run property tests (tests compute_node_id)
python -m pytest tests/test_properties.py -v

# Run benchmark tests
python -m pytest tests/benchmarks/test_discovery_performance.py -v
```

---

## Common Pitfalls

1. **Don't break existing functionality** — this is a consolidation, not a rewrite. Run all existing tests before considering this complete.

2. **Preserve imports** — many files import specific classes like `SourceParser`, `QueryLoader`, etc. Either:
   - Re-export them from `discovery.py`, OR
   - Update all importing files (more work now, cleaner long-term)

3. **Keep language detection working** — the `LANGUAGES` dict from `config.py` must be used

4. **Thread pool should default to 4 workers** — as per the current `TreeSitterDiscoverer`

5. **Queries directory must remain accessible** — use `importlib.resources` to find it inside the package

---

## Files to Modify

| Action | File |
|--------|------|
| CREATE | `src/remora/discovery.py` |
| MODIFY | `src/remora/__init__.py` |
| DELETE | `src/remora/discovery/` directory |
| MODIFY | `src/remora/agent_graph.py` |
| MODIFY | `tests/test_discovery.py` |
| MODIFY | `tests/test_properties.py` |
| MODIFY | `tests/benchmarks/test_discovery_performance.py` |
| MODIFY | `tests/roundtrip/run_harness.py` |
| MODIFY | `scripts/ast_summary_demo.py` |
| MODIFY | `scripts/remora_demo.py` |
| MODIFY | `scripts/stress_vllm.py` |

---

## Dependencies (Unchanged)

- `tree-sitter` (existing)
- `tree-sitter-languages` (existing)
- `pathlib` (stdlib)
- `concurrent.futures` (stdlib)
- `importlib.resources` (stdlib)

---

## Estimated Lines

- Original: ~569 lines (5 files)
- New: ~320 lines (1 file)
- Reduction: ~44%
