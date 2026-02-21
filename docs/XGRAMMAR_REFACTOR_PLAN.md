# Plan: XGrammar-Based FunctionGemma Tool Call Enforcement

## Executive Summary

**Is XGrammar a viable path forward?** Yes, it is a compelling approach that can provide "hard guarantees" about tool call formatting, complementing the existing fixes to conversation history and JSON fallback parsing.

**The key insight**: vLLM's XGrammar structured outputs can *constrain token-by-token decoding* to force the model to emit FunctionGemma-format tool calls, even if the model occasionally tries to output plain text or malformed responses.

**Chosen approach:**
- **Grammar type**: Permissive (forces wrapper format + tool name enum, freeform args)
- **Scope**: Full integration into runner config AND harness CLI

---

## Current State Analysis

### Existing Issues (from HARNESS_IMPROVEMENT_REVIEW.md)
1. **Conversation history** - Now fixed in `runner.py` (returns `self.messages`)
2. **JSON fallback parsing** - Implemented in `tool_parser.py` with FunctionGemma regex
3. **Tool call reliability** - Still variable; model sometimes outputs text instead of calls

### Current FunctionGemma Setup
```bash
vllm serve google/functiongemma-270m-it \
    --enable-auto-tool-choice \
    --tool-call-parser functiongemma \
    --chat-template /app/tool_chat_template_functiongemma.jinja
```

The server already has the FunctionGemma parser enabled, which means structured-output-constrained text in FunctionGemma format will be parsed into `tool_calls`.

---

## XGrammar Approach: How It Works

### Mechanism
1. Client sends `extra_body={"structured_outputs": {"type": "grammar", "grammar": ebnf_grammar}}`
2. vLLM's XGrammar backend constrains decoding so output **must match** the grammar
3. Model emits: `<start_function_call>call:tool_name{args}<end_function_call>`
4. vLLM's FunctionGemma parser converts this to `message.tool_calls`

### Benefits
- **Hard format guarantees** - Model cannot output non-tool-call text
- **Tool name enforcement** - Enum constrains to valid tools only
- **No invented tools** - Model cannot hallucinate tool names
- **Works with existing parser** - vLLM's FunctionGemma parser handles the rest

### Trade-offs
- Grammar doesn't validate argument schemas (required keys, types, enums)
- Need post-parse validation for full schema compliance
- Slightly more complex client-side code

---

## Implementation Plan

### Step 1: Create Grammar Builder Module

**New file**: `src/remora/grammar.py`

Build EBNF grammars dynamically from tool schemas:

```python
"""FunctionGemma grammar builder for vLLM structured outputs."""

from __future__ import annotations
from typing import Any

def build_functiongemma_grammar(tools: list[dict[str, Any]]) -> str:
    """Build a permissive EBNF grammar for FunctionGemma tool calls.

    Args:
        tools: OpenAI-format tool schemas

    Returns:
        EBNF grammar string for vLLM structured outputs
    """
    # Extract function names from tools
    tool_names = [
        t["function"]["name"]
        for t in tools
        if t.get("type") == "function"
        and isinstance(t.get("function"), dict)
        and "name" in t["function"]
    ]
    if not tool_names:
        raise ValueError("No function tools found in schema")

    # Escape tool names for EBNF (handle special chars if any)
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    tool_alts = " | ".join(f'"{esc(n)}"' for n in tool_names)

    # Permissive grammar: forces wrapper + tool enum, freeform args
    return f'''root ::= ws? "<start_function_call>" "call:" tool_name "{{" arg_body "}}" "<end_function_call>" ws?

tool_name ::= {tool_alts}

arg_body ::= arg_char*
arg_char ::= [^}}]

ws ::= [ \\t\\r\\n]+
'''
```

This generates a grammar like:
```ebnf
root ::= ws? "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>" ws?
tool_name ::= "simple_tool" | "submit_result"
arg_body ::= arg_char*
arg_char ::= [^}]
ws ::= [ \t\r\n]+
```

### Step 2: Add Grammar Option to Runner Config

**Modify**: `src/remora/config.py`

Add `use_grammar_enforcement` field to `RunnerConfig`:

