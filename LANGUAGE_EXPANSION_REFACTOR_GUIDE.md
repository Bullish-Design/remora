# Language Expansion Refactor Guide (Simplified)

## Core Philosophy

Push all extraction logic to `.scm` files. Make the Python engine completely generic. Use strings instead of enums.

---

## The Three Key Changes

### 1. NodeType = str (not enum)

```python
# src/remora/discovery/models.py
NodeType = str  # Replace enum entirely

@dataclass(frozen=True)
class CSTNode:
    node_type: NodeType = "block"  # Any string
    name: str
    file_path: Path
    start_byte: int
    end_byte: int
    text: str
    start_line: int
    end_line: int
    node_id: str = ""
    _full_name: str = ""
```

### 2. Config-driven language loading

```python
# src/remora/config.py
LANGUAGES: dict[str, str] = {  # extension -> grammar_module
    ".py": "tree_sitter_python",
    ".toml": "tree_sitter_toml",
    ".md": "tree_sitter_markdown",
}
```

### 3. Simplify MatchExtractor (~50 lines)

```python
# src/remora/discovery/match_extractor.py
def _run_query(self, file_path, tree, source_bytes, compiled_query):
    cursor = QueryCursor(compiled_query.query)
    
    nodes = []
    for match_index, captures in cursor.matches(tree.root_node):
        # Find .def and .name captures for this query's pattern
        def_node = captures.get(f"@{self.query_name}.def")
        name_node = captures.get(f"@{self.query_name}.name")
        
        if def_node is None:
            continue
            
        node_type = self.query_name
        name = "unknown"
        
        if name_node:
            name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
        
        text = source_bytes[def_node.start_byte:def_node.end_byte].decode("utf-8", errors="replace")
        
        node_id = compute_node_id(file_path, node_type, name)
        
        nodes.append(CSTNode(
            node_id=node_id,
            node_type=node_type,
            name=name,
            file_path=file_path,
            start_byte=def_node.start_byte,
            end_byte=def_node.end_byte,
            text=text,
            start_line=def_node.start_point.row + 1,
            end_line=def_node.end_point.row + 1,
        ))
    
    return nodes
```

---

## Implementation Steps

### Step 1: Add Dependencies

```toml
# pyproject.toml
dependencies = [
    ...
    "tree-sitter-toml>=0.7",
    "tree-sitter-markdown>=0.5",
]
```

**Test:** `python -c "import tree_sitter_toml; import tree_sitter_markdown"`

---

### Step 2: Refactor models.py

- Replace `NodeType` enum with `NodeType = str`
- Update all references from `NodeType.FUNCTION` to `"function"`
- Update `factories.py` to use string literals

**Test:** `pytest tests/test_discovery.py`

---

### Step 3: Refactor source_parser.py

```python
import importlib
from tree_sitter import Language, Parser

class SourceParser:
    def __init__(self, grammar_module: str) -> None:
        grammar_pkg = importlib.import_module(grammar_module)
        self._language = Language(grammar_pkg.language())
        self._parser = Parser(self._language)
    
    @classmethod
    def for_extension(cls, ext: str) -> "SourceParser | None":
        grammar_module = LANGUAGES.get(ext)
        return cls(grammar_module) if grammar_module else None
```

**Test:** Parse `.py`, `.toml`, `.md` files with appropriate SourceParser

---

### Step 4: Refactor query_loader.py

```python
import importlib
from tree_sitter import Language, Query

class QueryLoader:
    def __init__(self, language: str) -> None:
        self._language_name = language
    
    def load_query_pack(self, query_dir: Path, language: str, query_pack: str):
        grammar_module = f"tree_sitter_{language}"
        grammar_pkg = importlib.import_module(grammar_module)
        language_obj = Language(grammar_pkg.language())
        
        # ... load .scm files and compile with language_obj
```

**Test:** Load queries for python, toml, markdown

---

### Step 5: Simplify match_extractor.py

**Remove:**
- `_PREFIX_TO_NODE_TYPE` dict
- `_extract_name_from_node()` method  
- `_classify_function()` method
- All Python AST walking logic

**Simplify to:**
- Parse capture names directly: `@class.name` → `node_type="class"`
- Extract name from `@X.name` capture
- Return CSTNode with string node_type

**Test:** Parse sample.py, verify node_type is string "function", "class", not enum

---

### Step 6: Update discoverer.py

```python
class TreeSitterDiscoverer:
    def discover(self) -> list[CSTNode]:
        all_nodes = []
        
        for ext, grammar_module in LANGUAGES.items():
            parser = SourceParser(grammar_module)
            loader = QueryLoader(grammar_module.replace("tree_sitter_", ""))
            
            files = self._collect_files({ext})
            queries = loader.load_query_pack(...)
            
            for file_path in files:
                tree, src = parser.parse_file(file_path)
                nodes = extractor.extract(file_path, tree, src, queries)
                all_nodes.extend(nodes)
        
        return all_nodes
```

