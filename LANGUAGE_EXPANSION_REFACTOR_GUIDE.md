# Language Expansion Refactor Guide

## Overview

Add TOML and Markdown tree-sitter language support using per-language NodeType enums.

## Architecture

```
remora/discovery/languages/
├── __init__.py          # LanguageRegistry
├── base.py              # LanguageAdapter ABC
├── python.py            # PythonNodeType, PythonLanguage
├── toml.py              # TomlNodeType, TomlLanguage
├── markdown.py          # MarkdownNodeType, MarkdownLanguage
└── protocols.py         # Typed protocols
```

## Phase 1: Foundation

### Step 1.1: Create base.py
- Define `LanguageAdapter` abstract base class
- Methods: `name`, `file_extensions`, `language`, `node_type_enum`, `get_node_type_prefixes()`
- Test: ABC cannot be instantiated directly

### Step 1.2: Create protocols.py
- Define `TypedNodeType` protocol (str, Enum subclass)
- Define `ParsableLanguage` protocol
- Test: Protocol validation with mypy

## Phase 2: Migrate Python

### Step 2.1: Create python.py
- Define `PythonNodeType(str, Enum)` with FILE, CLASS, FUNCTION, METHOD
- Create `PythonLanguage(LanguageAdapter)` class
- Move logic from `source_parser.py` and `match_extractor.py`
- Test: Parse sample.py, verify all node types are `PythonNodeType`

### Step 2.2: Update models.py
- Make `CSTNode` generic over node type
- Add `NodeType = TypeVar('NodeType', bound=str)`
- Test: CSTNode construction with each language's NodeType

### Step 2.3: Update source_parser.py
- Accept `LanguageAdapter` in constructor
- Add `for_file()` classmethod factory
- Test: Parser constructed via factory for .py files

### Step 2.4: Update query_loader.py
- Accept `LanguageAdapter` instead of language string
- Test: Queries load for Python

### Step 2.5: Update match_extractor.py
- Use `LanguageAdapter.node_type_enum` for type construction
- Test: Extracted nodes have correct PythonNodeType

## Phase 3: Add TOML

### Step 3.1: Add dependency
- Add `tree-sitter-toml>=0.7` to pyproject.toml
- Test: `import tree_sitter_toml` succeeds

### Step 3.2: Create toml.py
- Define `TomlNodeType(str, Enum)`: FILE, TABLE, ARRAY_TABLE, KEY_VALUE
- Create `TomlLanguage(LanguageAdapter)`
- Implement `get_node_type_prefixes()` for TOML nodes
- Test: Adapter properties are correct

### Step 3.3: Create queries/toml/remora_core/
- file.scm: `(document) @file.def`
- table.scm: `(table (bare_key) @table.name) @table.def`
- Test: Queries compile without error

### Step 3.4: Update LanguageRegistry
- Register TomlLanguage for `.toml` extension
- Test: `registry.get_for_extension('.toml')` returns TomlLanguage

### Step 3.5: Integration test
- Parse sample pyproject.toml
- Verify TABLE nodes extracted with correct names
- Test: `[project]` table has name "project"

## Phase 4: Add Markdown

### Step 4.1: Add dependency
- Add `tree-sitter-markdown>=0.5` to pyproject.toml
- Test: `import tree_sitter_markdown` succeeds

### Step 4.2: Create markdown.py
- Define `MarkdownNodeType(str, Enum)`: FILE, SECTION, PARAGRAPH, CODE_BLOCK, LIST
- Create `MarkdownLanguage(LanguageAdapter)`
- Test: Adapter properties are correct

### Step 4.3: Create queries/markdown/remora_core/
- file.scm: `(document) @file.def`
- section.scm: `(atx_heading) @section.def`
- Test: Queries compile without error

### Step 4.4: Update LanguageRegistry
- Register MarkdownLanguage for `.md`, `.markdown`
- Test: `registry.get_for_extension('.md')` returns MarkdownLanguage

### Step 4.5: Integration test
- Parse sample README.md
- Verify SECTION nodes for headings
- Test: `# Title` creates SECTION node

## Phase 5: Update Discoverer

### Step 5.1: Refactor TreeSitterDiscoverer
- Accept list of `LanguageAdapter` instances
- Auto-detect language per file via registry
- Test: Discover both .py and .toml files in mixed directory

### Step 5.2: Update config.py
- Add `languages: list[str]` to DiscoveryConfig
- Default to ["python", "toml", "markdown"]
- Test: Config loads with new field

## Phase 6: Final Validation

### Step 6.1: Run all existing tests
- Ensure no regressions
- Test: `pytest tests/` passes

### Step 6.2: Type checking
- Run mypy with strict mode
- Test: `mypy src/remora` passes

### Step 6.3: New test coverage
- Create test_languages.py
- Test all three language adapters
- Test CSTNode with each NodeType enum

## File Checklist

**Create:**
- src/remora/discovery/languages/__init__.py
- src/remora/discovery/languages/base.py
- src/remora/discovery/languages/protocols.py
- src/remora/discovery/languages/python.py
- src/remora/discovery/languages/toml.py
- src/remora/discovery/languages/markdown.py
- src/remora/queries/toml/remora_core/file.scm
- src/remora/queries/toml/remora_core/table.scm
- src/remora/queries/markdown/remora_core/file.scm
- src/remora/queries/markdown/remora_core/section.scm
- tests/test_languages.py
- tests/fixtures/sample.toml
- tests/fixtures/sample.md

**Modify:**
- pyproject.toml (add dependencies)
- src/remora/discovery/models.py (generic CSTNode)
- src/remora/discovery/source_parser.py (multi-language)
- src/remora/discovery/query_loader.py (LanguageAdapter)
- src/remora/discovery/match_extractor.py (use adapter)
- src/remora/discovery/discoverer.py (auto-detect)
- src/remora/config.py (languages config)
