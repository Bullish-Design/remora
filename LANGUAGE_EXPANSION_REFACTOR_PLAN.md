# Language Expansion Refactor Plan

This document outlines architectural strategies for expanding Remora's `discovery` module from a strictly Python-centric Tree-sitter parser to a generic, elegant, multi-language parser capable of driving the AST_MOMENTUM generative features.

**Core Philosophy:** The goal is the absolute best, most elegant, and cleanly maintainable codebase moving forward. We do not care about backwards compatibility or ease of implementation.

---

## 1. The Core Problem: The "Naming" Heuristic
Tree-sitter returns syntax nodes. Remora needs `CSTNode` objects that have a human-readable `name` (e.g. "MyClass.my_method") and a stable `NodeType` (e.g. `NodeType.METHOD`). 

In the current hardcoded Python implementation:
- `NodeType` is determined by hardcoded dictionary mapping: `"@class.def" -> NodeType.CLASS`
- `name` is extracted by specific Python logic:
  - Find a child node literally named "name".
  - If it's a `function_definition`, walk up the AST in Python to see if the parent is a `class_definition`. If so, it's a `METHOD` and prepend the class name.

When we add TOML (e.g., extracting a `[tool.pytest]` table name) or Markdown (e.g., getting the text of an `## H2 Header`), this hardcoded logic completely breaks down.

---

## Option A: Pure Data-Driven Polymorphism (The "Smart Queries" Approach) - Highly Recommended

Instead of using Python to write complex logic for *how* to extract names or classify nodes for different languages, we push 100% of the extraction logic to the `.scm` files and configure the pipeline purely via static data.

If a language can be parsed by Tree-sitter, we should be able to query *everything* we need directly using Tree-sitter queries. 

### Architecture

1. **The Registry Config**: A pure data definition (e.g., built into the config or a `languages.toml`) that defines the parsing capabilities:
```toml
[language.python]
extensions = [".py"]
grammar_module = "tree_sitter_python"

[language.toml]
extensions = [".toml"]
grammar_module = "tree_sitter_toml"
```

2. **The `.scm` Contract**: The python engine no longer tries to guess relationships. It enforces a strict grammar on the `.scm` files themselves. 
Every query that identifies a node **must** capture:
- `@node.def`: The full byte-range of the node.
- `@node.name`: The byte-range of the identifier string.

3. **Dynamic Node Typing**: We eliminate the hardcoded `NodeType` enum. If a query file is named `models.scm` and captures `@table.def`, the node type is simply `"table"`.

### Pros:
- **Zero Python Logic**: We never have to write Python AST walking code again. If we want to change how a Markdown header name is extracted, we edit the `markdown/discovery.scm` file.
- **Trivial Extensibility**: Adding a new language is literally just adding 3 lines to a TOML config and writing `.scm` files.
- **Language Agnostic Engine**: `TreeSitterDiscoverer` and `MatchExtractor` become universally applicable to any language Tree-sitter supports.

### Cons:
- Complex naming relationships (like Python's `Class.method` fully qualified name) require writing slightly more advanced `.scm` queries (using overlapping captures or predicates) rather than a simple Python `while node.parent:` loop.

---

## Option B: Object-Oriented `LanguageDialect` Plugins

This is the traditional "Strategy Pattern" approach. We define an abstract `LanguageDialect` interface, and each language implements its own python class to handle the quirks of its AST.

### Architecture

```python
class LanguageDialect(ABC):
    name: str
    extensions: tuple[str, ...]
    
    @abstractmethod
    def get_parser(self) -> tree_sitter.Language: ...
    
    @abstractmethod
    def extract_node_data(self, capture_name: str, ts_node: Node, source_bytes: bytes) -> tuple[str, str]:
        """Returns (NodeType, NodeName) using whatever python logic the language needs."""
```

### Pros:
- **Familiar Pattern**: Standard gang-of-four dependency injection.
- **Handles Edge Cases Easily**: If a language has a bizarre quirk that is hard to capture in `.scm`, you have the full power of Python to walk the AST to figure it out.

### Cons:
- **Heavier Footprint**: Every new language requires shipping and maintaining a new Python class file, rather than just `.scm` files.
- **Leaky Abstraction**: Mixing Tree-sitter `.scm` logic for discovery with Python logic for extraction means the "truth" of how a node is parsed is split across two domains.

---

## Option C: The Callback / Hook System

A middle-ground where the core engine uses `.scm` for everything, but allows languages to register arbitrary Python callback hooks to mutate the `CSTNode` right after it's birthed.

```python
def python_method_hook(node: CSTNode, ts_node: Node_ tree: Tree) -> CSTNode:
    # Walk the tree, if parent is class, prepend name and change type.
    pass

EXTRACTOR_HOOKS = {
    "python": [python_method_hook]
}
```

### Pros:
- Keeps the core engine agnostic but provides an escape hatch.

### Cons:
- Action-at-a-distance. Hooks make it very hard to trace why a node was named a certain way or why its type changed.

---

## Recommendation: Option A (Pure Data-Driven "Smart Queries")

If we want the *best* and most elegant architecture moving forward, **Option A is the clear winner.**

We should push Tree-sitter to its limits. By forcing the `.scm` queries to be the sole source of truth for both *discovery* and *extraction*, we create a massively cleaner Python layer.

The core pipeline (`MatchExtractor.py`) shrinks significantly. It no longer cares if it's looking at Python, TOML, or Rust. It simply executes a query, looks for a `@X.def` capture, looks for a paired `@X.name` capture, and creates a `CSTNode` of type `X`. 

**The elegance comes from the constraint:** If a language feature cannot be expressed cleanly by capturing its definition and its name in an `.scm` file, it shouldn't be a primitive Node Type in our system.
