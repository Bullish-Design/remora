# Structural Tag Integration Exploration

*An exploration of integrating XGrammar's Structural Tags into Remora for enhanced tool calling.*

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current State: EBNF Grammar Approach](#current-state-ebnf-grammar-approach)
3. [What Are Structural Tags?](#what-are-structural-tags)
4. [Potential Benefits](#potential-benefits)
5. [Potential Downsides](#potential-downsides)
6. [Implementation Options](#implementation-options)
7. [FunctionGemma-Specific Considerations](#functiongemma-specific-considerations)
8. [Recommended Approach](#recommended-approach)
9. [Implementation Roadmap](#implementation-roadmap)
10. [Code Examples](#code-examples)

---

## Executive Summary

Structural tags are XGrammar's declarative, JSON-based approach to describing complex output formats. They offer composable building blocks that can enforce sophisticated patterns like "thinking before tool calling" or per-tool JSON schema validation.

**Key question:** Should Remora migrate from its current strict EBNF grammar to structural tags?

**Quick answer:** Structural tags offer compelling benefits for *argument schema enforcement* and *hybrid text+tool patterns*, but introduce complexity and potential risks with small models like FunctionGemma-270M. A phased approach is recommended: keep strict EBNF for format enforcement, optionally layer on structural tags for argument validation.

---

## Current State: EBNF Grammar Approach

### Current Grammar Implementation

Remora's `src/remora/grammar.py` builds a strict EBNF grammar:

```ebnf
root ::= "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>"

tool_name ::= "simple_tool" | "submit_result"

arg_body ::= arg_char*
arg_char ::= [^}]
```

### What This Enforces

| Aspect | Enforced? | Details |
|--------|-----------|---------|
| FunctionGemma format | ✅ Yes | Must match `<start_function_call>call:...<end_function_call>` |
| Tool name enum | ✅ Yes | Only registered tool names allowed |
| No plain text | ✅ Yes | Cannot output non-tool-call content |
| Argument structure | ❌ No | `[^}]*` allows anything except `}` |
| Required keys | ❌ No | No JSON schema validation |
| Value types | ❌ No | String vs number vs boolean not enforced |

### Strengths of Current Approach

1. **Simplicity** - Grammar is ~10 lines, easy to understand and debug
2. **Robustness** - No optional whitespace patterns that confuse small models
3. **100% tool call rate** - Model cannot output plain text
4. **Fast compilation** - Minimal grammar compiles quickly

### Weaknesses of Current Approach

1. **No argument validation** - Model can generate malformed JSON arguments
2. **Post-parse validation required** - Need separate JSON schema validation step
3. **No "thinking" support** - Cannot allow reasoning before tool call
4. **Single tool call only** - Grammar enforces exactly one call per turn

---

## What Are Structural Tags?

Structural tags are XGrammar's declarative format description system. Instead of writing EBNF, you compose Python/JSON objects that describe the expected output structure.

### Core Concepts

1. **Format objects** - Building blocks like `JSONSchemaFormat`, `TagFormat`, `AnyTextFormat`
2. **Composition** - Combine formats with `SequenceFormat`, `OrFormat`
3. **Triggered patterns** - `TriggeredTagsFormat` for "text until trigger, then structured"
4. **Schema enforcement** - `JSONSchemaFormat` enforces JSON schema on content

### The 10 Format Types

| Type | Purpose | Use Case |
|------|---------|----------|
| `const_string` | Exact string match | Force specific prefixes |
| `json_schema` | JSON matching schema | Structured data |
| `grammar` | EBNF grammar | Custom patterns |
| `regex` | Regex pattern | Simple patterns |
| `any_text` | Any text (with exclusions) | Free-form content |
| `sequence` | Match formats in order | Multi-part responses |
| `or` | Match one of formats | Alternative patterns |
| `tag` | `begin content end` pattern | XML-style tags |
| `triggered_tags` | Free text until trigger | Tool calling with preamble |
| `tags_with_separator` | Tags with delimiter | Multiple structured items |

### How Structural Tags Work

XGrammar compiles structural tags to internal grammar representation. The key insight is that structural tags handle **token boundary issues** automatically.

**The Token Boundary Problem:**

When you write EBNF like:
```ebnf
root ::= "<start_function_call>" ...
```

The tokenizer might split `<start_function_call>` across multiple tokens:
- Token 1: `<start`
- Token 2: `_function`
- Token 3: `_call>`

XGrammar handles this internally, but structural tags make it explicit and type-safe.

---

## Potential Benefits

### 1. Per-Tool Argument Schema Enforcement

**Current limitation:** Arguments are `[^}]*` - anything except closing brace.

**With structural tags:**
```python
TagFormat(
    begin="<start_function_call>call:get_weather{",
    content=JSONSchemaFormat(
        json_schema={
            "type": "object",
            "properties": {"location": {"type": "string"}},
            "required": ["location"],
            "additionalProperties": False
        }
    ),
    end="}<end_function_call>",
)
```

**Benefit:** Model cannot generate tool call without required `location` key.

### 2. Hybrid Text + Tool Patterns

**Current limitation:** Model must immediately produce tool call.

**With structural tags:**
```python
SequenceFormat(elements=[
    TagFormat(
        begin="<think>",
        content=AnyTextFormat(excludes=["</think>"]),
        end="</think>",
    ),
    TriggeredTagsFormat(
        triggers=["<start_function_call>"],
        tags=[...tool tags...],
        at_least_one=True,
    ),
])
```

**Benefit:** Model can "think" before calling tool, potentially improving reasoning.

### 3. Multiple Tool Calls Per Turn

**Current limitation:** Grammar enforces exactly one tool call.

**With structural tags:**
```python
TriggeredTagsFormat(
    triggers=["<start_function_call>call:"],
    tags=[...],
    at_least_one=False,
    stop_after_first=False,  # Allow multiple
)
```

**Benefit:** Model can call multiple tools in one turn (e.g., parallel operations).

### 4. Type-Safe Grammar Building

**Current approach:** String concatenation prone to errors.

**With structural tags:**
```python
# Validated at construction time
StructuralTag(
    format=TagFormat(
        begin="<start_function_call>call:my_tool{",
        content=JSONSchemaFormat(json_schema=MyToolArgs.model_json_schema()),
        end="}<end_function_call>",
    )
)
```

**Benefit:** Pydantic validates structure, IDE provides autocomplete.

### 5. Model-Agnostic Format Descriptions

Structural tags support different "styles" for different model families:

```python
JSONSchemaFormat(
    json_schema=schema,
    style="json",        # Standard JSON
    # style="qwen_xml",  # Qwen <parameter=key>value</parameter>
    # style="deepseek_xml",  # DeepSeek XML format
)
```

**Benefit:** Same schema works across model formats.

### 6. Explicit Constraint Documentation

Structural tags serve as self-documenting format specifications:

```python
StructuralTag(
    format=SequenceFormat(elements=[
        ConstStringFormat(value="Analyzing the request...\n"),
        TagFormat(begin="<reasoning>", content=AnyTextFormat(), end="</reasoning>"),
        TagFormat(begin="<action>", content=JSONSchemaFormat(...), end="</action>"),
    ])
)
```

**Benefit:** Format requirements are explicit in code, not buried in EBNF.

---

## Potential Downsides

### 1. Complexity for Small Models

**Risk:** FunctionGemma-270M is a small model. Complex structural constraints may:
- Reduce generation quality
- Cause unexpected behaviors
- Increase latency from more complex grammar matching

**Evidence:** We already saw issues with `ws?` (optional whitespace) causing degenerate outputs.

**Mitigation:** Use minimal structural tags, avoid optional patterns.

### 2. Debugging Difficulty

**Current:** EBNF is human-readable, easy to test with string matching.

**With structural tags:** Complex nested object graph harder to debug.

```python
# What grammar does this compile to?
StructuralTag(
    format=TriggeredTagsFormat(
        triggers=["<start_function_call>call:"],
        tags=[
            TagFormat(
                begin="<start_function_call>call:tool_a{",
                content=JSONSchemaFormat(json_schema=schema_a),
                end="}<end_function_call>",
            ),
            TagFormat(
                begin="<start_function_call>call:tool_b{",
                content=JSONSchemaFormat(json_schema=schema_b),
                end="}<end_function_call>",
            ),
        ],
    )
)
```

**Mitigation:** Structural tags can be serialized to JSON and printed as EBNF for debugging.

### 3. Escaping Complexity

FunctionGemma uses `<escape>...<escape>` for strings, not standard JSON quotes.

**Problem:** `JSONSchemaFormat` generates standard JSON grammar (`"value"`), but FunctionGemma expects:
```
<escape>value<escape>
```

**Risk:** Schema enforcement may not work correctly with FunctionGemma's non-standard JSON.

**Mitigation:** May need custom style or `GrammarFormat` wrapper.

### 4. vLLM API Compatibility

**Current:** vLLM accepts `structured_outputs.grammar` directly.

**Question:** Does vLLM accept `structured_outputs.structural_tag`?

Need to verify vLLM's XGrammar integration exposes structural tag API.

**Fallback:** Convert structural tag to EBNF string before sending:
```python
grammar = xgr.Grammar.from_structural_tag(structural_tag)
ebnf_string = str(grammar)
```

### 5. Argument Schema Trade-offs

**Enforcing schemas has costs:**
- Model may struggle to satisfy complex schemas
- May reduce tool call success rate
- May increase generation latency

**Current reality:** Remora validates arguments post-parse anyway. If invalid, agent loop retries with error context. This works well.

### 6. Dependency on XGrammar Library

**Current:** Grammar is a simple string. No XGrammar import needed at grammar build time.

**With structural tags:** Need `from xgrammar.structural_tag import ...` at build time.

**Risk:** Tighter coupling to XGrammar API, versioning concerns.

### 7. Testing Complexity

**Current:** Test with string matching.

```python
def test_grammar_accepts_valid_call():
    assert '<start_function_call>call:my_tool{}<end_function_call>' in grammar
```

**With structural tags:** Need XGrammar testing utilities.

```python
from xgrammar.testing import _is_grammar_accept_string

def test_structural_tag_accepts_valid_call():
    grammar = xgr.Grammar.from_structural_tag(structural_tag)
    assert _is_grammar_accept_string(str(grammar), input_string)
```

---

## Implementation Options

### Option 1: Keep Current EBNF (Status Quo)

**Approach:** No changes. Continue using strict EBNF grammar.

**Pros:**
- Proven to work
- Simple and debuggable
- No new dependencies

**Cons:**
- No argument schema enforcement
- No thinking/reasoning support
- Single tool call per turn

**Recommendation:** Good baseline. Keep as fallback.

### Option 2: Structural Tags for Full Format

**Approach:** Replace EBNF grammar entirely with structural tags.

```python
def build_functiongemma_structural_tag(tools: list[dict]) -> StructuralTag:
    tags = []
    for tool in tools:
        name = tool["function"]["name"]
        schema = tool["function"].get("parameters", {})
        tags.append(TagFormat(
            begin=f"<start_function_call>call:{name}{{",
            content=JSONSchemaFormat(json_schema=schema),
            end="}<end_function_call>",
        ))

    return StructuralTag(
        format=TagsWithSeparatorFormat(
            tags=tags,
            separator="",  # No separator, just sequence
            at_least_one=True,
            stop_after_first=True,  # Single tool call
        )
    )
```

**Pros:**
- Full schema enforcement
- Type-safe building
- Composable

**Cons:**
- FunctionGemma `<escape>` string format may not work with JSONSchemaFormat
- Increased complexity
- Unknown interaction with 270M model

**Recommendation:** High risk. Needs extensive testing.

### Option 3: Hybrid - EBNF Format + Structural Tag Arguments

**Approach:** Use EBNF for outer format, structural tags only for argument validation.

```python
def build_hybrid_grammar(tools: list[dict]) -> str:
    # Keep strict EBNF for outer format
    tool_names = [t["function"]["name"] for t in tools]
    tool_alts = " | ".join(f'"{name}"' for name in tool_names)

    ebnf = f'''
root ::= "<start_function_call>" "call:" tool_name "{{" args "}}" "<end_function_call>"
tool_name ::= {tool_alts}
args ::= {build_args_grammar(tools)}
'''
    return ebnf

def build_args_grammar(tools: list[dict]) -> str:
    # Generate per-tool argument grammar from schemas
    # This is where structural tag thinking helps
    ...
```

**Pros:**
- Preserves proven strict format
- Adds argument validation
- Incremental adoption

**Cons:**
- Still need to handle FunctionGemma escaping
- More complex grammar building

**Recommendation:** Moderate risk. Good middle ground.

### Option 4: Structural Tags for Thinking + Tool Calling

**Approach:** Use structural tags to enable "thinking" before tool calls.

```python
StructuralTag(
    format=SequenceFormat(elements=[
        # Optional thinking phase
        TagFormat(
            begin="<think>",
            content=AnyTextFormat(excludes=["</think>", "<start_function_call>"]),
            end="</think>",
        ),
        # Required tool call
        TriggeredTagsFormat(
            triggers=["<start_function_call>call:"],
            tags=[...tool tags...],
            at_least_one=True,
            stop_after_first=True,
        ),
    ])
)
```

**Pros:**
- Enables chain-of-thought reasoning
- May improve tool selection quality
- Follows reasoning-before-action pattern

**Cons:**
- FunctionGemma may not support `<think>` tags
- Increased output length
- Unknown model behavior

**Recommendation:** Experimental. Worth exploring but not for production.

---

## FunctionGemma-Specific Considerations

### The `<escape>` String Format

FunctionGemma doesn't use standard JSON string quoting. Instead:

```
# Standard JSON:
{"name": "John Doe"}

# FunctionGemma format:
{name: <escape>John Doe<escape>}
```

**Impact:** `JSONSchemaFormat` generates standard JSON grammar, which may reject valid FunctionGemma output.

### Solutions

1. **Custom grammar for arguments:**
   ```python
   GrammarFormat(grammar='''
   args ::= "{" pair ("," pair)* "}"
   pair ::= key ":" value
   key ::= [a-zA-Z_][a-zA-Z0-9_]*
   value ::= escaped_string | number | boolean
   escaped_string ::= "<escape>" [^<]* "<escape>"
   ''')
   ```

2. **Post-processing:** Keep current `[^}]*` and parse FunctionGemma format after.

3. **Custom structural tag style:** XGrammar supports `style="qwen_xml"` etc. Could we add `style="functiongemma"`?

### Model Size Considerations

FunctionGemma-270M is small. Observations:
- Struggles with complex reasoning
- Benefits from strict constraints (no optional patterns)
- May not handle "thinking" patterns well

**Recommendation:** Test extensively before adding complexity.

---

## Recommended Approach

### Phase 1: Enhanced Argument Grammar (Low Risk)

Keep current strict format, but improve argument matching:

```python
def build_functiongemma_grammar(tools: list[dict]) -> str:
    # Current: arg_body ::= [^}]*
    # Enhanced: Match FunctionGemma's key:value format

    return '''
root ::= "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>"

tool_name ::= "simple_tool" | "submit_result"

arg_body ::= ws? (pair (ws? "," ws? pair)*)? ws?
pair ::= key ws? ":" ws? value
key ::= [a-zA-Z_][a-zA-Z0-9_]*
value ::= escaped_string | number | boolean | "null" | array | object
escaped_string ::= "<escape>" [^<]* "<escape>"
number ::= "-"? [0-9]+ ("." [0-9]+)?
boolean ::= "true" | "false"
array ::= "[" ws? (value (ws? "," ws? value)*)? ws? "]"
object ::= "{" ws? (pair (ws? "," ws? pair)*)? ws? "}"
ws ::= [ \\t]*
'''
```

**Benefits:**
- Better argument structure enforcement
- Still simple EBNF
- Handles FunctionGemma `<escape>` format

### Phase 2: Structural Tag Experimentation (Medium Risk)

Add optional structural tag support for experimentation:

```python
class GrammarBuilder:
    @staticmethod
    def build_ebnf(tools: list[dict]) -> str:
        """Current approach - always works."""
        ...

    @staticmethod
    def build_structural_tag(tools: list[dict]) -> StructuralTag:
        """Experimental - use with caution."""
        ...

    @staticmethod
    def build(tools: list[dict], use_structural_tags: bool = False) -> str | StructuralTag:
        if use_structural_tags:
            return GrammarBuilder.build_structural_tag(tools)
        return GrammarBuilder.build_ebnf(tools)
```

**Configuration:**
```yaml
runner:
  use_grammar_enforcement: true
  grammar_mode: "ebnf"  # or "structural_tag"
```

### Phase 3: Per-Tool Schema Validation (Higher Risk)

If Phase 2 succeeds, add per-tool schema enforcement:

```python
def build_structural_tag_with_schemas(tools: list[dict]) -> StructuralTag:
    tags = []
    for tool in tools:
        name = tool["function"]["name"]
        schema = tool["function"].get("parameters", {})

        # Convert to FunctionGemma-compatible grammar
        content = build_functiongemma_schema_grammar(schema)

        tags.append(TagFormat(
            begin=f"<start_function_call>call:{name}{{",
            content=GrammarFormat(grammar=content),
            end="}<end_function_call>",
        ))

    return StructuralTag(
        format=OrFormat(elements=tags)
    )
```

---

## Implementation Roadmap

### Milestone 1: Research & Validation

1. **Test vLLM structural tag support**
   - Verify `structured_outputs.structural_tag` works
   - Or confirm EBNF conversion approach

2. **Test JSONSchemaFormat with FunctionGemma**
   - Does it work? What errors occur?
   - Can we use custom grammar instead?

3. **Benchmark complexity impact**
   - Compare generation quality: simple vs complex grammar
   - Measure latency impact

### Milestone 2: Enhanced EBNF

1. Improve `arg_body` grammar to match FunctionGemma format
2. Add unit tests for enhanced grammar
3. Validate with real model outputs

### Milestone 3: Structural Tag Infrastructure

1. Add `xgrammar` as optional dependency
2. Create `StructuralTagBuilder` class
3. Add configuration toggle
4. Create comprehensive tests

### Milestone 4: Per-Tool Schema Enforcement

1. Generate per-tool argument grammars from OpenAI schemas
2. Handle FunctionGemma `<escape>` format
3. Validate with tool execution tests

### Milestone 5: Thinking Support (Experimental)

1. Add `<think>` tag support (if model supports it)
2. Test with FunctionGemma
3. Measure impact on tool selection quality

---

## Code Examples

### Example 1: Current Grammar Builder

```python
# src/remora/grammar.py (current)
def build_functiongemma_grammar(tools: list[dict]) -> str:
    tool_names = [t["function"]["name"] for t in tools ...]
    tool_alternatives = " | ".join(f'"{name}"' for name in tool_names)

    return "\n".join([
        'root ::= "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>"',
        "",
        f"tool_name ::= {tool_alternatives}",
        "",
        "arg_body ::= arg_char*",
        "arg_char ::= [^}]",
        "",
    ])
```

### Example 2: Enhanced EBNF Grammar (Phase 1)

```python
def build_functiongemma_grammar_v2(tools: list[dict]) -> str:
    """Enhanced grammar with FunctionGemma argument structure."""
    tool_names = [t["function"]["name"] for t in tools ...]
    tool_alternatives = " | ".join(f'"{name}"' for name in tool_names)

    return f'''
root ::= "<start_function_call>" "call:" tool_name "{{" arg_body "}}" "<end_function_call>"

tool_name ::= {tool_alternatives}

# FunctionGemma argument structure
arg_body ::= ws? (pair (ws? "," ws? pair)*)? ws?
pair ::= key ws? ":" ws? value
key ::= [a-zA-Z_][a-zA-Z0-9_]*

# FunctionGemma uses <escape>...<escape> for strings
value ::= escaped_string | number | boolean | "null" | array | object
escaped_string ::= "<escape>" escape_content "<escape>"
escape_content ::= escape_char*
escape_char ::= [^<] | "<" [^e/]

number ::= "-"? int frac?
int ::= "0" | [1-9][0-9]*
frac ::= "." [0-9]+

boolean ::= "true" | "false"

array ::= "[" ws? (value (ws? "," ws? value)*)? ws? "]"
object ::= "{{" ws? (pair (ws? "," ws? pair)*)? ws? "}}"

ws ::= [ \\t]*
'''
```

### Example 3: Structural Tag Approach (Phase 2)

```python
from xgrammar.structural_tag import (
    StructuralTag,
    OrFormat,
    TagFormat,
    GrammarFormat,
)

def build_functiongemma_structural_tag(tools: list[dict]) -> StructuralTag:
    """Build structural tag for FunctionGemma tool calling."""
    tags = []

    for tool in tools:
        func = tool.get("function", {})
        name = func.get("name")
        if not name:
            continue

        # Use custom grammar for FunctionGemma argument format
        args_grammar = build_functiongemma_args_grammar(func.get("parameters", {}))

        tags.append(TagFormat(
            begin=f"<start_function_call>call:{name}{{",
            content=GrammarFormat(grammar=args_grammar),
            end="}<end_function_call>",
        ))

    return StructuralTag(
        format=OrFormat(elements=tags) if len(tags) > 1 else tags[0]
    )

def build_functiongemma_args_grammar(schema: dict) -> str:
    """Convert JSON schema to FunctionGemma-compatible EBNF."""
    # For now, permissive grammar
    return 'root ::= [^}]*'
```

### Example 4: Per-Tool Schema Validation (Phase 3)

```python
def build_functiongemma_args_grammar(schema: dict) -> str:
    """Convert JSON schema to FunctionGemma-compatible EBNF.

    Handles the <escape>...<escape> string format.
    """
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    if not properties:
        return 'root ::= [^}]*'

    # Build per-property rules
    rules = ['root ::= "{" ws? properties ws? "}"']

    # Generate property alternations
    prop_rules = []
    for name, prop_schema in properties.items():
        prop_type = prop_schema.get("type", "string")
        value_rule = f"value_{name}"
        prop_rules.append(f'"{name}" ws? ":" ws? {value_rule}')
        rules.append(f'{value_rule} ::= {type_to_ebnf(prop_type)}')

    rules.append(f'properties ::= {" | ".join(prop_rules)}')
    rules.append('ws ::= [ \\t]*')
    rules.append('escaped_string ::= "<escape>" [^<]* "<escape>"')
    rules.append('number ::= "-"? [0-9]+ ("." [0-9]+)?')
    rules.append('boolean ::= "true" | "false"')

    return '\n'.join(rules)

def type_to_ebnf(json_type: str) -> str:
    """Convert JSON schema type to EBNF rule."""
    mapping = {
        "string": "escaped_string",
        "number": "number",
        "integer": "number",
        "boolean": "boolean",
        "null": '"null"',
    }
    return mapping.get(json_type, "escaped_string")
```

### Example 5: Thinking + Tool Calling (Phase 5)

```python
def build_thinking_structural_tag(tools: list[dict]) -> StructuralTag:
    """Enable reasoning before tool calling.

    WARNING: Experimental. FunctionGemma may not support <think> tags.
    """
    from xgrammar.structural_tag import (
        StructuralTag,
        SequenceFormat,
        TagFormat,
        AnyTextFormat,
        TriggeredTagsFormat,
        GrammarFormat,
    )

    tool_tags = []
    for tool in tools:
        name = tool["function"]["name"]
        tool_tags.append(TagFormat(
            begin=f"<start_function_call>call:{name}{{",
            content=GrammarFormat(grammar='root ::= [^}]*'),
            end="}<end_function_call>",
        ))

    return StructuralTag(
        format=SequenceFormat(elements=[
            # Optional thinking phase
            TagFormat(
                begin="<think>",
                content=AnyTextFormat(excludes=["</think>", "<start_function_call>"]),
                end="</think>",
            ),
            # Required tool call
            TriggeredTagsFormat(
                triggers=["<start_function_call>call:"],
                tags=tool_tags,
                at_least_one=True,
                stop_after_first=True,
            ),
        ])
    )
```

---

## Summary

### Should Remora Adopt Structural Tags?

**For argument schema enforcement:** Yes, but incrementally. Start with enhanced EBNF that understands FunctionGemma's `<escape>` format, then layer on structural tags for per-tool validation.

**For thinking/reasoning:** Maybe later. Need to verify FunctionGemma supports it and test impact on small model.

**For format enforcement:** No change needed. Current strict EBNF works well.

### Decision Matrix

| Feature | Recommendation | Risk | Priority |
|---------|---------------|------|----------|
| Enhanced arg grammar | Implement | Low | High |
| Structural tag infra | Add as option | Medium | Medium |
| Per-tool schemas | Experiment | Medium | Medium |
| Thinking support | Research only | High | Low |

### Next Steps

1. Test FunctionGemma argument format patterns
2. Enhance EBNF grammar for argument structure
3. Add optional structural tag builder
4. Benchmark and validate