```python
@dataclass
class RunnerConfig:
    # ... existing fields ...
    use_grammar_enforcement: bool = False
```

### Step 3: Integrate Grammar into Runner

**Modify**: `src/remora/runner.py`

Add import at top:
```python
from remora.grammar import build_functiongemma_grammar
```

In `_call_model()`, modify the `_attempt()` closure (~line 411):

```python
async def _attempt() -> Any:
    extra_body: dict[str, Any] | None = None

    # Build grammar if enforcement is enabled
    if self.runner_config.use_grammar_enforcement:
        grammar = build_functiongemma_grammar(tools_payload)
        extra_body = {
            "structured_outputs": {
                "type": "grammar",
                "grammar": grammar,
            }
        }
        # When using grammar, set tool_choice="none" to avoid conflicts
        # The grammar itself forces tool call format
        effective_tool_choice = "none"
    else:
        effective_tool_choice = tool_choice

    return await self._http_client.chat.completions.create(
        model=self._model_target,
        messages=cast(list[ChatCompletionMessageParam], prompt_messages),
        tools=cast(list[ChatCompletionToolParam], tools_payload),
        tool_choice=cast(Any, effective_tool_choice),
        max_tokens=self.runner_config.max_tokens,
        temperature=self.runner_config.temperature,
        extra_body=extra_body,
    )
```

**Key point**: When grammar enforcement is on, we set `tool_choice="none"` because:
- Grammar already forces FunctionGemma format
- vLLM's FunctionGemma parser extracts `tool_calls` from the constrained output
- Using `tool_choice="required"` would conflict with grammar mode

### Step 4: Add Harness CLI Options

**Modify**: `scripts/functiongemma_harness.py`

```python
@app.command()
def main(
    # ... existing options ...
    use_grammar: bool = typer.Option(False, "--use-grammar", help="Use XGrammar structured outputs for guaranteed tool call format"),
):
```

The harness should pass this through to `runner_config.use_grammar_enforcement`.

### Step 5: Update Configuration

**Modify**: `remora.yaml`

```yaml
runner:
  # ... existing fields ...
  use_grammar_enforcement: false  # Set true for guaranteed tool call format
```

When enabled globally, all agents will use grammar enforcement. Can be overridden per-run via harness CLI.

---

## Grammar Implementation Details

### Permissive Grammar (Chosen Approach)
```ebnf
root ::= ws? "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>" ws?

tool_name ::= "simple_tool" | "submit_result"  # Dynamic from tools

arg_body ::= (arg_char)*
arg_char ::= [^}]

ws ::= [ \t\r\n]+
```

**Why permissive:**
- Forces correct wrapper format (`<start_function_call>...<end_function_call>`)
- Tool name constrained to enum (no hallucinated tools)
- Arguments freeform (existing `tool_parser.py` regex handles extraction)
- Simpler grammar = faster compilation, fewer edge cases
- Can upgrade to strict later if needed

### Future Enhancement: Strict Key-Value Arguments
```ebnf
root ::= ws? "<start_function_call>" "call:" tool_name ws? obj "<end_function_call>" ws?

tool_name ::= "simple_tool" | "submit_result"

obj ::= "{" ws? (pair (ws? "," ws? pair)*)? ws? "}"
pair ::= ident ws? ":" ws? value

value ::= escaped_string | number | boolean | "null" | obj | arr
arr ::= "[" ws? (value (ws? "," ws? value)*)? ws? "]"

escaped_string ::= "<escape>" str_char* "<escape>"
str_char ::= str_safe | str_esc
str_safe ::= [^<\\]
str_esc  ::= "\\" ["\\"/bfnrt]

number ::= "-"? int frac? exp?
int    ::= "0" | [1-9] [0-9]*
frac   ::= "." [0-9]+
exp    ::= ("e"|"E") ("+"|"-")? [0-9]+

boolean ::= "true" | "false"
ident ::= [A-Za-z_] [A-Za-z0-9_]*
ws ::= [ \t\r\n]+
```

- Forces FunctionGemma's `<escape>...<escape>` string convention
- Validates object structure
- Still doesn't enforce required keys per tool

