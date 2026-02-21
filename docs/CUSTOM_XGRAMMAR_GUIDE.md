# CUSTOM_XGRAMMAR_GUIDE.md
*A practical guide to enforcing FunctionGemma-style tool calls (outer tags + tool-name enforcement + structured args) using vLLM Structured Outputs with the XGrammar backend.*

## Overview
This guide shows how to:
1. Run vLLM for FunctionGemma tool calling (standard parser path).
2. Use **Structured Outputs (guided decoding)** with **XGrammar** to **force** the model to emit **FunctionGemma’s custom text format**:
   - `<start_function_call>call:<tool_name>{...args...}<end_function_call>`
3. Enforce that `<tool_name>` is **one of your OpenAI `tools`**.
4. Tighten argument formatting beyond “anything inside braces” to a **JSON-ish** object form with:
   - `key:value` pairs
   - comma-separated pairs
   - nested objects/arrays
   - booleans/null/numbers
   - strings encoded as `<escape>...<escape>` (FunctionGemma convention)

You can then let vLLM’s **FunctionGemma tool-call parser** convert that text into OpenAI-style `tool_calls` in responses.

---

## Two different mechanisms in vLLM
### A) Parser-based FunctionGemma tool calls
- You prompt the model (via chat template) to emit FunctionGemma tags.
- vLLM decodes text, then the **FunctionGemma tool-call parser** extracts tool calls from the special markers.

**Works best when the model was trained for this format (FunctionGemma).**

### B) Structured outputs / guided decoding (XGrammar)
- vLLM **constrains decoding token-by-token** so output **must match** a grammar/JSON/regex constraint.
- This does **not** require the model to have been trained on that exact format, but quality may vary.
- Here, we use it to force **FunctionGemma’s tag protocol** *and* enforce tool-name selection from your tool list.

**Best when you need “hard guarantees” about formatting.**

---

## Recommended setup for FunctionGemma + XGrammar
### Server command
Use the FunctionGemma template + parser for normal operation, and enable structured outputs (backend selection depends on your vLLM version):

```bash
vllm serve google/functiongemma-270m-it \
  --enable-auto-tool-choice \
  --tool-call-parser functiongemma \
  --chat-template examples/tool_chat_template_functiongemma.jinja
```

Notes:
- `--tool-call-parser functiongemma` lets vLLM extract `<start_function_call>...<end_function_call>` into `tool_calls`.
- `--enable-auto-tool-choice` is for parser-based tool calling. With structured outputs, you may set `tool_choice="none"` and rely on grammar enforcement.

---

## Client pattern
### Key idea
- Provide tools in **standard OpenAI `tools`** format.
- Set `tool_choice="none"` so the server does **not** switch into OpenAI-style tool-call forcing.
- Pass a **structured outputs grammar** in `extra_body` to force the **FunctionGemma** text format.

---

## 1) “Outer-shape only” grammar (choose among tools, enforce name)
This is the simplest: forces a single FunctionGemma call and restricts tool name to an enum derived from tools.
Arguments are permissive.

```ebnf
root ::= ws? "<start_function_call>" "call:" tool_name "{" arg_body "}" "<end_function_call>" ws?

tool_name ::= "get_weather" | "get_time" | "search_web"

arg_body ::= (arg_char)*
arg_char ::= [^}]

ws ::= [ \t\r\n]+
```

This is robust, but it doesn’t validate `key:value` structure.

---

## 2) Stricter grammar: JSON-ish args with `<escape>…<escape>` strings
This version enforces:
- `{ key:value, key2:value2 }`
- nested objects/arrays
- numbers/bools/null
- string values must be encoded as `<escape>...<escape>`

### Grammar (single tool call, tool name chosen from enum)

```ebnf
root ::= ws? "<start_function_call>" "call:" tool_name ws? obj "<end_function_call>" ws?

tool_name ::= "get_weather" | "get_time" | "search_web"

# Object and pairs (FunctionGemma uses braces and colon separators)
obj ::= "{" ws? (pair (ws? "," ws? pair)*)? ws? "}"

pair ::= ident ws? ":" ws? value

value ::= escaped_string | number | boolean | "null" | obj | arr

arr ::= "[" ws? (value (ws? "," ws? value)*)? ws? "]"

# FunctionGemma convention for strings: <escape> ... <escape>
escaped_string ::= "<escape>" str_char* "<escape>"

# Allow most characters, but disallow '<' so we don't accidentally open a new tag.
# Keep backslash escapes minimal/simple.
str_char ::= str_safe | str_esc
str_safe ::= [^<\\]
str_esc  ::= "\\" ["\\\"/bfnrt"]

number ::= "-"? int frac? exp?
int    ::= "0" | [1-9] [0-9]*
frac   ::= "." [0-9]+
exp    ::= ("e"|"E") ("+"|"-")? [0-9]+

boolean ::= "true" | "false"

ident ::= [A-Za-z_] [A-Za-z0-9_]*

ws ::= [ \t\r\n]+
```

### What this does (and doesn’t) guarantee
✅ Guarantees:
- Exactly one FunctionGemma call wrapper
- Tool name is one of your tools
- Args are an object with pairs/values, nested ok
- String values use `<escape>…<escape>`

⚠️ Does **not** guarantee:
- Required keys per tool
- Enum validation from your JSON schema
- “No extra keys” constraints
- Full JSON Schema fidelity

Those are possible but get complex fast; many teams validate arguments after parsing, then reprompt/repair on failure.

---

## 3) Python: build the tool-name enum grammar from OpenAI `tools`
Below is a helper that:
- Reads tool names from standard OpenAI `tools` JSON
- Builds the stricter grammar above with the enum plugged in

