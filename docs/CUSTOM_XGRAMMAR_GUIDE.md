# XGrammar Structured Generation Guide

*The comprehensive guide to EBNF grammar-based structured generation with vLLM and FunctionGemma.*

---

## Table of Contents

1. [Overview](#overview)
2. [How It Works](#how-it-works)
3. [Server Setup](#server-setup)
4. [XGrammar Python API Reference](#xgrammar-python-api-reference)
5. [EBNF Grammar Reference](#ebnf-grammar-reference)
6. [Grammar Types](#grammar-types)
7. [Grammar Complexity Levels](#grammar-complexity-levels)
8. [Remora Integration](#remora-integration)
9. [Testing Grammars Locally](#testing-grammars-locally)
10. [Common Pitfalls](#common-pitfalls)
11. [Advanced Topics](#advanced-topics)
12. [Structural Tags](#structural-tags)
13. [Runtime Safeguards](#runtime-safeguards)
14. [Debugging](#debugging)

---

## Overview

### What is XGrammar?

XGrammar is vLLM's structured output backend that **constrains token-by-token decoding** so model output **must match** a specified grammar. This provides "hard guarantees" about output format that prompt engineering alone cannot achieve.

XGrammar supports:
- **JSON** and **JSON Schema** (including Pydantic models)
- **Regular expressions** (regex)
- **Custom context-free grammar** (EBNF format)
- **Structural tags** (for tool calling, reasoning tags, etc.)

### Why Use Grammar Enforcement?

| Without Grammar | With Grammar |
|-----------------|--------------|
| ~60-80% tool call rate | **100% tool call rate** |
| Model can output plain text | Impossible - format enforced |
| Model can invent tool names | Impossible - enum enforced |
| Format errors possible | Format errors impossible |

### Key Benefits

1. **Hard format guarantees** - Model cannot output non-tool-call text
2. **Tool name enforcement** - Enum constrains to valid tools only
3. **No hallucinated tools** - Model cannot invent tool names outside your list
4. **Works with existing parser** - vLLM's FunctionGemma parser extracts `tool_calls`

### Trade-offs

- Grammar doesn't validate argument schemas (required keys, types, enums)
- Need post-parse validation for full schema compliance
- Grammar compilation adds minimal overhead (cached by XGrammar)

---

## How It Works

### Constrained Decoding Explained

In each step of LLM inference, XGrammar provides a **token bitmask** to the LLM. The mask:
- Allows tokens that follow the grammar
- Prohibits tokens that don't
- Sets logits of invalid tokens to `-inf` so their probability becomes `0` after softmax

```
Token Mask (binary):  [1, 1, 0, 1, 0, 0, 1, ...]
                       ↓  ↓     ↓        ↓
Logits before mask:   [2.1, 1.3, 0.8, -0.5, 1.2, 0.3, -1.0, ...]
                       ↓  ↓     ↓        ↓
Logits after mask:    [2.1, 1.3, -inf, -0.5, -inf, -inf, -1.0, ...]
```

### The Pipeline

```
Client Request
    │
    ├─► tools: [...]           # OpenAI-format tool schemas
    ├─► tool_choice: "auto"    # Let vLLM parse tool calls
    └─► extra_body: {          # Grammar constraint
            "structured_outputs": {
                "type": "grammar",
                "grammar": ebnf_string
            }
        }
    │
    ▼
vLLM Server
    │
    ├─► XGrammar constrains decoding token-by-token
    ├─► Model emits: <start_function_call>call:tool_name{args}<end_function_call>
    └─► FunctionGemma parser extracts tool_calls
    │
    ▼
Response
    │
    ├─► message.content: null (or raw text)
    └─► message.tool_calls: [{name: "tool_name", arguments: {...}}]
```

### Critical: tool_choice Setting

**Use `tool_choice="auto"` with grammar enforcement.**

| Setting | Behavior |
|---------|----------|
| `tool_choice="auto"` | Grammar constrains output + vLLM extracts `tool_calls` |
| `tool_choice="none"` | Grammar constrains output but `tool_calls` is empty (output in `content` only) |
| `tool_choice="required"` | May conflict with grammar; avoid |

The grammar forces the FunctionGemma format, and `tool_choice="auto"` tells vLLM's parser to extract tool calls from that format.

---

## Server Setup

### vLLM Server Command

```bash
vllm serve google/functiongemma-270m-it \
  --enable-auto-tool-choice \
  --tool-call-parser functiongemma \
  --chat-template /path/to/tool_chat_template_functiongemma.jinja
```

**Flags explained:**
- `--enable-auto-tool-choice` - Enables tool call parsing
- `--tool-call-parser functiongemma` - Extracts `<start_function_call>...<end_function_call>` into `tool_calls`
- `--chat-template` - Uses FunctionGemma's chat format

### Docker Example

```yaml
# docker-compose.yml
services:
  vllm:
    image: vllm/vllm-openai:latest
    command: >
      --model google/functiongemma-270m-it
      --enable-auto-tool-choice
      --tool-call-parser functiongemma
      --chat-template /app/tool_chat_template_functiongemma.jinja
    ports:
      - "8000:8000"
```

---

## XGrammar Python API Reference

### Installation

```bash
pip install xgrammar

# For Apple Silicon MPS support:
pip install "xgrammar[metal]"
```

### Core Classes

#### TokenizerInfo

Contains tokenizer vocabulary and metadata. Required for grammar compilation.

```python
import xgrammar as xgr
from transformers import AutoTokenizer, AutoConfig

tokenizer = AutoTokenizer.from_pretrained("meta-llama/Llama-3.2-1B-Instruct")
config = AutoConfig.from_pretrained("meta-llama/Llama-3.2-1B-Instruct")

# IMPORTANT: Use config.vocab_size (model's logit dimension), not tokenizer.vocab_size
# They can differ due to padding
tokenizer_info = xgr.TokenizerInfo.from_huggingface(
    tokenizer,
    vocab_size=config.vocab_size,  # Model's vocab size, not tokenizer's
    stop_token_ids=[128001],       # Optional: override stop tokens
)
```

**VocabType enum:**
- `VocabType.RAW` - Tokens kept as-is (tiktoken, Qwen, Phi-3-small)
- `VocabType.BYTE_FALLBACK` - Byte fallback encoding, e.g., `"\u001b"` -> `"<0x1B>"` (Llama-2, Phi-3.5-mini)
- `VocabType.BYTE_LEVEL` - Byte-to-unicode, e.g., `" "` -> `"Ġ"` (Llama-3, GPT-2)

**Properties:**
- `vocab_size: int` - Size of vocabulary
- `vocab_type: VocabType` - Type of vocabulary encoding
- `stop_token_ids: List[int]` - Stop token IDs
- `special_token_ids: List[int]` - Special token IDs (control, reserved, padding)
- `decoded_vocab: List[bytes]` - Vocabulary decoded to original format
- `add_prefix_space: bool` - Whether tokenizer prepends space

#### Grammar

Represents a grammar that can be compiled. Create from various sources:

```python
# From EBNF string
grammar = xgr.Grammar.from_ebnf(ebnf_string, root_rule_name="root")

# From JSON Schema (string, dict, or Pydantic model)
grammar = xgr.Grammar.from_json_schema(
    schema,                    # str, dict, or Type[BaseModel]
    any_whitespace=True,       # Allow flexible whitespace (default)
    indent=None,               # Indentation spaces (None = single line)
    separators=None,           # (comma, colon) separators
    strict_mode=True,          # Disallow extra properties/items
    max_whitespace_cnt=None,   # Max whitespace chars between elements
)

# From regex
grammar = xgr.Grammar.from_regex(r"\d{3}-\d{4}")

# Built-in JSON grammar
grammar = xgr.Grammar.builtin_json_grammar()

# From structural tag (for tool calling)
grammar = xgr.Grammar.from_structural_tag(structural_tag)

# Combine grammars
combined = xgr.Grammar.concat(grammar1, grammar2)  # Sequence (g1 + g2)
combined = xgr.Grammar.union(grammar1, grammar2)   # Choice (g1 | g2)

# Print as EBNF
print(grammar)  # Outputs EBNF string

# Serialization
json_str = grammar.serialize_json()
grammar = xgr.Grammar.deserialize_json(json_str)
```

#### GrammarCompiler

Compiles grammars for a specific tokenizer. Use one per model, reuse across requests.

```python
compiler = xgr.GrammarCompiler(
    tokenizer_info,
    max_threads=8,              # Threads for compilation (default: 8)
    cache_enabled=True,         # Enable caching (default: True)
    cache_limit_bytes=-1,       # Cache memory limit (-1 = unlimited)
)

# Compile various grammar types
compiled = compiler.compile_grammar(ebnf_string, root_rule_name="root")
compiled = compiler.compile_grammar(grammar_object)
compiled = compiler.compile_json_schema(schema, ...)
compiled = compiler.compile_builtin_json_grammar()
compiled = compiler.compile_regex(pattern)
compiled = compiler.compile_structural_tag(structural_tag)

# Cache management
compiler.clear_cache()
size = compiler.get_cache_size_bytes()
limit = compiler.cache_limit_bytes
```

**Caching:** The compiler caches compiled grammars by input string. Same grammar compiles once.

**Async compilation:** `compile_*` methods release the GIL, enabling asyncio parallelism:

```python
async def compile_multiple():
    future1 = asyncio.to_thread(compiler.compile_grammar, grammar1)
    future2 = asyncio.to_thread(compiler.compile_grammar, grammar2)
    return await asyncio.gather(future1, future2)
```

#### CompiledGrammar

Result of grammar compilation. Contains compiled grammar + tokenizer info.

```python
# Properties
compiled.grammar           # Original Grammar object
compiled.tokenizer_info    # Associated TokenizerInfo
compiled.memory_size_bytes # Memory usage in bytes

# Serialization (for caching across processes)
json_str = compiled.serialize_json()  # Excludes tokenizer_info
compiled = xgr.CompiledGrammar.deserialize_json(json_str, tokenizer_info)
```

#### GrammarMatcher

Stateful matcher for grammar-guided generation. **One per request.**

```python
matcher = xgr.GrammarMatcher(
    compiled_grammar,
    override_stop_tokens=None,          # Override stop tokens
    terminate_without_stop_token=False, # Terminate without EOS
)

# Accept a token and update state
accepted: bool = matcher.accept_token(token_id, debug_print=False)

# Accept a string (for testing, not production)
accepted: bool = matcher.accept_string("hello", debug_print=False)

# Fill bitmask for next token prediction
need_apply: bool = matcher.fill_next_token_bitmask(bitmask, index=0, debug_print=False)
# Returns True if mask needs to be applied (not all-true)

# Check termination
if matcher.is_terminated():
    print("Generation complete")

# Reset for next generation
matcher.reset()

# Rollback tokens (for speculative decoding)
matcher.rollback(num_tokens=1)

# Jump-forward decoding
jump_str = matcher.find_jump_forward_string()  # Deterministic next chars

# Properties
matcher.stop_token_ids  # List of stop token IDs
```

#### Token Bitmask Operations

```python
# Allocate bitmask (on CPU, int32)
bitmask = xgr.allocate_token_bitmask(batch_size, vocab_size)
# Shape: (batch_size, ceil(vocab_size / 32))

# Reset bitmask to all-allowed
xgr.reset_token_bitmask(bitmask)

# Apply bitmask to logits (sets masked tokens to -inf)
xgr.apply_token_bitmask_inplace(
    logits,                 # torch.Tensor on GPU or CPU
    bitmask.to(logits.device),  # Must be same device
    vocab_size=None,        # Optional: actual vocab size
    indices=None,           # Optional: batch indices to apply
    backend="auto",         # "auto", "cpu", "cuda", "triton", "torch_compile", "torch_native"
)

# Helper functions
shape = xgr.get_bitmask_shape(batch_size, vocab_size)  # (batch, ceil(vocab/32))
dtype = xgr.bitmask_dtype  # torch.int32
```

#### BatchGrammarMatcher

For efficient batched inference with multiple matchers:

```python
batch_matcher = xgr.BatchGrammarMatcher(max_threads="auto")

# Batch fill bitmasks
batch_matcher.batch_fill_next_token_bitmask(
    matchers,          # List[GrammarMatcher]
    bitmask,           # Preallocated bitmask
    indices=None,      # Optional indices
    debug_print=False,
)

# Batch accept tokens (static method)
results: List[bool] = xgr.BatchGrammarMatcher.batch_accept_token(
    matchers, tokens, debug_print=False
)

# Batch accept strings (static method)
results: List[bool] = xgr.BatchGrammarMatcher.batch_accept_string(
    matchers, strings, debug_print=False
)
```

#### HuggingFace Integration

```python
from xgrammar.contrib.hf import LogitsProcessor

# Create logits processor (one per generate() call!)
processor = LogitsProcessor(compiled_grammar)
# Or for batch with different grammars:
processor = LogitsProcessor([grammar1, grammar2, ...])

# Use with transformers
generated = model.generate(
    **inputs,
    max_new_tokens=512,
    logits_processor=[processor]
)
```

**Important:** Create a new `LogitsProcessor` for each `generate()` call.

---

## EBNF Grammar Reference

XGrammar uses **GBNF format** (GGML BNF), documented at:
https://github.com/ggerganov/llama.cpp/blob/master/grammars/README.md

### Basic Syntax

```ebnf
# Rule definition
rule_name ::= expression

# String literal (exact match)
"hello"
'hello'

# Character class (any single char matching)
[a-zA-Z]        # Letters
[0-9]           # Digits
[^}]            # Any char EXCEPT }
[A-Za-z0-9_]    # Alphanumeric + underscore
[\t\r\n]        # Tab, carriage return, newline
[ \t\r\n]       # Whitespace characters

# Quantifiers
expr?           # Zero or one (optional)
expr*           # Zero or more
expr+           # One or more

# Alternation (choice)
"a" | "b" | "c"

# Grouping
("a" | "b") "c"

# Sequence
"hello" " " "world"
```

### Character Class Syntax

```ebnf
# Positive class - match any listed character
[abc]           # Matches 'a', 'b', or 'c'
[a-z]           # Matches any lowercase letter
[A-Za-z0-9]     # Matches alphanumeric

# Negated class - match any character EXCEPT listed
[^}]            # Any character except '}'
[^<\\]          # Any character except '<' or '\'

# Special characters in classes
[\t\r\n]        # Tab, carriage return, newline
[ \t\r\n]       # Space, tab, CR, newline (whitespace)

# Ranges
[a-z]           # Lowercase letters
[A-Z]           # Uppercase letters
[0-9]           # Digits
[a-zA-Z0-9]     # Alphanumeric
```

### Escaping Rules

When writing EBNF in Python strings:

```python
# In EBNF file (raw):
ws ::= [ \t\r\n]+

# In Python string (need to escape backslashes):
"ws ::= [ \\t\\r\\n]+"

# Using raw string (easier - no escaping needed):
r'ws ::= [ \t\r\n]+'
```

**Important:** In character classes, use `[^}]` not complex enumerations like `[A-Za-z0-9_:\-\"\., ]`. Negated classes are simpler and more robust.

### Complete JSON Grammar Example

```ebnf
root ::= basic_array | basic_object

basic_any ::= basic_number | basic_string | basic_boolean | basic_null | basic_array | basic_object

basic_integer ::= ("0" | "-"? [1-9] [0-9]*) ".0"?

basic_number ::= ("0" | "-"? [1-9] [0-9]*) ("." [0-9]+)? ([eE] [+-]? [0-9]+)?

basic_string ::= "\"" basic_string_content "\""
basic_string_content ::= "" | [^"\\] basic_string_content | "\\" escape basic_string_content

escape ::= ["\\/bfnrt] | "u" [A-Fa-f0-9] [A-Fa-f0-9] [A-Fa-f0-9] [A-Fa-f0-9]

basic_boolean ::= "true" | "false"

basic_null ::= "null"

basic_array ::= "[" ws (basic_any (ws "," ws basic_any)*)? ws "]"

basic_object ::= "{" ws (basic_string ws ":" ws basic_any (ws "," ws basic_string ws ":" ws basic_any)*)? ws "}"

ws ::= [ \n\t]*
```

---

## Grammar Types

XGrammar supports multiple grammar types:

### 1. EBNF Grammar

Custom context-free grammars for maximum flexibility:

```python
ebnf = r'''
root ::= expr "=" term
expr ::= term ([-+*/] term)*
term ::= num | "(" expr ")"
num ::= [0-9]+
'''
grammar = xgr.Grammar.from_ebnf(ebnf)
compiled = compiler.compile_grammar(ebnf)
```

### 2. JSON Schema

Enforce JSON structure from schema:

```python
from pydantic import BaseModel
from typing import List, Optional

class Person(BaseModel):
    name: str
    age: int
    hobbies: Optional[List[str]] = None

# From Pydantic model
compiled = compiler.compile_json_schema(Person)

# From dict
schema = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"}
    },
    "required": ["name", "age"]
}
compiled = compiler.compile_json_schema(schema)

# From JSON string
compiled = compiler.compile_json_schema('{"type": "object", ...}')
```

**Options:**
- `any_whitespace=True` - Allow flexible whitespace (recommended)
- `indent=2` - Force specific indentation (may hurt generation quality)
- `separators=(",", ": ")` - Specify JSON separators
- `strict_mode=True` - Disallow extra properties (recommended)
- `max_whitespace_cnt=10` - Limit whitespace between elements

### 3. Regular Expressions

For simple pattern matching:

```python
# Phone number
compiled = compiler.compile_regex(r"\d{3}-\d{3}-\d{4}")

# Email-like pattern
compiled = compiler.compile_regex(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
```

**Supported regex features:**
- Character classes: `[a-z]`, `[^abc]`, `\d`, `\w`, `\s`
- Quantifiers: `*`, `+`, `?`
- Alternation: `a|b`
- Groups: `(abc)`

**Not supported:**
- Backreferences: `\1`
- Lookahead/lookbehind: `(?=...)`, `(?!...)`
- Non-capturing groups: `(?:...)`
- Unicode properties: `\p{...}`
- Quantifier ranges: `{n,m}` (use repetition instead)

### 4. Built-in JSON Grammar

For any valid JSON:

```python
compiled = compiler.compile_builtin_json_grammar()
```

### 5. Structural Tags

For tool calling and structured responses (see [Structural Tags](#structural-tags) section).

---

## Grammar Complexity Levels

### Level 1: Strict (Recommended)

Forces exact FunctionGemma format with no whitespace flexibility. **This is what Remora uses.**

```ebnf
root ::= "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>"

tool_name ::= "simple_tool" | "submit_result"

arg_body ::= arg_char*
arg_char ::= [^}]
```

**Characteristics:**
- No leading/trailing whitespace allowed
- No whitespace between `call:` and tool name
- Arguments are freeform (anything except `}`)
- Simplest and most robust

**Why strict?** Allowing optional whitespace (`ws?`) can cause degenerate outputs where the model generates endless whitespace/newlines instead of completing the call.

### Level 2: Permissive (Legacy)

Allows optional whitespace in various positions.

```ebnf
root ::= ws? "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>" ws?

tool_name ::= "simple_tool" | "submit_result"

arg_body ::= arg_char*
arg_char ::= [^}]

ws ::= [ \t\r\n]+
```

**Warning:** The `ws?` patterns can cause issues with small models that get stuck generating whitespace.

### Level 3: Structured Arguments

Enforces JSON-like argument structure with FunctionGemma's `<escape>` string convention.

```ebnf
root ::= "<start_function_call>" "call:" tool_name obj "<end_function_call>"

tool_name ::= "simple_tool" | "submit_result"

obj ::= "{" ws? (pair (ws? "," ws? pair)*)? ws? "}"
pair ::= ident ws? ":" ws? value

value ::= escaped_string | number | boolean | "null" | obj | arr
arr ::= "[" ws? (value (ws? "," ws? value)*)? ws? "]"

escaped_string ::= "<escape>" str_char* "<escape>"
str_char ::= [^<\\] | "\\" ["\\/bfnrt]

number ::= "-"? int frac? exp?
int ::= "0" | [1-9] [0-9]*
frac ::= "." [0-9]+
exp ::= ("e" | "E") ("+" | "-")? [0-9]+

boolean ::= "true" | "false"
ident ::= [A-Za-z_] [A-Za-z0-9_]*
ws ::= [ \t\r\n]+
```

**Guarantees:**
- Exactly one FunctionGemma call wrapper
- Tool name is one of your tools
- Args are an object with key:value pairs
- String values use `<escape>...<escape>`

**Does NOT guarantee:**
- Required keys per tool
- Enum validation from JSON schema
- "No extra keys" constraints

### Level 4: Per-Tool Argument Schemas

For small tool sets, you can enforce specific required keys per tool:

```ebnf
root ::= "<start_function_call>" "call:" function_call "<end_function_call>"

function_call ::= "get_weather" args_weather | "get_time" args_time

args_weather ::= "{" ws? "location" ws? ":" ws? escaped_string ws? "}"
args_time ::= "{" ws? "timezone" ws? ":" ws? escaped_string ws? "}"

escaped_string ::= "<escape>" [^<]* "<escape>"
ws ::= [ \t\r\n]+
```

**Note:** This scales poorly for many tools. Most teams use Level 1 or 3 and validate arguments after parsing.

---

## Remora Integration

### Configuration

Grammar enforcement is enabled by default in `remora.yaml`:

```yaml
runner:
  use_grammar_enforcement: true  # Default: true
  tool_choice: "auto"            # Keep as "auto" for tool_calls extraction
```

### Implementation

Remora's grammar builder (`src/remora/grammar.py`):

```python
"""FunctionGemma grammar builder for vLLM structured outputs."""

from __future__ import annotations
from typing import Any


def build_functiongemma_grammar(tools: list[dict[str, Any]]) -> str:
    """Build a strict EBNF grammar for FunctionGemma tool calls.

    Args:
        tools: OpenAI-format tool schemas

    Returns:
        EBNF grammar string for vLLM structured outputs
    """
    tool_names = [
        tool["function"]["name"]
        for tool in tools
        if tool.get("type") == "function"
        and isinstance(tool.get("function"), dict)
        and "name" in tool["function"]
    ]
    if not tool_names:
        raise ValueError("No function tools found in schema")

    def esc(value: str) -> str:
        """Escape special characters for EBNF string literals."""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    tool_alternatives = " | ".join(f'"{esc(name)}"' for name in tool_names)

    # Strict grammar - no whitespace flexibility
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

### Harness Testing

Test grammar enforcement with the harness:

```bash
# With grammar (default)
uv run python scripts/functiongemma_harness.py --use-grammar --requests-per-variant 10

# Without grammar (baseline comparison)
uv run python scripts/functiongemma_harness.py --no-use-grammar --requests-per-variant 10
```

---

## Testing Grammars Locally

### Using XGrammar Testing Utilities

XGrammar provides testing utilities for validating grammars without running a model:

```python
from xgrammar.testing import _is_grammar_accept_string, _get_matcher_from_grammar

# Test if grammar accepts a string
grammar = r'root ::= "hello" " " "world"'
accepts = _is_grammar_accept_string(grammar, "hello world")
print(f"Accepts 'hello world': {accepts}")  # True

# Get a matcher for manual testing
matcher = _get_matcher_from_grammar(grammar)
accepted = matcher.accept_string("hello world")
print(f"Terminated: {matcher.is_terminated()}")

# Convert JSON schema to EBNF (for inspection)
from xgrammar.testing import _json_schema_to_ebnf
ebnf = _json_schema_to_ebnf({"type": "object", "properties": {"name": {"type": "string"}}})
print(ebnf)

# Convert regex to EBNF
from xgrammar.testing import _regex_to_ebnf
ebnf = _regex_to_ebnf(r"\d{3}-\d{4}")
print(ebnf)
```

### Grammar Test Harness

Remora includes a grammar test harness (`scripts/test_grammar.py`) for validating EBNF without needing the vLLM server:

```bash
# Full test suite
uv run python scripts/test_grammar.py full-test

# Validate syntax only
uv run python scripts/test_grammar.py validate --show-grammar

# Test specific input
uv run python scripts/test_grammar.py test -i '<start_function_call>call:simple_tool{test}<end_function_call>'

# Generate grammar for custom tools
uv run python scripts/test_grammar.py generate my_tool another_tool
```

### Sample Output

```
============================================================
GRAMMAR TEST HARNESS - Full Test Suite
============================================================

Step 1: Generate grammar
----------------------------------------
Grammar generated successfully.

Generated grammar:
  root ::= "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>"

  tool_name ::= "simple_tool" | "submit_result"

  arg_body ::= arg_char*
  arg_char ::= [^}]


Step 2: Validate EBNF syntax
----------------------------------------
No syntax errors found.

Step 3: Test against sample inputs
----------------------------------------
Valid samples (should match):
  1. [PASS] <start_function_call>call:simple_tool{...
  2. [PASS] <start_function_call>call:submit_result{...
  ...

============================================================
ALL TESTS PASSED
```

### Writing Grammar Tests

Add test cases to the harness:

```python
# Valid samples (should match grammar)
VALID_SAMPLES = [
    '<start_function_call>call:simple_tool{}<end_function_call>',
    '<start_function_call>call:simple_tool{key:value}<end_function_call>',
]

# Invalid samples (should NOT match grammar)
INVALID_SAMPLES = [
    "plain text",                                    # Not a tool call
    "<start_function_call>call:unknown{}<end_...",  # Unknown tool
    "  <start_function_call>...",                   # Leading whitespace (strict)
]
```

---

## Common Pitfalls

### Pitfall 1: Using tool_choice="none"

**Problem:** Setting `tool_choice="none"` prevents vLLM from extracting `tool_calls`.

```python
# WRONG - tool_calls will be empty
response = client.chat.completions.create(
    ...,
    tool_choice="none",  # Grammar constrains, but no tool_calls extraction
    extra_body={"structured_outputs": {"type": "grammar", "grammar": grammar}},
)
print(response.choices[0].message.tool_calls)  # []
print(response.choices[0].message.content)     # Raw FunctionGemma text
```

**Solution:** Use `tool_choice="auto"`:

```python
# CORRECT - grammar + tool_calls extraction
response = client.chat.completions.create(
    ...,
    tool_choice="auto",  # vLLM will extract tool_calls
    extra_body={"structured_outputs": {"type": "grammar", "grammar": grammar}},
)
print(response.choices[0].message.tool_calls)  # [ToolCall(...)]
```

### Pitfall 2: Invalid Character Class Syntax

**Problem:** Using enumerated character classes with complex escaping.

```python
# WRONG - complex escaping, may be rejected
'arg_char ::= [A-Za-z0-9_:\\-\\"\\., ]'
```

**Solution:** Use negated character class:

```python
# CORRECT - simple, robust
'arg_char ::= [^}]'
```

### Pitfall 3: Allowing Too Much Whitespace

**Problem:** Optional whitespace patterns cause degenerate outputs.

```ebnf
# PROBLEMATIC - model may generate endless whitespace
root ::= ws? "<start_function_call>" "call:" ws? tool_name ...
ws ::= [ \t\r\n]+
```

**Solution:** Use strict grammar without optional whitespace:

```ebnf
# CORRECT - no whitespace flexibility
root ::= "<start_function_call>" "call:" tool_name ...
```

### Pitfall 4: Grammar Not Validated Before Deployment

**Problem:** Invalid EBNF causes vLLM to reject requests with "Invalid grammar specification."

**Solution:** Test locally first:

```bash
uv run python scripts/test_grammar.py validate --show-grammar
```

Or use XGrammar directly:

```python
import xgrammar as xgr

grammar = r'root ::= "test"'
try:
    g = xgr.Grammar.from_ebnf(grammar)
    print("Grammar is valid")
except RuntimeError as e:
    print(f"Grammar error: {e}")
```

### Pitfall 5: Expecting Full JSON Schema Validation

**Problem:** Assuming grammar validates required keys, types, enums.

**Solution:** Grammar enforces structure, not schema. Validate after parsing:

```python
# Parse tool call
tool_name = tool_call.function.name
args = json.loads(tool_call.function.arguments)

# Validate against schema
schema = get_schema_for_tool(tool_name)
validate(args, schema)  # Raise if invalid
```

### Pitfall 6: Wrong vocab_size

**Problem:** Using `tokenizer.vocab_size` instead of `config.vocab_size`.

```python
# WRONG - may be smaller than model's logit dimension
tokenizer_info = xgr.TokenizerInfo.from_huggingface(tokenizer)

# CORRECT - use model config's vocab_size
config = AutoConfig.from_pretrained(model_name)
tokenizer_info = xgr.TokenizerInfo.from_huggingface(
    tokenizer, vocab_size=config.vocab_size
)
```

### Pitfall 7: Reusing LogitsProcessor

**Problem:** Using same LogitsProcessor for multiple `generate()` calls.

```python
# WRONG - state is not reset between calls
processor = LogitsProcessor(compiled_grammar)
model.generate(..., logits_processor=[processor])
model.generate(..., logits_processor=[processor])  # State is corrupted!

# CORRECT - create new processor for each call
model.generate(..., logits_processor=[LogitsProcessor(compiled_grammar)])
model.generate(..., logits_processor=[LogitsProcessor(compiled_grammar)])
```

---

## Advanced Topics

### Multi-Tool Calls Per Turn

Extend the grammar to allow multiple tool calls:

```ebnf
root ::= function_call+
function_call ::= "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>"

tool_name ::= "tool_a" | "tool_b"
arg_body ::= [^}]*
```

**Note:** Your tool execution loop must handle multiple calls.

### Dynamic Grammar Generation

Build grammars dynamically from tool schemas:

```python
def build_grammar_from_tools(tools: list[dict]) -> str:
    tool_names = [t["function"]["name"] for t in tools if t["type"] == "function"]
    tool_alts = " | ".join(f'"{name}"' for name in tool_names)

    return f'''root ::= "<start_function_call>" "call:" tool_name "{{" arg_body "}}" "<end_function_call>"
tool_name ::= {tool_alts}
arg_body ::= [^}}]*
'''
```

### Caching Grammars

Grammar compilation has some overhead. Cache when tools don't change:

```python
from functools import lru_cache

@lru_cache(maxsize=32)
def get_cached_grammar(tool_names: tuple[str, ...]) -> str:
    tools = [{"type": "function", "function": {"name": n}} for n in tool_names]
    return build_functiongemma_grammar(tools)
```

**GrammarCompiler also caches internally** - same grammar string compiles once:

```python
compiler = xgr.GrammarCompiler(tokenizer_info, cache_enabled=True)
compiled1 = compiler.compile_grammar(grammar)  # Compiles
compiled2 = compiler.compile_grammar(grammar)  # Returns cached
```

### Fallback Without Grammar

Support environments where XGrammar isn't available:

```python
def call_model(tools, use_grammar=True):
    extra_body = None
    if use_grammar:
        try:
            grammar = build_functiongemma_grammar(tools)
            extra_body = {"structured_outputs": {"type": "grammar", "grammar": grammar}}
        except Exception as e:
            logger.warning(f"Grammar build failed: {e}, falling back to no grammar")

    return client.chat.completions.create(
        ...,
        extra_body=extra_body,
    )
```

### Batched Inference

For multiple concurrent requests with different grammars:

```python
import xgrammar as xgr

# Setup (once per model)
tokenizer_info = xgr.TokenizerInfo.from_huggingface(tokenizer, vocab_size=config.vocab_size)
compiler = xgr.GrammarCompiler(tokenizer_info)

# Per-request: different schemas
schemas = [schema1, schema2, schema3]
compiled_grammars = [compiler.compile_json_schema(s) for s in schemas]

# Create matchers (one per request)
batch_size = len(schemas)
matchers = [xgr.GrammarMatcher(cg) for cg in compiled_grammars]

# Allocate bitmask
bitmask = xgr.allocate_token_bitmask(batch_size, tokenizer_info.vocab_size)

# Create batch matcher for parallel bitmask filling
batch_matcher = xgr.BatchGrammarMatcher(max_threads=8)

# Generation loop
while not all(m.is_terminated() for m in matchers):
    logits = model_forward(...)  # Shape: (batch_size, vocab_size)

    # Fill bitmasks in parallel
    batch_matcher.batch_fill_next_token_bitmask(matchers, bitmask)
    xgr.apply_token_bitmask_inplace(logits, bitmask.to(logits.device))

    # Sample tokens
    next_tokens = sample(logits)

    # Update matchers
    for i, token in enumerate(next_tokens):
        if not matchers[i].is_terminated():
            matchers[i].accept_token(token)
```

### Jump-Forward Decoding

Skip deterministic token sequences:

```python
matcher = xgr.GrammarMatcher(compiled_grammar)

# After some tokens, find deterministic continuation
jump_str = matcher.find_jump_forward_string()
if jump_str:
    # Accept the string without LLM inference
    matcher.accept_string(jump_str)
    output += jump_str
```

### Speculative Decoding Support

XGrammar supports rollback for speculative decoding:

```python
# Accept speculative tokens
for token in speculative_tokens:
    if not matcher.accept_token(token):
        break

# If some were rejected, rollback
matcher.rollback(num_rejected_tokens)
```

---

## Structural Tags

Structural tags provide a JSON-config-based way to describe complex output formats, especially useful for tool calling across different model formats.

### Basic Concepts

A structural tag describes a response format like:
```json
{
    "type": "structural_tag",
    "format": { ... format object ... }
}
```

### Format Types

#### 1. const_string

LLM output must exactly match the given string:

```python
from xgrammar.structural_tag import ConstStringFormat

format = ConstStringFormat(value="Let's think step by step")
```

#### 2. json_schema

Output must be valid JSON matching the schema:

```python
from xgrammar.structural_tag import JSONSchemaFormat

format = JSONSchemaFormat(
    json_schema={"type": "object", "properties": {"name": {"type": "string"}}},
    style="json",  # "json", "qwen_xml", "minimax_xml", "deepseek_xml"
)
```

#### 3. grammar

Match a custom EBNF grammar:

```python
from xgrammar.structural_tag import GrammarFormat

format = GrammarFormat(grammar='root ::= "hello" | "world"')
```

#### 4. regex

Match a regex pattern:

```python
from xgrammar.structural_tag import RegexFormat

format = RegexFormat(pattern=r"\d{3}-\d{4}")
```

#### 5. any_text

Allow any text (with optional exclusions):

```python
from xgrammar.structural_tag import AnyTextFormat

format = AnyTextFormat(excludes=["<forbidden>", "</forbidden>"])
```

#### 6. sequence

Match formats in order:

```python
from xgrammar.structural_tag import SequenceFormat, ConstStringFormat, JSONSchemaFormat

format = SequenceFormat(elements=[
    ConstStringFormat(value="Result: "),
    JSONSchemaFormat(json_schema={"type": "integer"}),
])
```

#### 7. or

Match any one of the formats:

```python
from xgrammar.structural_tag import OrFormat

format = OrFormat(elements=[format1, format2])
```

#### 8. tag

Match `begin content end` pattern:

```python
from xgrammar.structural_tag import TagFormat, AnyTextFormat

format = TagFormat(
    begin="<think>",
    content=AnyTextFormat(),
    end="</think>",  # Can also be a list: ["</think>", "</reasoning>"]
)
```

#### 9. triggered_tags

Allow free text until trigger, then match tag:

```python
from xgrammar.structural_tag import TriggeredTagsFormat, TagFormat, JSONSchemaFormat

format = TriggeredTagsFormat(
    triggers=["<function="],
    tags=[
        TagFormat(
            begin="<function=get_weather>",
            content=JSONSchemaFormat(json_schema=weather_schema),
            end="</function>",
        ),
        TagFormat(
            begin="<function=get_time>",
            content=JSONSchemaFormat(json_schema=time_schema),
            end="</function>",
        ),
    ],
    at_least_one=False,     # Require at least one tool call
    stop_after_first=False, # Stop after first tool call
    excludes=[],            # Strings to exclude before trigger
)
```

#### 10. tags_with_separator

Match tags separated by a delimiter:

```python
from xgrammar.structural_tag import TagsWithSeparatorFormat

format = TagsWithSeparatorFormat(
    tags=[tag1, tag2],
    separator=",",
    at_least_one=False,
    stop_after_first=False,
)
```

### Tool Calling Examples

#### Llama JSON-style

```python
from xgrammar.structural_tag import StructuralTag, TriggeredTagsFormat, TagFormat, JSONSchemaFormat

structural_tag = StructuralTag(
    format=TriggeredTagsFormat(
        triggers=['{"name":'],
        tags=[
            TagFormat(
                begin='{"name": "get_weather", "parameters": ',
                content=JSONSchemaFormat(json_schema=weather_schema),
                end="}",
            ),
        ],
    )
)
```

#### Llama Custom XML-style

```python
structural_tag = StructuralTag(
    format=TriggeredTagsFormat(
        triggers=["<function="],
        tags=[
            TagFormat(
                begin="<function=get_weather>",
                content=JSONSchemaFormat(json_schema=weather_schema),
                end="</function>",
            ),
        ],
    )
)
```

#### Qwen/Hermes Style

```python
structural_tag = StructuralTag(
    format=TriggeredTagsFormat(
        triggers=["<tool_call>"],
        tags=[
            TagFormat(
                begin='<tool_call>\n{"name": "get_weather", "arguments": ',
                content=JSONSchemaFormat(json_schema=weather_schema),
                end='}\n</tool_call>',
            ),
        ],
    )
)
```

#### Force Thinking + Tool Call

```python
structural_tag = StructuralTag(
    format=SequenceFormat(elements=[
        TagFormat(
            begin="<think>",
            content=AnyTextFormat(),
            end="</think>",
        ),
        TriggeredTagsFormat(
            triggers=["<function="],
            tags=[...],
            at_least_one=True,
            stop_after_first=True,
        ),
    ])
)
```

### Using Structural Tags

```python
import xgrammar as xgr
from xgrammar.structural_tag import StructuralTag

# Build structural tag
structural_tag = StructuralTag(format=...)

# Compile
compiled = compiler.compile_structural_tag(structural_tag)

# Or create grammar directly
grammar = xgr.Grammar.from_structural_tag(structural_tag)
```

---

## Runtime Safeguards

### Recursion Limit

XGrammar limits recursion depth to prevent stack overflow:

```python
import xgrammar as xgr

# Get/set recursion limit
current = xgr.get_max_recursion_depth()  # Default: 10000
xgr.set_max_recursion_depth(20000)

# Use context manager
with xgr.max_recursion_depth(5000):
    matcher.accept_token(token_id)
```

**Note:** Since XGrammar v0.1.21, the Earley parser eliminated recursion during parsing, so this is rarely needed.

### Cache Size Limit

Limit grammar compiler cache memory:

```python
compiler = xgr.GrammarCompiler(
    tokenizer_info,
    cache_enabled=True,
    cache_limit_bytes=128 * 1024 * 1024,  # 128 MB
)

# Check cache usage
print(f"Cache size: {compiler.get_cache_size_bytes()} bytes")
print(f"Cache limit: {compiler.cache_limit_bytes} bytes")

# Clear cache
compiler.clear_cache()
```

---

## Debugging

### "Invalid grammar specification" Error

**Cause:** EBNF syntax is invalid.

**Debug steps:**
1. Run local validation: `uv run python scripts/test_grammar.py validate --show-grammar`
2. Use XGrammar directly:
   ```python
   try:
       grammar = xgr.Grammar.from_ebnf(ebnf_string)
   except RuntimeError as e:
       print(f"Parse error: {e}")
   ```
3. Check for:
   - Unbalanced quotes
   - Invalid escape sequences in character classes
   - Missing rule definitions
   - Newlines breaking rule definitions

### 0% Tool Call Rate with Grammar

**Cause:** Using `tool_choice="none"`.

**Solution:** Change to `tool_choice="auto"`.

### Model Generates Degenerate Output (Endless Whitespace)

**Cause:** Grammar allows `ws?` (optional whitespace) in problematic positions.

**Solution:** Use strict grammar without optional whitespace:

```ebnf
# Before (problematic)
root ::= ws? "<start_function_call>" "call:" ws? tool_name ...

# After (fixed)
root ::= "<start_function_call>" "call:" tool_name ...
```

### Model Picks Wrong Tool Repeatedly

**Cause:** This is model behavior, not a grammar issue. Small models (270M params) may struggle with multi-turn reasoning.

**Diagnosis:** The grammar is working if:
- Tool call rate is ~100%
- Tool names are always valid (from your list)
- Format is always correct

**Mitigations:**
- Improve system prompt
- Increase model size
- Add more explicit instructions in user messages

### Debug Printing

Enable debug output for detailed information:

```python
# Debug token acceptance
accepted = matcher.accept_token(token_id, debug_print=True)

# Debug bitmask generation
need_apply = matcher.fill_next_token_bitmask(bitmask, debug_print=True)

# Print internal matcher state
print(matcher._debug_print_internal_state())
```

### Viewing Raw Grammar Output

```python
import asyncio
from openai import AsyncOpenAI
from remora.grammar import build_functiongemma_grammar

tools = [{"type": "function", "function": {"name": "my_tool", "description": "..."}}]
grammar = build_functiongemma_grammar(tools)

print("Grammar:")
print(grammar)

async def test():
    client = AsyncOpenAI(base_url="http://localhost:8000/v1", api_key="EMPTY")
    response = await client.chat.completions.create(
        model="google/functiongemma-270m-it",
        messages=[{"role": "user", "content": "Call my_tool"}],
        tools=tools,
        tool_choice="auto",
        extra_body={"structured_outputs": {"type": "grammar", "grammar": grammar}},
    )
    msg = response.choices[0].message
    print(f"Content: {msg.content!r}")
    print(f"Tool calls: {msg.tool_calls}")

asyncio.run(test())
```

### Testing Utilities

XGrammar provides testing utilities for debugging:

```python
from xgrammar.testing import (
    _is_grammar_accept_string,
    _get_masked_tokens_from_bitmask,
    bitmask_to_bool_mask,
    bool_mask_to_bitmask,
)

# Check if grammar accepts string
accepts = _is_grammar_accept_string(grammar, "test string")

# Get rejected token IDs from bitmask
rejected_ids = _get_masked_tokens_from_bitmask(bitmask, vocab_size)

# Convert between bitmask formats
bool_mask = bitmask_to_bool_mask(bitmask, vocab_size)
bitmask = bool_mask_to_bitmask(bool_mask)
```

---

## Quick Reference

### Minimal Working Example

```python
from openai import OpenAI

tools = [
    {"type": "function", "function": {"name": "greet", "description": "Greet someone"}},
]

grammar = '''root ::= "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>"
tool_name ::= "greet"
arg_body ::= [^}]*
'''

client = OpenAI(base_url="http://localhost:8000/v1", api_key="EMPTY")

response = client.chat.completions.create(
    model="google/functiongemma-270m-it",
    messages=[{"role": "user", "content": "Greet me"}],
    tools=tools,
    tool_choice="auto",  # Important!
    extra_body={"structured_outputs": {"type": "grammar", "grammar": grammar}},
)

print(response.choices[0].message.tool_calls)
# [ChatCompletionMessageToolCall(function=Function(name='greet', arguments='{}'), ...)]
```

### Checklist

- [ ] Server started with `--tool-call-parser functiongemma`
- [ ] Using `tool_choice="auto"` (not `"none"`)
- [ ] Grammar validated locally before deployment
- [ ] Using strict grammar (no `ws?` patterns)
- [ ] Character classes use `[^}]` not complex enumerations
- [ ] Tool names in grammar match tool schemas exactly
- [ ] Using `config.vocab_size` not `tokenizer.vocab_size`
- [ ] Creating new LogitsProcessor for each generate() call

---

## Summary

XGrammar structured outputs provide **hard guarantees** about FunctionGemma tool call formatting:

1. **100% tool call rate** - Model cannot output plain text
2. **No hallucinated tools** - Enum constrains to valid names only
3. **Guaranteed format** - Always matches FunctionGemma syntax

**Key configuration:**
- `tool_choice="auto"` - Enables tool_calls extraction
- Strict grammar - No optional whitespace
- `[^}]` character class - Simple and robust

**Test locally first:**
```bash
uv run python scripts/test_grammar.py full-test
```

**XGrammar Core Classes:**
- `TokenizerInfo` - Per-model tokenizer information
- `GrammarCompiler` - Per-model grammar compiler (reusable, caches)
- `CompiledGrammar` - Compiled grammar (cacheable)
- `GrammarMatcher` - Per-request state machine