---

## Files to Modify/Create

| File | Action | Description |
|------|--------|-------------|
| `src/remora/grammar.py` | **CREATE** | Grammar builder from tool schemas |
| `src/remora/config.py` | MODIFY | Add `use_grammar_enforcement: bool` to RunnerConfig |
| `src/remora/runner.py` | MODIFY | Add `extra_body` with grammar to API call |
| `scripts/functiongemma_harness.py` | MODIFY | Add `--use-grammar` CLI option |
| `remora.yaml` | MODIFY | Add `runner.use_grammar_enforcement: false` |

---

## Testing Strategy

### Phase 1: Baseline (No Grammar)
```bash
python scripts/functiongemma_harness.py \
    --tool-choice auto \
    --requests-per-variant 50
```
Record tool call rate (expected: 60-80%).

### Phase 2: Grammar Enforcement via Harness
```bash
python scripts/functiongemma_harness.py \
    --use-grammar \
    --requests-per-variant 50
```
Expected: Near 100% tool call rate (grammar forces format).

### Phase 3: Grammar via Config
```bash
# Set in remora.yaml: runner.use_grammar_enforcement: true
python scripts/functiongemma_harness.py \
    --requests-per-variant 50
```
Verify config-based grammar works.

### Phase 4: Production Agent Testing
Test multi-turn agents with grammar enabled:
```bash
# Enable grammar in remora.yaml, then:
remora lint path/to/file.py --verbose
remora docstring path/to/file.py --verbose
```
Verify multi-turn conversations work with grammar enforcement.

---

## Expected Outcomes

| Metric | Without Grammar | With Grammar |
|--------|-----------------|--------------|
| Tool call rate | ~60-80% | ~99%+ |
| Format errors | Occasional | None |
| Invalid tool names | Possible | Impossible |
| Non-tool responses | Possible | Impossible |

---

## Risks and Mitigations

### Risk 1: vLLM Version Compatibility
- **Mitigation**: Test against current vLLM version; document minimum version requirements

### Risk 2: Performance Overhead
- **Mitigation**: Grammar compilation is cached by XGrammar; minimal runtime impact

### Risk 3: Argument Validation
- **Mitigation**: Grammar ensures structure, post-parse validation handles schema compliance

### Risk 4: Multi-Tool Call Support
- **Mitigation**: Grammar can be extended for multiple calls:
```ebnf
root ::= ws? function_call (ws? function_call)* ws?
function_call ::= "<start_function_call>" "call:" tool_name ws? obj "<end_function_call>"
```

---

## Alternative Approaches Considered

1. **`tool_choice="required"` only** - Doesn't guarantee FunctionGemma format
2. **Prompt engineering only** - No hard guarantees, model can still deviate
3. **JSON mode** - Not compatible with FunctionGemma's custom format

XGrammar provides the strongest guarantees while remaining compatible with the existing FunctionGemma parser pipeline.

---

## Part 2: Library Simplification (If XGrammar Becomes Standard)

If XGrammar grammar enforcement becomes the standard approach, significant code can be removed or simplified because grammar **guarantees** the output format.

### What Can Be Removed

#### 1. `src/remora/tool_parser.py` - ~90% Removable

| Component | Lines | Reason |
|-----------|-------|--------|
| `_FUNCTIONGEMMA_CALL_RE` regex | 33-36 | Grammar guarantees format |
| `_FUNCTIONGEMMA_ARG_RE` regex | 37-40 | Same |
| `_parse_functiongemma_call()` | 43-54 | vLLM parser handles this |
| Most of `parse_tool_call_from_content()` | 57-125 | `message.tool_calls` always populated |

**Simplified version:**
```python
def parse_tool_call_from_content(content: str) -> ParsedToolCall | None:
    """No longer needed - grammar guarantees tool_calls."""
    return None
```

#### 2. `src/remora/runner.py` - ~150 Lines Removable

| Method | Lines | Action |
|--------|-------|--------|
| `_handle_no_tool_calls()` | 514-552 | Simplify to just return result |
| `_dispatch_parsed_tool_call()` | 554-624 | **Remove entirely** |
| `_initial_tool_choice()` | 472-481 | Remove FunctionGemma workaround |
| `_normalize_tool_choice()` | 483-486 | Remove "required"→"auto" hack |
| `_uses_functiongemma()` | 122-125 | May be removed entirely |

