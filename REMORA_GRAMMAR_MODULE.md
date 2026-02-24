# The Missing remora.grammar Module

## Executive Summary

The `remora.grammar` module is a planned but **not yet implemented** component of the remora library. It is referenced in `scripts/test_grammar.py` but does not exist in the codebase. This report explains why this is a problem, what the module should do, and why it's critical for the Qwen integration.

---

## The Problem

### Current State

The file `scripts/test_grammar.py` contains this import:

```python
from remora.grammar import build_functiongemma_grammar
```

However, there is **no `remora/grammar.py`** file in the codebase:

```
$ ls -la src/remora/
analyzer.py      context/    errors.py     hub/       queries/   utils/
cli.py           discovery/  events.py     __init__.py  results.py  watcher.py
client.py        externals.py  kernel_runner.py  orchestrator.py  testing/
```

### Diagnostic Error

Running any Python analysis shows the import cannot be resolved:

```
ERROR [29:6] Import "remora.grammar" could not be resolved
```

---

## Why This Is an Issue

### 1. Grammar Testing is Broken

The `scripts/test_grammar.py` script is designed to:
- Validate EBNF grammar syntax locally
- Test grammars against sample inputs
- Generate valid/invalid sample strings
- Check if xgrammar package is available

Without `remora.grammar`, none of these tests can run.

### 2. No Local Grammar Development

The module was intended to allow developers to:
- **Iterate on grammars quickly** without starting vLLM
- **Validate grammar syntax** before deploying
- **Test tool call parsing** in isolation
- **Generate test cases** for different tool configurations

### 3. Missing Qwen Grammar

To add Qwen as a first-class model, we need:
- A Qwen-specific grammar builder (similar to functiongemma)
- The ability to switch between model formats
- Local testing/validation capabilities

---

## What the Module Should Contain

### 1. Grammar Builder Functions

```python
# src/remora/grammar.py

def build_functiongemma_grammar(
    tools: list[dict[str, Any]],
    *,
    allow_parallel_calls: bool = True,
    args_format: str = "permissive",
) -> str:
    """
    Build EBNF grammar for FunctionGemma tool calling format.
    
    Format: <start_function_call>call:tool_name{args}<end_function_call>
    
    Args:
        tools: List of tool schemas in OpenAI format
        allow_parallel_calls: Allow multiple tool calls in one response
        args_format: "strict" | "permissive" | "escaped_strings" | "json"
    
    Returns:
        EBNF grammar string in GBNF format
    """
    ...

def build_qwen3_grammar(
    tools: list[dict[str, Any]],
    *,
    allow_parallel_calls: bool = True,
    args_format: str = "permissive",
    style: str = "qwen_xml",
) -> str:
    """
    Build EBNF grammar for Qwen3 tool calling format.
    
    Format: <tool_call><function=tool_name><parameter=name>value</parameter>...
    
    Args:
        tools: List of tool schemas in OpenAI format
        allow_parallel_calls: Allow multiple tool calls in one response
        args_format: "strict" | "permissive" | "json"
        style: "qwen_xml" | "qwen_coder"
    
    Returns:
        EBNF grammar string in GBNF format
    """
    ...

def build_grammar(
    tools: list[dict[str, Any]],
    model_format: str,
    **kwargs: Any,
) -> str:
    """
    Build grammar for specified model format.
    
    Args:
        tools: List of tool schemas
        model_format: "functiongemma" | "qwen3" | "openai" | etc.
        **kwargs: Additional format-specific options
    
    Returns:
        EBNF grammar string
    """
    builders = {
        "functiongemma": build_functiongemma_grammar,
        "qwen3": build_qwen3_grammar,
        # Add more as needed
    }
    
    builder = builders.get(model_format)
    if not builder:
        raise ValueError(f"Unknown model format: {model_format}")
    
    return builder(tools, **kwargs)
```

### 2. Grammar Format Reference

Based on bundle.yaml configurations, the module should support:

| Parameter | Values | Description |
|-----------|--------|-------------|
| `mode` | `ebnf`, `json_schema`, `structural_tag` | Output format type |
| `allow_parallel_calls` | `true`, `false` | Allow multiple tool calls |
| `args_format` | `permissive`, `strict`, `escaped_strings`, `json` | How to format arguments |

### 3. FunctionGemma Format Reference

From test samples in `test_grammar.py`:

```
<start_function_call>call:simple_tool{payload:<escape>ping<escape>}<end_function_call>
<start_function_call>call:submit_result{summary:<escape>Done<escape>, changed_files:[]}<end_function_call>
<start_function_call>call:simple_tool{}<end_function_call>
```

**Structure:**
- Wrapper: `<start_function_call>...<end_function_call>`
- Tool invocation: `call:tool_name{...}`
- Arguments: `key:value` pairs separated by commas
- Escaping: `<escape>value<escape>` for special characters

### 4. Qwen3 Format Reference

From vLLM documentation:

```
<tool_call>
<function=get_weather>
<parameter=city>{"city": "London"}</parameter>
</function>
</tool_call>
```

**Structure:**
- Wrapper: `<tool_call>...</tool_call>`
- Tool name: `<function=tool_name>`
- Parameters: `<parameter=name>value</parameter>`

---

## Why We Need This Module

### 1. Testing Without vLLM

The primary use case is **local testing and development**:

```bash
# Validate grammar syntax
python scripts/test_grammar.py validate

# Test against sample inputs
python scripts/test_grammar.py test

# Generate grammar for specific tools
python scripts/test_grammar.py generate run_linter apply_fix --output grammar.ebnf
```

### 2. Grammar Development Workflow

Without this module:
- Developers must start vLLM to test grammar changes
- Iteration is slow (minutes per change)
- Can't run automated tests in CI/CD

With this module:
- Instant local validation (milliseconds)
- Fast iteration on grammar design
- CI/CD integration possible

### 3. Multi-Model Support

To support both FunctionGemma and Qwen, we need:
- A unified interface for grammar building
- Model-specific format implementations
- Easy switching between formats

### 4. Integration with structured-agents

The grammar module should integrate with structured-agents:

```
remora.grammar          structured-agents         vLLM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
build_functiongemma_grammar() ──► Grammar ──► constrained decoding
build_qwen3_grammar() ─────────► Grammar ──► constrained decoding
```

---

## Implementation Plan

### Phase 1: Basic Module Structure

1. Create `src/remora/grammar.py`
2. Implement `build_functiongemma_grammar()`
3. Add basic tests

### Phase 2: Qwen Support

1. Implement `build_qwen3_grammar()`
2. Add Qwen format options (qwen_xml, qwen_coder)
3. Test against actual model outputs

### Phase 3: Integration

1. Connect with structured-agents
2. Update bundle.yaml configurations
3. End-to-end testing

---

## Key Files That Will Use This Module

| File | Usage |
|------|-------|
| `scripts/test_grammar.py` | Import `build_functiongemma_grammar` |
| `bundle.yaml` (agents) | Grammar configuration reference |
| `structured-agents` | Grammar integration |
| Tests | Validation and testing |

---

## References

- **FunctionGemma Format**: `<start_function_call>call:tool{args}<end_function_call>`
- **Qwen3 Format**: `<tool_call><function=tool><parameter=name>val</parameter></function></tool_call>`
- **GBNF Specification**: https://github.com/ggerganov/llama.cpp/blob/master/grammars/README.md
- **XGrammar**: https://xgrammar.mlc.ai/docs/api/python/grammar.html