```python
from __future__ import annotations
from typing import Any, Dict, List

def build_functiongemma_strict_grammar(tools: List[Dict[str, Any]]) -> str:
    tool_names = [
        t["function"]["name"]
        for t in tools
        if t.get("type") == "function" and isinstance(t.get("function"), dict) and "name" in t["function"]
    ]
    if not tool_names:
        raise ValueError("No function tools found.")

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    tool_alts = " | ".join(f'"{esc(n)}"' for n in tool_names)

    return f\"\"\"\
root ::= ws? "<start_function_call>" "call:" tool_name ws? obj "<end_function_call>" ws?

tool_name ::= {tool_alts}

obj ::= "{{" ws? (pair (ws? "," ws? pair)*)? ws? "}}"
pair ::= ident ws? ":" ws? value

value ::= escaped_string | number | boolean | "null" | obj | arr
arr ::= "[" ws? (value (ws? "," ws? value)*)? ws? "]"

escaped_string ::= "<escape>" str_char* "<escape>"
str_char ::= str_safe | str_esc
str_safe ::= [^<\\\\]
str_esc  ::= "\\\\\\" ["\\\\\\\"/bfnrt"]

number ::= "-"? int frac? exp?
int    ::= "0" | [1-9] [0-9]*
frac   ::= "." [0-9]+
exp    ::= ("e"|"E") ("+"|"-")? [0-9]+

boolean ::= "true" | "false"
ident ::= [A-Za-z_] [A-Za-z0-9_]*
ws ::= [ \\t\\r\\n]+
\"\"\"
```

---

## 4) Client request example (OpenAI-compatible)
This example:
- Provides multiple tools
- Forces output to be one FunctionGemma call with a tool name in your enum
- Uses stricter args object grammar

```python
from openai import OpenAI

tools = [
  {"type":"function","function":{"name":"get_weather","description":"Weather","parameters":{"type":"object","properties":{"location":{"type":"string"}},"required":["location"]}}},
  {"type":"function","function":{"name":"get_time","description":"Time","parameters":{"type":"object","properties":{"tz":{"type":"string"}},"required":["tz"]}}},
]

grammar = build_functiongemma_strict_grammar(tools)

client = OpenAI(base_url="http://localhost:8000/v1", api_key="dummy")

resp = client.chat.completions.create(
    model="google/functiongemma-270m-it",
    messages=[{"role": "user", "content": "What's the weather in London?"}],
    tools=tools,
    tool_choice="none",
    extra_body={
        "structured_outputs": {
            "type": "grammar",
            "grammar": grammar,
            # Some vLLM versions also allow selecting backend; otherwise configure server-side.
            # "backend": "xgrammar",
        }
    },
)

print(resp.choices[0].message.content)
```

Expected output shape (example):

```text
<start_function_call>call:get_weather{location:<escape>London<escape>}<end_function_call>
```

If you started the server with `--tool-call-parser functiongemma`, vLLM can parse that text into `message.tool_calls`.

---

## 5) Multi-tool selection behavior
With the grammar above, the model can still “decide” which tool to call because:
- `tool_name` is a *choice* among your tool names.
- Your prompt + tool descriptions drive which one is most likely.
- But the model **cannot** output a non-tool response, and **cannot** invent a tool name outside your list.

---

## 6) Common pitfalls and how to avoid them
### Pitfall: Tool call forced in OpenAI style instead of FunctionGemma tags
- If you set `tool_choice="required"`, vLLM may force **OpenAI-style** `tool_calls` instead of emitting your FunctionGemma-tagged text.
- If you want **FunctionGemma** tag syntax, keep `tool_choice="none"` and rely on grammar enforcement.

### Pitfall: Arguments don’t match your JSON schema
- Grammar enforces *shape*, not your full schema.
- Do JSON schema validation post-parse:
  1) parse FunctionGemma call -> tool name + args
  2) validate args
  3) repair/retry if invalid

### Pitfall: Strings without `<escape>`
- If you enforce `escaped_string` in grammar, the model must use `<escape>…<escape>`.
- If you prefer normal JSON strings, replace `escaped_string` with JSON-style quoted string rules and adjust your parser expectations.

### Pitfall: Need multiple tool calls per turn
- You can extend `root` to allow repetitions:

```ebnf
root ::= ws? function_call (ws? function_call)* ws?
function_call ::= "<start_function_call>" "call:" tool_name ws? obj "<end_function_call>"
...
```

Be careful: your downstream tool execution loop must handle multiple calls.

---

## 7) How this fits with vLLM’s FunctionGemma parser
**Best practice integration:**
- Use grammar to guarantee a clean FunctionGemma call.
- Let vLLM’s FunctionGemma parser convert it to `tool_calls`.

This yields:
- Hard format guarantees (via XGrammar guided decoding)
- Standard OpenAI-compatible `tool_calls` output for the rest of your stack

---

## Appendix: Making args a bit stricter per-tool (optional)
If you want to enforce *required keys* for a subset of tools, you can:
- generate per-tool productions like `args_get_weather ::= "{" "location" ":" value "}"`
- and then set `tool_name` and args together:

```ebnf
function_call ::= "<start_function_call>" "call:" (
    "get_weather" ws? args_get_weather |
    "get_time"    ws? args_get_time
) "<end_function_call>"
```

This scales poorly for large schemas, but works well for small tool sets.

---

## Summary
- FunctionGemma’s custom format is great when using the native parser path.
- XGrammar structured outputs lets you *enforce* the FunctionGemma wrapper + tool-name enum + structured args.
- Use `tool_choice="none"` when you want the **custom FunctionGemma text format**, and enforce it with a grammar.
- Optionally keep `--tool-call-parser functiongemma` so vLLM produces standard `tool_calls` downstream.
