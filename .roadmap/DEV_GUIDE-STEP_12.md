# DEV GUIDE STEP 12: Training Data Generation

## Goal
Build scripts that generate synthetic multi-turn training examples for each domain. These JSONL datasets are the input to the fine-tuning pipeline in Step 13.

## Why This Matters
The quality of the fine-tuned FunctionGemma model is directly determined by the quality of training data. The training examples must exactly mirror the conversation format the runner will use at inference time: same tool schemas, same system prompt structure, same context injection pattern. Training data that deviates from this format produces a model that misbehaves at runtime.

## Implementation Checklist
- Implement `training/shared/conversation_schema.py` with Pydantic models for the training conversation format.
- Implement `training/shared/tool_schema_loader.py` — loads tool schemas from a `SubagentDefinition` in a format suitable for injecting into training examples.
- For each domain (`lint`, `test`, `docstring`, `sample_data`), implement `training/{domain}/generate_examples.py`:
  - Loads Python fixtures from `training/{domain}/fixtures/` as source nodes
  - Generates synthetic multi-turn conversations from a curated set of example trajectories
  - Outputs JSONL to `training/{domain}/examples/train.jsonl` and `examples/eval.jsonl`
- Accept CLI flags: `--count N` (number of examples), `--split 0.9` (train/eval split), `--seed` (for reproducibility).

## Suggested File Targets
- `training/shared/conversation_schema.py`
- `training/shared/tool_schema_loader.py`
- `training/lint/generate_examples.py`
- `training/lint/fixtures/` (small Python files with known lint issues)
- `training/test/generate_examples.py`
- `training/test/fixtures/`
- `training/docstring/generate_examples.py`
- `training/docstring/fixtures/`
- `training/sample_data/generate_examples.py`
- `training/sample_data/fixtures/`

## Training Conversation Format

Each example is a JSON object with a `messages` array. The conversation must follow the exact format that `FunctionGemmaRunner` produces at runtime:

```python
class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

class ToolCall(BaseModel):
    id: str
    type: str = "function"
    function: ToolCallFunction

class ToolCallFunction(BaseModel):
    name: str
    arguments: str  # JSON string

class TrainingExample(BaseModel):
    messages: list[Message]
```

## Generating Examples

Each training example is a **fixed trajectory**: a pre-written sequence of model decisions (tool calls) and tool results, rooted in a real Python fixture file. You are scripting what a correct agent would do, not using a model to generate examples.

Structure for each example:
1. System message: subagent system prompt (from YAML)
2. User message: rendered node context (from fixture Python file)
3. Alternating assistant tool_calls / tool messages
4. Terminal assistant message with `submit_result` tool call

**Lint example trajectory:**
```
user:  [code with E225 and F401 issues]
model: run_linter(check_only=true)
tool:  {"issues": [{"code": "E225", "line": 3}, {"code": "F401", "line": 1}], "fixable_count": 2}
model: apply_fix(issue_code="F401", line_number=1)
tool:  {"success": true}
model: apply_fix(issue_code="E225", line_number=3)
tool:  {"success": true}
model: submit_result(summary="Fixed 2 issues", issues_fixed=2, issues_remaining=0, changed_files=["src/utils.py"])
```

## Example Count Guidelines

| Domain | Min examples | Notes |
|---|---|---|
| lint | 200 | Many distinct issue patterns (E225, F401, E501, W291, etc.) |
| test | 150 | Varied function signatures and test strategies |
| docstring | 150 | All 3 styles × multiple complexity levels |
| sample_data | 100 | Simpler domain, fewer turn patterns needed |

Include both single-turn examples (one issue, immediate submit) and multi-turn examples (2–5 tool calls before submit).

## Implementation Notes
- Store trajectory templates as data, not code. A `trajectories/` subdirectory per domain with JSON/YAML templates that the generator instantiates against fixture files is more maintainable than hardcoded Python.
- Ensure tool call argument JSON strings in training data match the exact schema in the YAML definition — run them through the Pydantic models to validate before writing.
- The eval split (10–15%) should cover edge cases not seen in training: empty functions, already-correct code, functions with decorators, etc.

## Testing Overview
- **Unit test:** Each generator produces valid JSONL (parseable, correct types).
- **Unit test:** Every conversation ends with a `submit_result` tool call.
- **Unit test:** Tool call arguments in training data validate against the corresponding YAML tool schema.
- **Integration test:** `python training/lint/generate_examples.py --count 10` runs without error and produces 10 examples.
- **Integration test:** Train and eval counts match the `--split` ratio.
