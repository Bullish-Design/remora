# Remora Code Review

**Date:** 2026-02-18
**Repository:** `Bullish-Design/remora`
**Scope:** Full library review — architecture, correctness, robustness, maintainability, and security

---

## Executive Summary

Remora is a well-structured, thoughtfully designed library for orchestrating multi-turn LLM agents over Python codebases. The core abstractions are clean, the Pydantic v2 data models are thorough, and the codebase is consistently typed (mypy strict mode). The library is at an early `v0.1.0` stage and several major CLI commands (`analyze`, `watch`, `list-agents`) are not yet implemented.

The primary concerns identified are:

1. A fundamental correctness bug in the agent loop when a model response contains multiple tool calls
2. Incomplete error handling at several decision boundaries
3. The `agent_id` field in events does not match the actual `agent_id` naming (`workspace_id`)
4. The node discovery module name is misleading (uses `ast`, not Tree-sitter CST)
5. Several hardcoded values that should be configurable
6. Missing input validation at key security-relevant boundaries

---

## Module-by-Module Review

### `remora/runner.py` — FunctionGemmaRunner

**Rating: 7/10**

This is the most critical file and is generally well implemented. The multi-turn agent loop, tool dispatch, event emission, and result construction are all correct in the common case.

#### Bug: Inner loop `response_text` re-call breaks multi-tool handling

```python
# runner.py:107-119
for tool_call in tool_calls:
    name = tool_call.get("name")
    if name == "submit_result":
        return self._build_submit_result(tool_call.get("arguments"))
    tool_result = await self._dispatch_tool(tool_call)
    tool_payload = json.dumps(tool_result)
    self.messages.append(...)
    response_text = await self._call_model(phase="loop")  # ← called inside the loop
```

When the model returns multiple tool calls in a single response (which `_parse_tool_calls` supports — it can return a list), `_call_model` is invoked after **each individual tool result**, not after all tool results are accumulated. This means:

- The second tool call in the same model response is dispatched correctly, but then a new model call is made immediately after, discarding subsequent tool calls in the original list.
- The model is called `N` extra times per turn for N-tool responses, wasting tokens and TTFT.
- The intent of the loop is ambiguous: is it "process all calls, then re-query" or "process one call, re-query, process next"?

The fix is to accumulate all tool results, append them all, then call the model once outside the loop.

#### Bug: `turn_count` increments before `submit_result` check

```python
# runner.py:95-110
while self.turn_count < self.definition.max_turns:
    self.turn_count += 1
    ...
    for tool_call in tool_calls:
        if name == "submit_result":
            return ...
```

`turn_count` is incremented at the top of the loop, but `submit_result` returns before the model is called again. This means `turn_count` reports one more turn than was actually needed. Not a critical bug, but misleading for observability.

#### The `AGENT_003` error message is reused for two distinct cases

```python
# runner.py:100-106 — no tool calls parsed
message="Model stopped without calling submit_result",

# runner.py:121-127 — turn limit exceeded
message=f"Turn limit {self.definition.max_turns} exceeded",
```

Both use `AGENT_003`. These are meaningfully different failure modes — a missing tool call vs. a turn limit exhaustion — and should use separate error codes to allow callers to distinguish and handle them differently.

#### `_dispatch_tool` swallows unknown tool errors silently

```python
# runner.py:339-342
tool_def = self.definition.tools_by_name.get(str(name)) if name is not None else None
if tool_def is None:
    tool_error = {"error": f"Unknown tool: {name}"}
    self._emit_tool_result(tool_name, tool_error)
    return tool_error
```

An unknown tool returns an error dict and continues. On the next model call, the model receives an "Unknown tool" error message and is expected to self-correct. This is actually the correct behavior for a multi-turn system; however, there is no guard against the model repeatedly calling the same unknown tool, leading to wasted turns and eventual `AGENT_003`. Consider adding a counter and failing fast after N repeated unknown-tool calls.

#### `_build_submit_result` ignores model-reported `status`

```python
# runner.py:279-286
result_data = {
    "status": filtered.get("status", "success"),
    ...
}
```