**Test:** Discover mixed directory with .py, .toml, .md files

---

### Step 7: Rewrite Python .scm files (nested queries)

**Key insight:** Methods must be captured with nested query to distinguish from standalone functions. Order matters!

```scm
; src/remora/queries/python/remora_core/function.scm

; Methods (functions inside classes) - MUST come FIRST
; This nested pattern captures @method.def and @method.name
(class_definition
  body: (block
    (function_definition
      name: (identifier) @method.name
    ) @method.def
  )
)

; Standalone functions - capture @function.def and @function.name
(function_definition
  name: (identifier) @function.name
) @function.def
```

```scm
; src/remora/queries/python/remora_core/class.scm
(class_definition
  name: (identifier) @class.name
) @class.def
```

```scm
; src/remora/queries/python/remora_core/file.scm
(module) @file.def
```

**Test:** Parse sample.py with both standalone functions and class methods. Methods should have `node_type="method"`, not "function".

---

### Step 8: Create TOML .scm files

**Critical:** tree-sitter-toml uses different node types than expected!

| Expected | Actual tree-sitter-toml |
|----------|------------------------|
| `array_table` | `table_array_element` |
| `table` | `table` |

```scm
; src/remora/queries/toml/remora_core/table.scm

; Standard tables: [project], [tool.pytest]
(table
  (bare_key) @table.name
) @table.def

(table
  (dotted_key) @table.name
) @table.def

; Array tables: [[tool.mypy.overrides]]
(table_array_element
  (bare_key) @array_table.name
) @array_table.def

(table_array_element
  (dotted_key) @array_table.name
) @array_table.def
```

```scm
; src/remora/queries/toml/remora_core/file.scm
(document) @file.def
```

**Test:** Parse pyproject.toml with `[project]`, `[tool.pytest]`, `[[tool.mypy.overrides]]`. Verify correct names extracted.

---

### Step 9: Create Markdown .scm files

```scm
; src/remora/queries/markdown/remora_core/section.scm

; ATX headings: # Title, ## Section, etc.
(atx_heading
  (inline) @section.name
) @section.def

; Fenced code blocks
(fenced_code_block
  (info_string) @code_block.lang
) @code_block.def
```

```scm
; src/remora/queries/markdown/remora_core/file.scm
(document) @file.def
```

**Test:** Parse README.md with headings. Verify section names extracted.

---

### Step 10: Final Validation

```bash
# Run all discovery tests
pytest tests/test_discovery.py -v

# Type checking
mypy src/remora/discovery/

# Test multi-language discovery
python -c "
from remora.discovery import TreeSitterDiscoverer
discoverer = TreeSitterDiscoverer(root_dirs=['tests/fixtures'], ...)
nodes = discoverer.discover()
for n in nodes:
    print(f'{n.node_type}: {n.name}')
"
```

---

## File Checklist

### Create (New Files)
- `src/remora/queries/toml/remora_core/file.scm`
- `src/remora/queries/toml/remora_core/table.scm`
- `src/remora/queries/markdown/remora_core/file.scm`
- `src/remora/queries/markdown/remora_core/section.scm`
- `tests/fixtures/sample.toml`
- `tests/fixtures/sample.md`

### Modify (Existing Files)
| File | Change |
|------|--------|
| `pyproject.toml` | Add tree-sitter-toml, tree-sitter-markdown deps |
| `src/remora/config.py` | Add LANGUAGES dict |
| `src/remora/discovery/models.py` | Replace NodeType enum with `NodeType = str` |
| `src/remora/discovery/source_parser.py` | Dynamic language loading via importlib |
| `src/remora/discovery/query_loader.py` | Dynamic language for Query compilation |
| `src/remora/discovery/match_extractor.py` | Simplify to ~50 lines, remove Python AST walking |
| `src/remora/discovery/discoverer.py` | Loop over LANGUAGES config |
| `src/remora/queries/python/remora_core/function.scm` | Add nested query for methods FIRST |
| `tests/test_discovery.py` | Update tests for string NodeType |
| `tests/fixtures/sample.py` | Add class with method for testing |

### Delete (If No Longer Needed)
- `src/remora/discovery/languages/` (if created in old plan - not needed)

---

## Verification Tests

| Test | Expected Result |
|------|-----------------|
| Parse Python with methods | node_type="method", name="greet" |
| Parse Python standalone function | node_type="function", name="add" |
| Parse `[project]` table | node_type="table", name="project" |
| Parse `[tool.pytest]` table | node_type="table", name="tool.pytest" |
| Parse `[[array]]` table | node_type="array_table", name="array" |
| Parse `# Title` | node_type="section", name="Title" |
| Discover mixed directory | Returns nodes from .py, .toml, .md files |
