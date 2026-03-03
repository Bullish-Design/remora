# Scenario 10: ext_discovery — Test Report

## Summary

| Field | Value |
|-------|-------|
| Scenario | `ext_discovery` |
| Result | **PASS (genuine, weak assertions)** |
| Duration | 49.6s (runner) / 32.4s (recording) |
| Cast file | `ext_discovery_20260303_123138.cast` |
| Frames | 31 |

## What the Scenario Does

1. Opens `schema.py` in nv2, waits for `class SchemaError`
2. Waits for stable, asserts `class SchemaError` and `def validate` visible
3. Scrolls down 10 lines and back to top
4. Opens agent panel (`<leader>ra`), focuses right then left
5. Opens `loader.py` via `:e`, waits for `def load_config`
6. Waits for stable, asserts `def load_config` visible
7. Final stable wait, captures pane (no assertion)

## Timeline

| Frame | Time | Event |
|-------|------|-------|
| 5 | 5.4s | `schema.py` loaded, both `SchemaError` and `validate` visible |
| 6 | 6.7s | Status bar rendered with git info |
| 7-17 | 10.5-23.7s | Scroll down/up, stable wait, notifications clear |
| 18-19 | 24.0-24.2s | Panel opens (`<leader>ra`) |
| 23 | 26.9s | Panel shows `? schema`, Type: file, Lines: 1-24, Tools (3) |
| 24-26 | 29.2-30.8s | Focus right (panel active) then left |
| 28-30 | 31.9-32.4s | `:e loader.py` — file loads, panel updates to `? loader` |

## Findings

### Core Functionality Works

- `schema.py` loads correctly with both `SchemaError` class and `validate` function visible
- Agent panel opens and shows the `schema` file-level agent (Type: file, Lines: 1-24, Tools: 3)
- After switching to `loader.py`, panel updates to show `? loader` (file-level agent, Lines: 1-44)
- File navigation between schema.py and loader.py works cleanly

### Panel Shows File-Level Agent Only

At cursor position line 1, the panel shows the file-level agent (`schema` / `loader`) rather than specific function agents. This is expected — the cursor needs to be on a function/class for it to show a more specific agent. The scenario doesn't navigate into specific functions on schema.py to verify `SchemaError` or `validate` agents.

### No Extension-Specific Verification

Despite the scenario being named "ext_discovery", there's no assertion that verifies:
- Custom extensions are discovered
- Extension assignments appear in the panel
- Different node types (class vs function) get different extensions

The description says "verify code lenses appear" and "show all discovered agents with their extension assignments" but neither is actually checked.

### Assertions Are Valid but Minimal

The two assertions (`class SchemaError` and `def validate` in pane, `def load_config` in pane) pass because the file content is displayed. These confirm file loading works but don't verify agent/extension discovery.

## Classification

**Genuine pass (weak assertions)** — File loading, panel opening, and file switching all work correctly. But the scenario doesn't test what its name implies (extension discovery).

## Recommendations

1. Navigate cursor to `SchemaError` class and verify panel shows a class-type agent
2. Navigate to `validate` function and verify panel shows a function-type agent
3. If extensions are assigned, assert their names appear in the panel
4. The scenario could be a simpler version of `panel_nav` for `schema.py` — consider differentiating it more