`AgentResult.status` is `Literal["success", "failed", "skipped"]`. If the model returns an invalid string (e.g., `"added"`, which is the docstring agent's `action` field), Pydantic will raise a `ValidationError`. This exception is not caught in `_build_submit_result`, causing an unhandled exception to bubble up through `run()`. The caller in `orchestrator.py` does catch all exceptions, but the error message will be confusing. Consider explicit validation with a fallback.

#### Hardcoded inference parameters

```python
# runner.py:144-149
response = await self._http_client.chat.completions.create(
    model=self._model_target,
    messages=...,
    max_tokens=512,     # hardcoded
    temperature=0.1,    # hardcoded
)
```

`max_tokens` and `temperature` are not configurable per operation. A lint agent might need more tokens to describe multiple issues, while a docstring agent might need fewer. These should be surfaced in `OperationConfig` or `RunnerConfig`.

#### Event payload: `agent_id` vs `workspace_id` naming inconsistency

The event fields use `"agent_id"` as the key, but the Python object field is `workspace_id`. The value emitted is `self.workspace_id`. This inconsistency means log consumers and the TUI dashboard must know that `agent_id` in events equals `workspace_id` in code. One or the other should be renamed to be consistent.

---

### `remora/orchestrator.py` — Coordinator

**Rating: 8/10**

Clean and well-structured. The use of `asyncio.Semaphore` for concurrency limiting, the try/finally for event stream cleanup, and the double error recording (per-operation vs. per-node) are all correct.

#### `watch_task` lifecycle is fragile

```python
# orchestrator.py:42-43
if isinstance(self._event_emitter, EventStreamController):
    watch_task = asyncio.create_task(self._event_emitter.watch())
```

The watch task is created and cancelled in `process_node`. If `process_node` is called multiple times (for multiple nodes), a new task is created and a new emitter is opened and closed each time. This means the emitter is opened once in `__init__` and closed after every `process_node` call. For a batch of 100 nodes, the file is opened and closed 100 times. The watch task and emitter lifecycle should be tied to the `Coordinator` lifecycle, not individual `process_node` calls.

#### The `return_exceptions=True` in `asyncio.gather` may obscure bugs

```python
# orchestrator.py:97-109
raw = await asyncio.gather(
    *[run_with_limit(op, runner) for op, runner in runners.items()],
    return_exceptions=True,
)
for item in raw:
    if isinstance(item, BaseException):
        errors.append({"phase": "run", "error": str(item)})
```

`run_with_limit` already catches all exceptions and returns `(operation, exc)`. The `return_exceptions=True` combined with `isinstance(item, BaseException)` is a redundant double-catch. The outer `BaseException` check can never be triggered because `run_with_limit` never raises. This dead code path should be removed or the intent clarified.

---

### `remora/discovery.py` — NodeDiscoverer

**Rating: 7/10**

The module works correctly but has several naming and structural issues.

#### Module is named "CST" but uses Python's `ast` module, not a CST library

The module docstring says "CST node discovery utilities" and uses the class name `CSTNode`, but the implementation uses Python's built-in `ast` module which produces an Abstract Syntax Tree, not a Concrete Syntax Tree. A CST preserves whitespace, comments, and formatting; an AST does not. If the intent is to eventually use a true CST library (like `libcst` or Tree-sitter via `pydantree`), the current implementation is a placeholder. This should be clearly documented to avoid confusion.

Additionally, the `queries_dir` and `.scm` query files are loaded and validated by `_load_queries()`, but the query content is never actually used — the `.scm` files are parsed only for syntax validation (balanced parens), and the actual discovery is done directly with `ast.walk()`. This is dead infrastructure that implies a future Tree-sitter integration.

#### `_build_node` has 7 positional arguments plus `assert` chains

```python
# discovery.py:155-177
def _build_node(self, file_path, source_bytes, line_offsets, lines, node, node_type, name):
    ...
    if None in (start_line, start_col, end_line, end_col):
        raise DiscoveryError(...)
    assert start_line is not None
    assert start_col is not None
    ...
```

The `assert` statements immediately after the `None` check are redundant — they exist only to satisfy the type checker. The pattern works but is noisy. A cleaner approach would be a single typed extraction function that narrows the type.

#### `_iter_python_files` returns a list but is documented as an iterator

The method signature says `-> list[Path]` and indeed returns a sorted list, but the name `_iter_*` conventionally implies a generator. Minor naming inconsistency.

#### SHA1 for node IDs

```python
# discovery.py:206-208
def _compute_node_id(file_path: Path, node_type: str, name: str) -> str:
    digest_input = f"{file_path.resolve()}::{node_type}::{name}".encode("utf-8")
    return hashlib.sha1(digest_input).hexdigest()
```

SHA1 is used for a non-security purpose (stable node ID generation), which is fine. However, SHA1 collision resistance is weak. Two nodes in different files with the same name/type and identical resolved paths would collide — but this is practically impossible given the `file_path.resolve()` component. A larger concern is that renaming a function changes its `node_id`, making historical result tracking impossible. The documentation should clearly state this limitation.

---

### `remora/subagent.py` — SubagentDefinition

**Rating: 8/10**

Well-structured Pydantic models. The YAML loading, path resolution, and validation are solid.

#### `tools_by_name` property is recomputed on every access

```python
# subagent.py:89-90
@property
def tools_by_name(self) -> dict[str, ToolDefinition]:
    return {tool.name: tool for tool in self.tools}
```

This property is called in the hot path of `_dispatch_tool` (once per tool call per turn). For a 20-turn agent with multiple tools, this constructs the dict dozens of times. It should be cached using `@cached_property` or computed once in a validator.

#### Duplicate tool names are silently overwritten

If a YAML definition accidentally defines two tools with the same `name`, `tools_by_name` will silently use only the last one. There is no validation for duplicate tool names.

#### Jinja2 template rendering has no error handling

```python
# subagent.py:56-63
def render(self, node: CSTNode) -> str:
    template = jinja2.Template(self.node_context)
    return template.render(...)
```

If `node_context` contains an invalid Jinja2 template (e.g., unclosed `{%`), this will raise a `jinja2.TemplateSyntaxError` that is not caught anywhere in the call chain. The `load_subagent_definition` function validates tool paths but not the Jinja2 template syntax. Template syntax should be validated at load time.

---

### `remora/config.py` — Configuration

**Rating: 9/10**

The configuration management is one of the strongest parts of the library. The layered merge strategy (`_deep_update`), Pydantic validation, and warning system are all well done.

#### DNS check can cause a 5-10 second hang

```python
# config.py:177-187
def _warn_unreachable_server(server: ServerConfig) -> None:
    parsed = urlparse(server.base_url)
    hostname = parsed.hostname
    try:
        socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        warnings.warn(...)
```

`socket.getaddrinfo` is synchronous and blocking. On a system with no DNS configured or a slow resolver, this can block the main thread for 5-10 seconds before timing out. For a CLI tool, this is an unacceptable UX delay. Consider running this in a thread with a short timeout (e.g., 1 second) or making it opt-in.

#### `OperationConfig` uses `extra="allow"` without documenting why

```python
# config.py:55
class OperationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
```

`extra="allow"` means unknown fields in the YAML (like `style: google` in the docstring operation) are silently accepted and stored. This is intentional — it allows operation-specific config fields (e.g., docstring style) — but it is not documented. Unknown fields in other config classes would be rejected by default, making this a non-obvious exception. Add a comment explaining the intent.

#### Error codes `CONFIG_001` and `CONFIG_002` are missing

`errors.py` defines codes starting at `CONFIG_003` and `CONFIG_004`, implying there were originally codes 001 and 002 that are no longer used (or never were). This creates confusion. Either define all codes or renumber sequentially.

---

### `remora/events.py` — Event Streaming

**Rating: 8/10**

Solid implementation. The control-file watching mechanism, null emitter pattern, and JSONL output are all correct.

#### `EventStreamController.watch()` is polling-based with no backoff

```python
# events.py:98-123
async def watch(self, poll_interval: float = 0.5) -> None:
    while True:
        await asyncio.sleep(poll_interval)
        if not control_file.exists():
            continue
        ...
```

The watch loop polls every 500ms indefinitely. For long-running batch jobs over thousands of nodes, this creates unnecessary overhead. The poll interval should be configurable, or the implementation should use `watchfiles` (already a dependency) for inotify-based watching.

#### `JsonlEventEmitter.emit` mutates the input dict

```python
# events.py:54
payload.setdefault("ts", _iso_timestamp())
```

`emit` modifies the caller's dict by adding a `ts` key. If the caller reuses the same dict object after emitting, the timestamp will already be set. This is a side-effect violation — the emitter should add the timestamp to a copy.

---

### `remora/cli.py` — CLI

**Rating: 5/10**

The CLI is at an early stage. The `config` command is functional, but `analyze`, `watch`, and `list-agents` are stubs. This is expected for v0.1.0 but worth noting.

#### Exit code 3 is non-standard

```python
# cli.py:118
raise typer.Exit(code=3) from exc
```

Unix convention uses exit code 1 for general errors and 2 for misuse of shell commands. Exit code 3 is non-standard and may confuse shell scripts wrapping `remora`. Consider using exit code 1 for config errors.

#### No `--version` flag

The CLI has no way to print the installed version. This is standard for Python CLI tools and should be added.

---

### `remora/errors.py`

**Rating: 6/10**

The file is correct but minimal. Error codes are bare string constants with no associated messages or documentation. Consumers must look up error meaning from context alone. Consider a structured approach (e.g., an `ErrorCode` dataclass with code + description + suggested action).

---

### `remora/results.py`

**Rating: 9/10**

Clean and well-typed. The `all_success` property is a useful shortcut.

#### `AgentResult.details` is untyped

```python
# results.py:18
details: dict = Field(default_factory=dict)
```

`dict` with no type parameters is equivalent to `dict[Any, Any]`. This sacrifices the type safety that Pydantic provides. Consider `dict[str, Any]` at minimum.

---

### `remora/client.py`

**Rating: 9/10**

Minimal and correct. One minor note: the function has a docstring in a file where nothing else does. Consistent docstring coverage would be better than selective coverage.

---

## Cross-Cutting Concerns

### Security

1. **No input sanitization on Jinja2 templates**: `node_context` in subagent YAML is rendered with `jinja2.Template(self.node_context).render(node_text=node.text, ...)`. If `node.text` contains `{{ }}` Jinja2 expressions (which it would for Python f-strings), these could be interpreted as Jinja2 template syntax. Use `jinja2.Environment(autoescape=False, undefined=jinja2.Undefined)` and pass `node_text` as data, not as part of the template string — but the current approach already does this correctly (node_text is a render variable, not injected into the template string). This is fine as-is.

2. **Tool .pym scripts are executed with Cairn**: The security posture of Cairn workspaces should be documented. If Cairn provides full filesystem access, malicious subagent YAML files could cause arbitrary code execution. The `agents_dir` should be treated as a trust boundary.

3. **API key stored in config**: `api_key` defaults to `"EMPTY"` and is stored in `remora.yaml`. If users set a real API key, it could end up in version control. Consider supporting environment variable-only secret injection.

### Testing

The test suite is thorough for the implemented modules. Key strengths:
- `FakeCairnClient` and `FakeAsyncOpenAI` provide clean, deterministic test doubles
- Tool call parsing, turn limits, context provider injection, and error codes are all tested
- The integration test suite is properly gated behind a `@pytest.mark.integration` marker

Gaps:
- `orchestrator.py` tests likely mock the HTTP client but do not cover the watch-task lifecycle bug
- `cli.py` has no tests (the `analyze` command is a stub, but `config` command is testable)
- Discovery edge cases (files with syntax errors, empty files, encoding issues) are not covered

### Type Safety

The codebase uses `from __future__ import annotations` throughout and mypy strict mode. The use of `cast()` in `runner.py` is necessary due to OpenAI SDK type limitations and is acceptable. The `Any` in `_dispatch_tool` for the `tool_call` dict is unavoidable given JSON parsing.

---

## Summary of Issues by Severity

| Severity | Issue | File | Line |
|---|---|---|---|
| High | Multi-tool response calls model once per tool instead of once per turn | `runner.py` | 107–119 |
| High | `_build_submit_result` can raise uncaught `ValidationError` for invalid status | `runner.py` | 265–287 |
| Medium | `AGENT_003` reused for two distinct failure modes | `runner.py` | 100–126 |
| Medium | `watch_task` and emitter opened/closed per `process_node` call | `orchestrator.py` | 42–43 |
| Medium | `tools_by_name` recomputed on every access in the hot path | `subagent.py` | 89–90 |
| Medium | `socket.getaddrinfo` blocks synchronously during config load | `config.py` | 177–187 |
| Medium | Duplicate tool names silently overwritten in `tools_by_name` | `subagent.py` | 89–90 |
| Medium | Jinja2 template syntax not validated at load time | `subagent.py` | 56–63 |
| Low | `agent_id` in events doesn't match `workspace_id` in code | `runner.py` | 133 |
| Low | `CSTNode` name misleading — uses `ast` not CST | `discovery.py` | 22 |
| Low | `JsonlEventEmitter.emit` mutates caller's dict | `events.py` | 54 |
| Low | `return_exceptions=True` dead code in gather loop | `orchestrator.py` | 99–103 |
| Low | `max_tokens` / `temperature` hardcoded, not configurable | `runner.py` | 147–148 |
| Low | `OperationConfig` `extra="allow"` undocumented | `config.py` | 55 |
| Low | Error codes skip CONFIG_001, CONFIG_002 | `errors.py` | all |
| Low | `AgentResult.details` untyped (`dict` vs `dict[str, Any]`) | `results.py` | 18 |
| Info | `analyze`, `watch`, `list-agents` CLI commands are stubs | `cli.py` | 69–135 |
| Info | Query `.scm` files are validated but never used for actual querying | `discovery.py` | 57–66 |

---

## Recommendations

1. **Fix the multi-tool-call loop bug** — this is a correctness issue that will cause spurious model calls and incorrect turn counting.

2. **Add a distinct error code for "no tool call in response"** vs. "turn limit exceeded" — both are `AGENT_003` currently.

3. **Cache `tools_by_name`** using `@cached_property` and add duplicate tool name validation in `load_subagent_definition`.

4. **Validate Jinja2 template syntax** in `load_subagent_definition` to give early, clear error messages.

5. **Move the watch task and emitter lifecycle to `Coordinator.__init__`/`close()`** rather than per-`process_node` calls.

6. **Run DNS check in a thread with timeout** or make it opt-in to avoid blocking config load.

7. **Make `max_tokens` and `temperature` configurable** per operation in `OperationConfig`.

8. **Standardize `agent_id` vs `workspace_id`** naming across events and code.