**Simplifications:**

```python
# _handle_no_tool_calls becomes trivial
async def _handle_no_tool_calls(self, message: ChatCompletionMessage) -> AgentResult | None:
    """With grammar enforcement, this should rarely be called."""
    return AgentResult.model_validate({
        "status": AgentStatus.SUCCESS,
        "workspace_id": self.workspace_id,
        "changed_files": [],
        "summary": message.content or "",
        "details": {},
        "error": None,
    })

# Tool choice normalization becomes a no-op
def _normalize_tool_choice(self, tool_choice: Any) -> Any:
    return tool_choice  # No FunctionGemma workarounds needed
```

#### 3. Event Emission Cleanup

- Remove `"parsed_from_content": True` event flag (lines 567-578)
- Simplify tool call event emission

### Refactored Architecture

**Before (with defensive code):**
```
Model Response
    │
    ├─► message.tool_calls populated? ──► Yes ──► Dispatch
    │
    └─► No ──► Parse from content
               ├─► FunctionGemma regex
               ├─► Direct JSON format
               └─► OpenAI array format
                   └─► Dispatch parsed call
```

**After (with grammar):**
```
Model Response
    │
    └─► message.tool_calls ALWAYS populated ──► Dispatch
```

### Summary of Removable Code

| File | Lines Removed | % Reduction |
|------|--------------|-------------|
| `tool_parser.py` | ~80 lines | ~90% |
| `runner.py` | ~150 lines | ~15% |
| **Total** | ~230 lines | N/A |

### New File Structure

**Option A: Keep `tool_parser.py` as stub**
- Single function returning `None`
- Maintains import compatibility

**Option B: Remove `tool_parser.py` entirely**
- Update imports in `runner.py`
- Cleaner but breaking change

**Recommended: Option A** (safer migration path)

---

## Revised Implementation Plan

### Phase 1: Add Grammar Support (Non-Breaking)
1. Create `src/remora/grammar.py`
2. Add `use_grammar_enforcement` config option
3. Integrate into runner with `extra_body`
4. Add `--use-grammar` harness CLI option

### Phase 2: Validate & Test
1. Run harness with grammar enabled
2. Verify ~99% tool call rate
3. Test production agents (lint, docstring, test)

### Phase 3: Make Grammar Default
1. Set `use_grammar_enforcement: true` as default
2. Update documentation

### Phase 4: Remove Defensive Code (Breaking)
1. Simplify `tool_parser.py` to stub
2. Remove `_dispatch_parsed_tool_call()`
3. Simplify `_handle_no_tool_calls()`
4. Remove `_uses_functiongemma()` workarounds
5. Clean up event emission

---

## Final File Changes Summary

| File | Phase 1 | Phase 4 |
|------|---------|---------|
| `src/remora/grammar.py` | **CREATE** | - |
| `src/remora/config.py` | Add field | - |
| `src/remora/runner.py` | Add grammar call | Remove ~150 lines |
| `src/remora/tool_parser.py` | - | Simplify to stub (~80 lines removed) |
| `scripts/functiongemma_harness.py` | Add CLI option | - |
| `remora.yaml` | Add config | - |

---

## Conclusion

XGrammar-based structured outputs is a **viable and recommended** approach for improving FunctionGemma tool call reliability. It provides hard guarantees that the model output will be in the correct format, preventing the "model outputs text instead of tool call" failure mode.

**Immediate benefits:**
1. Near 100% tool call rate
2. No hallucinated tool names
3. Guaranteed format compliance

**Long-term benefits (after simplification):**
1. ~230 lines of defensive code removed
2. Simpler, more maintainable codebase
3. Fewer code paths = fewer bugs
4. Cleaner architecture

The implementation is straightforward:
1. Build grammar from tool schemas
2. Pass grammar in `extra_body`
3. Let vLLM's existing parser handle the rest
4. (Later) Remove defensive code that's no longer needed
