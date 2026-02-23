# Language Expansion Refactor Plan

This document outlines architectural strategies for expanding Remora's `discovery` module from a strictly Python-centric Tree-sitter parser to a generic, elegant, multi-language parser capable of driving the AST_MOMENTUM generative features.

**Core Philosophy:** We do not care about backwards compatibility or ease of implementation. The goal is the cleanest, most extensible object-oriented design possible.

---

## The Current State vs. the Ideal State

**Current State (Hardcoded):**
- `SourceParser` hardcodes `PY_LANGUAGE` via `tree-sitter-python`.
- `QueryLoader` hardcodes `PY_LANGUAGE`.
- `TreeSitterDiscoverer` hardcodes `.py` file extension discovery.
- `MatchExtractor` uses a hardcoded `_PREFIX_TO_NODE_TYPE` static dict (`"@class.def" -> NodeType.CLASS`).

**Ideal State (Generic & Polymorphic):**
- The core discovery classes (`SourceParser`, `QueryLoader`, `MatchExtractor`) should know **nothing** about specific languages, extensions, or grammar specifics.
- Adding a new language (e.g., Markdown, Rust, TOML) should involve registering a unified `LanguageDefinition` object (or subclass) and dropping `.scm` queries into the correct folder. There should be exactly zero `if language == "python":` logic in the core pipeline.

---

## Option 1: The Unified Language Registry Pattern (Recommended)

In this approach, we define a formal `LanguageDialect` or `LanguageDefinition` interface. Each language provides its Tree-sitter bindings, its file extensions, and its specific AST-node mapping logic inside an encapsulated class. The core `discovery` module simply queries a `LanguageRegistry`.

### Example Architecture

```python
class LanguageDialect(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @property
    @abstractmethod
    def tree_sitter_language(self) -> tree_sitter.Language: ...
    
    @property
    @abstractmethod
    def file_extensions(self) -> set[str]: ...
    
    @abstractmethod
    def map_capture_to_node_type(self, capture_name: str) -> NodeType | None:
        """Map generic capture names (@class.def) to NodeTypes."""
        pass
        
    @abstractmethod
    def extract_node_name(self, ts_node: tree_sitter.Node, source_bytes: bytes) -> str | None:
        """Language-specific logic to extract a human readable name (e.g. from a class_definition)."""
        pass

# Implementations
class PythonDialect(LanguageDialect):
    name = "python"
    tree_sitter_language = Language(tspython.language())
    file_extensions = {".py", ".pyi"}
    # ... implements python specific name extraction and capture mapping ...

class TomlDialect(LanguageDialect):
    name = "toml"
    tree_sitter_language = Language(tstoml.language())
    file_extensions = {".toml"}
    # ... implements TOML specific extraction (e.g. mapping @table.def -> NodeType.TABLE)

# Core usage
class TreeSitterDiscoverer:
    def __init__(self, registry: LanguageRegistry, target_languages: list[str]):
        self.dialects = [registry.get(lang) for lang in target_languages]
```

### Pros:
- **Maximum Cleanliness:** Perfectly separates the standard discovery orchestration from the language-specific nuances (like how Python defines a "method" vs. how TOML defines a "table").
- **Highly Extensible:** Adding a new language strictly involves creating a new subclass representing the dialect, and updating `NodeType` enums. No core logic changes.
- **Dependency Injection Friendly:** The `TreeSitterDiscoverer` only depends on the abstract `LanguageDialect`, making unit testing incredibly clean.

### Cons:
- Highest refactoring overhead upfront. We must touch every file in `src/remora/discovery/`.

---

## Option 2: The Data-Driven Configuration Model

Instead of Polymorphic classes defining how a language behaves, we use a purely data-driven Pydantic configuration file that maps everything.

### Example Architecture

```python
class LanguageConfig(BaseModel):
    name: str
    library_name: str           # e.g., "tree_sitter_python"
    extensions: list[str]
    capture_mappings: dict[str, NodeType]
    name_extraction_queries: dict[NodeType, str] # e.g. "class": "(class_definition name: (identifier) @name)"
```

The system dynamically loads the `tree_sitter` language binding module using `importlib` based on the config. Instead of writing Python logic to parse the `name` out of a node (like traversing parents to see if a function is a method), we use secondary Tree-sitter `.scm` queries defined in the config to generically fetch the name from any node.

### Pros:
- **Zero-Code Extensions**: Adding a new language means appending a JSON/YAML/Pydantic block in a central config file. No new Python classes needed.
- **Enforces Pure AST Searching**: Forces developers to rely exclusively on Tree-sitter queries rather than writing hacky python code to traverse AST nodes to find names.

### Cons:
- **Complexity in Queries**: Extracting names or figuring out complex hierarchical relationships (like Python method vs function) can sometimes be intensely difficult to write cleanly in pure `.scm` queries compared to 5 lines of Python AST traversal.
- **Dynamic Imports**: Using `importlib` to fetch the Tree-sitter `language()` pointer feels slightly less robust than explicit class definitions.

---

## Option 3: The "Smart" Generic Discovery (Relying Entirely on `.scm` Conventions)

In this model, the Python code implements exactly zero language-specific logic. We enforce a strict `.scm` query contract that *every* language must follow.

If the `.scm` file is named `python/tags.scm`, the parser uses `importlib` to load `tree_sitter_python`.
To map NodeTypes, we enforce that captures MUST match the enum exactly: `@node_type.class.def` or `@node_type.file.def`.
To extract names, we enforce that every `*.def` capture MUST be paired with a `*.name` capture in the same logical query grouping.

### Pros:
- The absolute smallest Python footprint. Let the `.scm` files do 100% of the heavy lifting.

### Cons:
- **Fragile `.scm` Files**: Tree-sitter `.scm` files become bloated and highly coupled to Remora's internal Enums.
- **Tough to Debug**: If a node isn't named right, you have to debug complex `.scm` predicate logic instead of dropping a `print()` or debugger into a Python class.

---

## Recommendation: Option 1 (The OOP LanguageDialect Registry)

Given the user mandate for the "best, cleanest, most elegant codebase" prioritizing true object-oriented architecture via Smalltalk-style message passing and explicit context: **Option 1 is the definitive path forward.**

**Why?**
1. It encapsulates the messy reality that every language parses differently.
2. It allows `TreeSitterDiscoverer` to do what it does best: orchestrating files.
3. It allows `MatchExtractor` to say, *"Hey dialect, here's a Tree-sitter node. Tell me its Remora NodeType, and tell me its human-readable name."* This is perfect OOP separation of concerns.

### Refactoring Steps for Option 1:

1. **New Module:** `src/remora/discovery/dialects.py`. Define the `LanguageDialect` base class.
2. **Implement Dialects:** Spin up `PythonDialect`, `TomlDialect`, `MarkdownDialect`.
3. **Refactor `SourceParser`**: Accept a `LanguageDialect` on parse or instantiation.
4. **Refactor `QueryLoader`**: Accept a `LanguageDialect`.
5. **Refactor `MatchExtractor`**: Gut the hardcoded `_classify_function` and `_extract_name_from_node_` methods. Delegate those questions directly to the active `LanguageDialect`.
6. **Refactor `TreeSitterDiscoverer`**: Update the `discover` loop to iterate over registered dialects, grab their specific active extensions, and farm out the parser/extractor accordingly.
