# GRAIL Script Refactor Guide

This guide turns the rules in `docs/HOW_TO_CREATE_A_GRAIL_PYM_SCRIPT.md` into a concrete, repeatable refactor process. Follow it to fix every `.pym` script in the remora library.

## Goals

- Make every `.pym` file valid Monty-compatible Python.
- Ensure each script passes `grail check --strict`.
- Standardize script structure, inputs, externals, and return behavior.
- Eliminate unsupported Python features and forbidden imports.

## Prerequisites

- `grail` CLI installed and available in your PATH.
- Basic familiarity with async/await and Python typing.
- Working knowledge of the remora repository layout.

## Step 1: Inventory all `.pym` files

From the repo root, list every `.pym` file so you can track progress.

```bash
rg --files -g "*.pym"
```

Create a checklist of files and mark each one off as you refactor it.

## Step 2: Run baseline validation

Run `grail check` to surface all errors up front.

```bash
grail check
```

If you prefer a clean, strict baseline, run:

```bash
grail check --strict
```

Capture the errors and warnings for each file before editing. This is your baseline for verifying fixes.

## Step 3: Refactor each `.pym` file in a consistent order

Use the same sequence for every script. This prevents missed issues.

### 3.1 Confirm file structure

Each file must have:

1. Imports (only from `grail` and `typing`).
2. A declarations section for `Input()` and `@external` functions.
3. Executable code at the top level.
4. A final expression that acts as the return value.

If any part is missing, add or reorder it before addressing other issues.

### 3.2 Fix imports

Rules:

- Allowed: `from grail import external, Input` and `from typing import Any`.
- Forbidden: any other module, including standard library modules (`os`, `json`, `re`, etc.).

If a forbidden import is present:

- Remove it.
- Replace the functionality with an external function (for parsing, filesystem access, etc.).

### 3.3 Fix inputs (`Input()`)

Rules:

- Every `Input()` must have a type annotation on the left-hand side.
- Use defaults for optional inputs.
- Standard input: `task_description: str = Input("task_description")`.

Common fixes:

- Add missing annotations: `value: str = Input("value")`.
- Add defaults for optional inputs.
- Remove unused inputs (or wire them into the logic).

### 3.4 Fix external functions (`@external`)

Rules:

- Every parameter and return type must be annotated.
- Body must be exactly `...` (Ellipsis literal).
- Only declare externals that the script actually calls.

Common fixes:

- Add missing annotations to parameters or return type.
- Replace `pass` or a stub body with `...`.
- Remove unused externals to avoid `W002` warnings.

### 3.5 Replace unsupported Python features

Monty forbids several Python features. Remove or rewrite them.

| Forbidden Feature | Fix Strategy |
| --- | --- |
| `class` | Replace with `dict` or helper functions |
| `yield` / generators | Build lists explicitly |
| `with` statements | Use external functions for file access |
| `match` | Use `if/elif/else` chains |
| `lambda` | Replace with named `def` |
| standard library imports | Use externals instead |

If the script needs JSON parsing, regex, or filesystem access, define an external function and call it instead of using the standard library.

### 3.6 Verify executable section

- All work must be performed at top level, not inside `main()`.
- Use `await` for external calls.
- Keep helper functions defined above the executable section.
- Ensure errors are handled with `try/except` when needed.

### 3.7 Ensure `submit_result()` is called

Every agent script should call `submit_result()` before the final return expression.

Checklist:

- `submit_result()` is declared with `@external`.
- It is called once, after the main work completes.
- The `summary` describes the work done.
- `changed_files` includes only the files written by the script.

### 3.8 Verify the final return value

The final expression in the file is the return value. It should be a dict summarizing results.

Examples:

```python
{"status": "ok", "files_changed": len(changed_files)}
```

Avoid leaving a bare list or dict without meaning; `grail check` warns about that.

## Step 4: Run `grail check` per file

After refactoring a file, run:

```bash
grail check path/to/script.pym
```

If there are warnings, resolve them until the file passes `--strict`:

```bash
grail check --strict path/to/script.pym
```

## Step 5: Validate generated artifacts (optional but helpful)

After a successful check, inspect `.grail/<script_name>/`:

- `check.json` confirms the file is valid.
- `monty_code.py` shows the executable code without declarations.
- `inputs.json` and `externals.json` verify your declarations.

## Step 6: Repeat for all scripts

Work through your checklist until every `.pym` file passes `grail check --strict`.

## Quick Fix Checklist

Use this list when scanning a `.pym` file:

- Only `grail` and `typing` imports
- Inputs have type annotations
- Externals have full annotations and `...` body
- No classes, generators, `with`, `match`, `lambda`, or stdlib imports
- Declarations appear before executable code
- `submit_result()` is called before the final expression
- Final expression returns a meaningful dict
- `grail check --strict` passes

## Suggested Progress Tracking

Create a simple tracking table in your notes:

```
| File | Status | Notes |
| --- | --- | --- |
| agents/foo.pym | ✅ | clean |
| agents/bar.pym | 🛠️ | removed os import |
```

## When to Ask for Help

Escalate if:

- You need a new external function that doesn’t exist yet.
- The script relies on complex standard library behavior (regex, JSON, filesystem walking) and you’re unsure how to replace it with externals.
- The script exceeds 200 lines and needs a redesign.

## Summary

Follow the steps in order for each file, and verify with `grail check --strict`. Once all `.pym` files pass, the remora library will be compliant with the Grail/Monty execution model and safe to run in Cairn.
