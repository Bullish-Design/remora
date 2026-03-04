# E2E Harness Updates — Consolidated Review

All 12 E2E scenarios were run against a live vLLM server (`Qwen/Qwen3-4B-Instruct-2507-FP8` at `http://remora-server:8000/v1`) on 2026-03-03. This document consolidates findings into actionable changes.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary) — Overall health, classification breakdown, key metrics
2. [Priority Matrix](#2-priority-matrix) — What to fix first and why
3. [Cross-Scenario Issues](#3-cross-scenario-issues) — Systemic problems affecting multiple scenarios
   - 3.1 "LSP not running" on `<leader>rr`
   - 3.2 Focus management after chat panel opens
   - 3.3 Chat state leaks between runs
   - 3.4 Agent discovery timing
   - 3.5 No LLM response verification in any scenario
   - 3.6 Scenarios with zero assertions
4. [Harness Changes (`e2e/harness.py`)](#4-harness-changes) — Infrastructure-level fixes
   - 4.1 Add `wait_for_absent` method to TmuxDriver
   - 4.2 Add chat state clearing to DemoProjectGuard
   - 4.3 Add scenario isolation hooks
5. [Keys API Changes (`e2e/keys.py`)](#5-keys-api-changes) — New helpers and fixes
   - 5.1 Add `wait_for_lsp_ready()` method
   - 5.2 Add `wait_for_chat_prompt()` method
   - 5.3 Fix `focus_window()` reliability
   - 5.4 Add `assert_in_buffer()` helper
   - 5.5 Add `open_nvim_with_panel()` convenience method
6. [Per-Scenario Fixes](#6-per-scenario-fixes) — Specific changes for each of the 12 scenarios
7. [Backend Bugs Discovered](#7-backend-bugs-discovered) — Issues in Remora core, not test infrastructure

---

## 1. Executive Summary

**Overall health: Poor.** Only 3 of 12 scenarios are genuine passes. The test suite provides a false sense of confidence — every scenario reports PASS, but most pass for the wrong reasons.

### Classification Breakdown

| Classification | Count | Scenarios |
|---------------|-------|-----------|
| **Genuine pass** | 3 | startup, panel_nav, ext_edit_cascade* |
| **Genuine (weak)** | 2 | cascade, ext_discovery |
| **False positive** | 4 | chat, rewrite, proposal, reject |
| **Partial false positive** | 1 | multi_file |
| **No assertions** | 2 | golden_path, ext_multi_file |

*ext_edit_cascade works correctly but has zero assertions, so it's genuine in behavior but can never fail.

### Key Metrics

- **Scenarios that verify LLM actually responded**: 0/12
- **Scenarios with meaningful assertions**: 4/12 (startup, panel_nav, reject, ext_discovery)
- **Scenarios blocked by "LSP not running"**: 3/12 (rewrite, proposal, reject)
- **Scenarios with focus management bugs**: 2/12 (golden_path, multi_file)
- **Scenarios with zero assertions**: 3/12 (golden_path, ext_multi_file, ext_edit_cascade)

---

## 2. Priority Matrix

Fixes are ordered by impact — what unblocks the most scenarios and improves reliability the most.

### P0 — Blocking (fix these first)

| Fix | Impact | Effort | Affected Scenarios |
|-----|--------|--------|--------------------|
| `wait_for_lsp_ready()` in keys.py | Unblocks 3 scenarios | Low | rewrite, proposal, reject |
| Add real assertions to all scenarios | Eliminates all false positives | Medium | 9/12 scenarios |

### P1 — High (fix after P0)

| Fix | Impact | Effort | Affected Scenarios |
|-----|--------|--------|--------------------|
| Fix focus management after chat | Unblocks golden_path, multi_file | Medium | golden_path, multi_file |
| Chat state isolation | Test independence | Low | panel_nav, golden_path, ext_edit_cascade |
| `wait_for_chat_prompt()` in keys.py | Prevents typing into wrong buffer | Low | chat, multi_file, golden_path |

### P2 — Medium (nice to have)

| Fix | Impact | Effort | Affected Scenarios |
|-----|--------|--------|--------------------|
| Agent discovery wait/retry | Handles slow LSP startup | Medium | ext_multi_file |
| LLM response verification pattern | Proves the full loop works | High | chat, multi_file, golden_path |
| `wait_for_absent` in harness | Cleaner assertions | Low | General utility |

### P3 — Low (defer)

| Fix | Impact | Effort | Affected Scenarios |
|-----|--------|--------|--------------------|
| Stronger assertions for panel_nav | Polish | Low | panel_nav |
| Extension-specific verification | Validates naming | Medium | ext_discovery, ext_multi_file |

---

## 3. Cross-Scenario Issues

### 3.1 "LSP not running" on `<leader>rr`

**Affected**: rewrite (#3), proposal (#4), reject (#6)

**Symptom**: After opening nv2, `<leader>rr` produces notification `[Remora] LSP not running — is this a supported filetype?`. The rewrite never executes.

**Root cause**: The `open_nvim()` flow waits for file content (`wait_for_text("def load_config")`) then sleeps `LSP_STARTUP_DELAY` (3.0s). But the `[Remora]` notification appears at ~2.1s and the rewrite command fires at ~5.6-6.4s. The rewrite command has a stricter LSP readiness check than panel/chat commands — it apparently checks whether the Remora LSP client is fully attached, not just initialized.

**Evidence**:
- startup (#1): `[Remora]` at 2.1s — LSP initializes
- chat (#2): `<leader>rc` works at ~6s — chat doesn't check LSP attachment
- panel_nav (#8): `<leader>ra` works — panel doesn't check LSP attachment
- rewrite (#3): `<leader>rr` fails at ~6.4s — rewrite DOES check LSP attachment
- cascade (#5): manual edit works, panel shows agent — no `<leader>rr` used

**Conclusion**: The LSP initializes (notification appears) but the rewrite handler has an additional readiness gate that isn't met within the 3.0s `LSP_STARTUP_DELAY`. The fix is two-fold:
1. Add `wait_for_lsp_ready()` to keys.py that waits for a positive signal
2. Investigate the nv2 plugin to understand why rewrite has a different readiness check than chat/panel

**Fix in keys.py** (see Section 5.1).

---

### 3.2 Focus Management After Chat Panel Opens

**Affected**: golden_path (#9), multi_file (#7)

**Symptom**: After `<leader>rc` opens the chat input panel, `focus_window("h")` doesn't return focus to the code buffer. Subsequent keystrokes go to `remora://input` (the chat buffer).

**Evidence**:
- golden_path: `goto_line(12)` sends `:12` into chat input (visible as `h:12` message). `:w` fails with `E382: Cannot write, 'buftype' option is set`.
- multi_file: When `<leader>rc` fails (LSP not running), text gets typed into the source buffer instead.

**Root cause**: The Remora chat panel creates a split with a special buffer type (`remora://input`). Standard `C-w h` window navigation may not move to the expected window because:
1. The panel split order depends on which side the panel opens
2. The `remora://input` buffer traps focus differently than regular buffers
3. `focus_window("h")` sends `C-w h` which uses relative direction — if the layout isn't left-right, it goes to the wrong window

**Fix**: See Section 5.3 for `focus_window()` reliability improvements.

---

### 3.3 Chat State Leaks Between Runs

**Affected**: panel_nav (#8), golden_path (#9), ext_edit_cascade (#12)

**Symptom**: Chat messages from previous scenario runs appear in the panel. For example, panel_nav shows "what does this function do?" (22:18:16) and "what do you do?" (12:17:22) from earlier runs.

**Impact**: This doesn't cause failures currently, but it:
- Makes debugging harder (can't tell which messages came from the current run)
- Could interfere with text-matching assertions if they match old messages
- Violates test isolation

**Root cause**: The Remora LSP stores chat history in the EventStore database. `DemoProjectGuard` only restores mutable source files, not the database.

**Fix**: See Section 4.2 for adding chat/event state clearing.

---

### 3.4 Agent Discovery Timing

**Affected**: ext_multi_file (#11)

**Symptom**: On first file open, agents may not be discovered for several seconds. Panel shows "No agent at cursor" with "Tools (0)" for schema.py and loader.py, but agents appear correctly by the third file (merge.py, ~50s into the run).

**Root cause**: The Remora LSP performs agent discovery asynchronously after file open. For the first file, the full discovery pipeline (parse → analyze → create agents) takes time. By the third file, the system is warmed up.

**Fix**: Scenarios that depend on agent presence should use `wait_for_text("? <agent_name>", timeout=15)` after `goto_line()` instead of assuming instant availability. See Section 5.1 for the `wait_for_lsp_ready()` helper which covers this case.

---

### 3.5 No LLM Response Verification

**Affected**: chat (#2), multi_file (#7), golden_path (#9)

**Symptom**: No scenario verifies that the LLM actually responded to a prompt. All chat-related assertions match pre-existing file content or agent metadata.

**Evidence**:
- chat: `wait_for_text("load_config")` matches the function name in the file and panel header
- multi_file: `"deep_merge" in content` matches the function name in the file
- golden_path: zero assertions

**Fix**: This is hard to solve with simple text matching because:
- The LLM response content is unpredictable
- File content and agent metadata already contain the terms we'd search for
- Response timing varies by server load

**Recommended approach**: Wait for a chat response indicator rather than response content. Options:
1. Wait for a second timestamp in the chat panel (indicates a response was posted)
2. Wait for a text pattern like `Agent:` or a response separator
3. Count the number of chat messages before and after sending

This is a P2 fix because it requires understanding the chat panel's response format.

---

### 3.6 Scenarios With Zero Assertions

**Affected**: golden_path (#9), ext_multi_file (#11), ext_edit_cascade (#12), rewrite (#3)

These scenarios capture pane content into `_content` (underscore-prefixed = deliberately unused) and never assert. They literally cannot fail unless they throw an exception.

**Fix**: Every scenario must have at least one `assert` statement that verifies the core behavior it claims to test. See Section 6 for per-scenario assertion recommendations.

---

## 4. Harness Changes (`e2e/harness.py`)

### 4.1 Add `wait_for_absent` Method to TmuxDriver

**Location**: `e2e/harness.py`, TmuxDriver class (after `wait_for_stable` at line 237)

**Purpose**: Wait until a pattern is NOT present in the pane. Useful for verifying that an error message has cleared or that a previous state has been replaced.

```python
def wait_for_absent(
    self,
    pattern: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    poll: float = POLL_INTERVAL,
    regex: bool = False,
) -> str:
    """Poll capture_pane until pattern is absent or timeout.

    Returns the pane content where pattern was not found.
    Raises TimeoutError if pattern still present after timeout.
    """
    deadline = time.monotonic() + timeout
    compiled = re.compile(pattern) if regex else None

    while time.monotonic() < deadline:
        content = self.capture_pane()
        if regex:
            assert compiled is not None
            if not compiled.search(content):
                return content
        else:
            if pattern not in content:
                return content
        time.sleep(poll)

    content = self.capture_pane()
    raise TimeoutError(
        f"Timed out after {timeout}s waiting for "
        f"{'regex ' if regex else ''}pattern to disappear: {pattern!r}\n"
        f"Last pane content:\n{content}"
    )
```

---

### 4.2 Add Chat State Clearing to DemoProjectGuard

**Location**: `e2e/harness.py`, DemoProjectGuard class

**Purpose**: Clear Remora's event/chat database between scenario runs to ensure test isolation.

The Remora LSP stores state in a SQLite database or similar. The guard should either:
1. Delete the database file before/after each run
2. Or add the database file to `_DEMO_MUTABLE_FILES` so it gets snapshot/restored

**Investigation needed**: Find where Remora stores its EventStore data for the demo project. It's likely in one of:
- `remora_demo/project/.remora/` directory
- `~/.local/share/remora/` or similar XDG path
- An in-memory store that persists via the LSP server process (would need server restart)

```python
# Add to _DEMO_MUTABLE_FILES or handle separately:
_DEMO_STATE_PATHS = [
    DEMO_PROJECT / ".remora",  # Likely location — needs verification
]
```

**Alternative**: Add a `clear_state()` method to DemoProjectGuard that removes Remora state directories and is called in `restore()`.

---

### 4.3 Add Scenario Isolation Hooks

**Location**: `e2e/harness.py`, `run_scenario()` function (line 443)

**Purpose**: Provide pre/post hooks for scenario isolation beyond file restoration.

Currently `run_scenario()` does: save files → start tmux → run scenario → stop recorder → restore files → kill tmux.

Add optional hooks:

```python
def run_scenario(
    scenario: Scenario,
    *,
    record: bool = True,
    gif: bool = False,
    working_dir: str | Path | None = None,
    pre_hooks: list[Callable[[], None]] | None = None,
    post_hooks: list[Callable[[], None]] | None = None,
) -> ScenarioResult:
```

This enables scenarios to register cleanup like "kill any lingering Remora LSP processes" or "clear chat state" without modifying the harness core.

---

## 5. Keys API Changes (`e2e/keys.py`)

### 5.1 Add `wait_for_lsp_ready()` Method

**Location**: `e2e/keys.py`, NvimKeys class (after `open_nvim` at line 253)

**Purpose**: Wait for the Remora LSP to be fully ready before issuing commands that require it (rewrite, accept, reject).

**Current problem**: `open_nvim()` uses a fixed `time.sleep(LSP_STARTUP_DELAY)` which is both too slow (wastes 3s on startup) and insufficient (rewrite still fails after 3s).

```python
def wait_for_lsp_ready(
    self,
    *,
    indicator: str = "[Remora]",
    timeout: float = 15.0,
    extra_settle: float = 2.0,
) -> str:
    """Wait for the Remora LSP to show its initialization notification.

    After the indicator appears, waits an additional settle period for
    the LSP to fully attach to all buffers.

    Args:
        indicator: Text that confirms LSP initialization.
        timeout: Max seconds to wait for the indicator.
        extra_settle: Additional seconds after indicator appears.

    Returns:
        The pane content where the indicator was found.
    """
    content = self.driver.wait_for_text(indicator, timeout=timeout)
    if extra_settle > 0:
        time.sleep(extra_settle)
    return content
```

**Usage in scenarios**:
```python
nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
nv.wait_for_lsp_ready()  # Event-driven, not fixed sleep
nv.leader_rewrite()
```

**Note**: The `extra_settle` of 2.0s accounts for the gap between the `[Remora]` notification and full LSP attachment. This should be tuned based on testing. Ultimately, the nv2 plugin should expose a more reliable readiness signal (e.g., `[Remora] LSP ready` as a distinct message from `[Remora] nv2 initialized`).

---

### 5.2 Add `wait_for_chat_prompt()` Method

**Location**: `e2e/keys.py`, NvimKeys class

**Purpose**: After sending `<leader>rc`, wait for the chat input prompt to appear before typing the message. Prevents typing into the wrong buffer.

```python
def wait_for_chat_prompt(
    self,
    *,
    prompt_text: str = "Message to agent:",
    timeout: float = 10.0,
) -> str:
    """Wait for the chat input prompt to appear after leader_chat().

    Returns the pane content where the prompt was found.
    Raises TimeoutError if the prompt doesn't appear (e.g., LSP not running).
    """
    return self.driver.wait_for_text(prompt_text, timeout=timeout)
```

**Usage in scenarios**:
```python
nv.leader_chat()
nv.wait_for_chat_prompt()  # Confirms chat panel opened
nv.keys("what do you do?", delay=1)
```

This prevents the multi_file scenario 7 bug where chat text gets typed into the source buffer because `<leader>rc` failed silently.

---

### 5.3 Fix `focus_window()` Reliability

**Location**: `e2e/keys.py`, NvimKeys class, `focus_window()` at line 160

**Problem**: `focus_window("h")` sends `C-w h` but this doesn't reliably return to the code buffer after a chat panel opens because the window layout may not be a simple left-right split.

**Options**:

1. **Use window number targeting** (preferred): Send `C-w 1` or `:1wincmd w` to target the first (code) window explicitly.

2. **Use `:wincmd` ex command**: Send `:wincmd h<CR>` which is more reliable than `C-w h` through tmux.

3. **Add a `focus_code_buffer()` method** that navigates to the code window regardless of layout:

```python
def focus_code_buffer(self, expected_text: str = "def ", timeout: float = 5.0) -> str:
    """Navigate to the window containing source code.

    Tries C-w h first. If the expected text isn't in the pane, tries
    other windows until the code buffer is found.

    Args:
        expected_text: Text that identifies the code buffer.
        timeout: Max seconds to find the code buffer.

    Returns:
        The pane content of the code buffer.
    """
    # Try left window first (most common layout)
    self.raw("C-h", delay=0.3)
    content = self.driver.capture_pane()
    if expected_text in content:
        return content

    # Try Ctrl-w p (previous window)
    self.raw("C-w", delay=0.1)
    self.raw("p", delay=0.3)
    content = self.driver.capture_pane()
    if expected_text in content:
        return content

    # Fallback: cycle through windows
    for _ in range(4):
        self.raw("C-w", delay=0.1)
        self.raw("w", delay=0.3)
        content = self.driver.capture_pane()
        if expected_text in content:
            return content

    raise TimeoutError(f"Could not find window containing '{expected_text}'")
```

---

### 5.4 Add `assert_in_buffer()` Helper

**Location**: `e2e/keys.py`, NvimKeys class

**Purpose**: Verify the current buffer contains specific text. Wrapper around `capture_pane` + `assert`.

```python
def assert_in_pane(self, text: str, msg: str = "") -> str:
    """Assert that text is in the current pane content.

    Args:
        text: The text to find.
        msg: Optional failure message.

    Returns:
        The pane content.

    Raises:
        AssertionError if text is not found.
    """
    content = self.driver.capture_pane()
    assert text in content, msg or f"Expected {text!r} in pane, got:\n{content}"
    return content
```

---

### 5.5 Add `open_nvim_with_panel()` Convenience Method

**Location**: `e2e/keys.py`, NvimKeys class

**Purpose**: Many scenarios follow the same pattern: open file → wait for content → open panel → focus right → focus left. This should be a single method.

```python
def open_nvim_with_panel(
    self,
    file: str | Path,
    *,
    wait_for: str = "def ",
    timeout: float = 15.0,
) -> None:
    """Open nv2, wait for content and LSP, then open the agent panel.

    Combines open_nvim + wait_for_lsp_ready + leader_panel + focus cycle.
    """
    self.open_nvim(file, wait_for=wait_for, timeout=timeout, lsp_delay=0)
    self.wait_for_lsp_ready()
    self.leader_panel()
    self.focus_right(delay=0.3)
    self.focus_left(delay=0.3)
```

---

## 6. Per-Scenario Fixes

### 6.1 startup (Scenario 1) — Genuine Pass

**Status**: Working correctly. No changes required.

**Optional improvements**:
- Add a regex assertion for `\[Remora\].*initializ` to confirm the notification text
- Reduce timing if `wait_for_lsp_ready()` makes the fixed delay unnecessary

---

### 6.2 chat (Scenario 2) — False Positive

**File**: `e2e/scenarios/chat.py`

**Problems**:
1. `wait_for_text("load_config")` matches file content, not LLM response
2. 5s hard sleep after Enter (`nv.raw("Enter", delay=5)`) is wasteful and unreliable
3. No verification that chat panel opened before typing

**Required changes**:
```python
def run(self, driver: TmuxDriver) -> None:
    nv = NvimKeys(driver)
    target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"

    nv.open_nvim(target_file, wait_for="def load_config")
    nv.goto_line(13)

    # Open chat and verify prompt appears
    nv.leader_chat()
    nv.wait_for_chat_prompt()  # NEW: confirms chat opened

    # Type and send
    nv.keys("what do you do?", delay=1)
    nv.raw("Escape", delay=0.5)
    nv.raw("Enter", delay=1)

    # Wait for response — look for a response indicator, not file content
    # Option A: Wait for a second timestamp (response posted)
    # Option B: Wait for stable after sending (response rendered)
    driver.wait_for_stable(stable_seconds=3.0, timeout=30)

    # Open panel and verify agent info
    nv.leader_panel()
    nv.focus_right(delay=1)
    content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)

    # Assert panel shows agent info (not just file content)
    assert "load_config" in content  # OK — panel header shows agent name
    assert "function" in content.lower() or "Type:" in content  # NEW: verify panel content
```

---

### 6.3 rewrite (Scenario 3) — False Positive

**File**: `e2e/scenarios/rewrite.py`

**Problems**:
1. LSP not ready when `<leader>rr` fires
2. Only assertion is `wait_for_stable` + unused `_content`
3. No check that rewrite actually produced output

**Required changes**:
```python
def run(self, driver: TmuxDriver) -> None:
    nv = NvimKeys(driver)
    target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"

    nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
    nv.wait_for_lsp_ready()  # NEW: event-driven LSP wait
    nv.goto_line(12)

    # Trigger rewrite
    nv.leader_rewrite()

    # Wait for rewrite response — should show diagnostic or proposal
    content = driver.wait_for_stable(stable_seconds=3.0, timeout=30)

    # Assert rewrite produced something visible
    # (Specific assertion depends on what rewrite looks like in the UI)
    assert "LSP not running" not in content, \
        f"LSP should be ready but got 'not running':\n{content}"
```

---

### 6.4 proposal (Scenario 4) — False Positive

**File**: `e2e/scenarios/proposal.py`

**Problems**: Same as rewrite — LSP not ready, no assertions on acceptance.

**Required changes**: Mirror rewrite fixes plus:
```python
    nv.open_nvim(target_file, wait_for="test_load_yaml", lsp_delay=0)
    nv.wait_for_lsp_ready()  # NEW
    nv.goto_line(13)

    nv.leader_rewrite()
    content = driver.wait_for_stable(stable_seconds=3.0, timeout=30)
    assert "LSP not running" not in content

    # Accept the proposal
    nv.leader_accept()
    content = driver.wait_for_stable(stable_seconds=3.0, timeout=15)

    # Verify file was actually modified
    # (Specific assertion depends on what the LLM proposes)
```

---

### 6.5 cascade (Scenario 5) — Genuine (Weak)

**File**: `e2e/scenarios/cascade.py`

**Problems**:
1. Tests code editing, not cascade propagation
2. No verification that test agent received cascade

**Required changes** (after edit and save):
```python
    # After save, verify the edit persisted
    content = driver.capture_pane()
    assert "timeout: int = 30" in content, \
        f"Expected timeout parameter in pane:\n{content}"

    # Switch to test file to check for cascade activity
    test_file = DEMO_PROJECT / "tests" / "test_loader.py"
    nv.edit_file(test_file)
    driver.wait_for_text("test_load", timeout=10)

    # Open panel on test file to check agent status
    nv.leader_panel()
    nv.focus_right(delay=1)
    content = driver.wait_for_stable(stable_seconds=3.0, timeout=15)
    # At minimum, verify the test agent exists
    # Ideally, check for cascade-related status change
```

---

### 6.6 reject (Scenario 6) — False Positive

**File**: `e2e/scenarios/reject.py`

**Problems**:
1. Same LSP readiness issue as rewrite/proposal
2. Asserts file unchanged, but file was never modified (trivial pass)

**Required changes**:
```python
    nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
    nv.wait_for_lsp_ready()  # NEW
    nv.goto_line(29)

    # Snapshot file content before rewrite
    before = driver.capture_pane()

    nv.leader_rewrite()

    # Verify rewrite actually produced a proposal
    content = driver.wait_for_stable(stable_seconds=3.0, timeout=30)
    assert "LSP not running" not in content
    # TODO: assert proposal indicator is visible

    # Reject
    nv.leader_reject()
    content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)

    # Verify file returned to original state
    assert "def detect_format" in content
    # TODO: Compare content structure with `before` snapshot
```

---

### 6.7 multi_file (Scenario 7) — Partial False Positive

**File**: `e2e/scenarios/multi_file.py`

**Problems**:
1. First chat fails (LSP not running), corrupts source file
2. No chat prompt verification before typing
3. Assertions match file content, not LLM response

**Required changes**:
```python
    # First file
    nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
    nv.wait_for_lsp_ready()  # NEW
    nv.goto_line(12)

    nv.leader_chat()
    nv.wait_for_chat_prompt()  # NEW: prevents typing into source
    nv.keys("what does this function do?", delay=1)
    nv.raw("Escape", delay=0.5)
    nv.raw("Enter", delay=1)

    # Verify chat was sent (wait for stable, then check no file corruption)
    content = driver.wait_for_stable(stable_seconds=3.0, timeout=20)
    assert "def load_config" in content, "Source file should be intact"

    # Switch to second file
    nv.edit_file("src/configlib/merge.py")
    driver.wait_for_text("def deep_merge", timeout=10)
    nv.goto_line(8)

    nv.leader_chat()
    nv.wait_for_chat_prompt()  # NEW
    nv.keys("explain this function", delay=1)
    nv.raw("Escape", delay=0.5)
    nv.raw("Enter", delay=1)

    content = driver.wait_for_stable(stable_seconds=3.0, timeout=20)
    assert "deep_merge" in content or "merge" in content
```

---

### 6.8 panel_nav (Scenario 8) — Genuine Pass

**File**: `e2e/scenarios/panel_nav.py`

**Status**: Best-functioning scenario. Works correctly.

**Optional improvements**:
- Strengthen assertions to check panel-specific content: `"? load_config"` or `"Type: function"`
- Verify tools toggle actually works (check for `"▼ Tools"` after toggle)

---

### 6.9 golden_path (Scenario 9) — False Positive (No Assertions)

**File**: `e2e/scenarios/golden_path.py`

**Problems** (multiple compounding failures):
1. Focus stays in chat buffer after `<leader>rc` — all subsequent edits go to wrong buffer
2. `:w` fails with E382 on `remora://input` buffer
3. No cascade because file never modified
4. No proposal to accept
5. Zero assertions — `_content` deliberately unused
6. `to_llm_tool` backend error in chat

**Required changes** (this is the most broken scenario — needs substantial rework):
```python
    # Beat 4: Chat
    nv.goto_line(13, delay=1)
    nv.leader_chat(settle=0.2)
    nv.wait_for_chat_prompt()  # NEW: verify chat opened
    nv.keys("what do you do?", delay=2)
    nv.raw("Escape", delay=0.5)
    nv.raw("Enter", delay=2)

    # Beat 5: Return to code — use reliable focus method
    nv.focus_code_buffer(expected_text="def load_config")  # NEW: replaces focus_window("h")

    # Verify we're in the code buffer
    content = driver.capture_pane()
    assert "def load_config" in content, "Should be in code buffer"

    nv.goto_line(12)
    nv.find_char(")")
    nv.enter_insert()
    nv.type_in_insert(", timeout: int = 30", enter=False, delay=0.3)
    nv.exit_insert()
    nv.save(delay=2)

    # Verify the edit persisted
    content = driver.capture_pane()
    assert "timeout" in content, f"Edit should be visible:\n{content}"

    # Beat 6-8: Cascade and accept (same as before but with assertions)
    time.sleep(8)
    nv.edit_file(test_file)
    nv.goto_line(13, delay=1)
    nv.leader_accept()
    content = driver.wait_for_stable(stable_seconds=3.0, timeout=15)
    # Assert something changed in the test file
```

---

### 6.10 ext_discovery (Scenario 10) — Genuine (Weak)

**File**: `e2e/scenarios/ext_discovery.py`

**Problems**:
1. Assertions check file content visibility, not extension discovery
2. Doesn't navigate to specific functions to verify agent types

**Required changes**:
```python
    # After opening schema.py, navigate to specific nodes
    nv.goto_line(8)  # SchemaError class
    content = driver.wait_for_text("? SchemaError", timeout=15)  # NEW
    assert "class" in content.lower() or "Type:" in content  # Verify class agent

    nv.goto_line(16)  # validate function
    content = driver.wait_for_text("? validate", timeout=10)  # NEW
    assert "function" in content.lower() or "Type:" in content  # Verify function agent
```

---

### 6.11 ext_multi_file (Scenario 11) — No Assertions

**File**: `e2e/scenarios/ext_multi_file.py`

**Problems**:
1. "No agent at cursor" for first two files (discovery timing)
2. Zero assertions

**Required changes**:
```python
    # Wait for agent discovery after each goto_line
    nv.goto_line(8)
    try:
        content = driver.wait_for_text("? SchemaError", timeout=15)
    except TimeoutError:
        # Agent discovery may be slow — continue but note it
        content = driver.capture_pane()

    # ... navigate through files ...

    # On merge.py (agents should be ready by now)
    nv.goto_line(8)
    content = driver.wait_for_text("? deep_merge", timeout=15)
    assert "deep_merge" in content, "Agent should be discovered by third file"

    nv.goto_line(19)
    content = driver.wait_for_text("? merge_dicts", timeout=10)
    assert "merge_dicts" in content
```

---

### 6.12 ext_edit_cascade (Scenario 12) — Genuine (No Assertions)

**File**: `e2e/scenarios/ext_edit_cascade.py`

**Problems**:
1. Both edits work correctly but there are zero assertions
2. Chat history leaks from previous runs

**Required changes**:
```python
    # After schema.py edit + save
    content = driver.capture_pane()
    assert 'self.severity = "error"' in content or "severity" in content, \
        "Edit should be visible in schema.py"

    # After loader.py edit + save
    content = driver.capture_pane()
    assert "timeout: int = 30" in content, \
        "Edit should be visible in loader.py"

    # Verify panel shows correct agent
    assert "load_config" in content or "? load_config" in content
```

---

## 7. Backend Bugs Discovered

These are not test infrastructure issues — they're bugs in the Remora core that were exposed by live testing.

### 7.1 `to_llm_tool` Serialization Error

**Seen in**: golden_path (#9)

**Error**: `Error: 'dict' object has no attribute 'to_llm_tool'`

**Cause**: The Remora backend returns tool configurations as plain `dict` objects, but the chat handler expects them to have a `to_llm_tool()` method. This is a serialization/deserialization mismatch — tools are likely being stored/loaded as dicts somewhere in the pipeline instead of being wrapped in their proper model class.

**Impact**: Chat messages that reference tools will fail. This may affect all chat scenarios, but is only visible in golden_path because that's the only scenario where the chat error text is captured.

**Fix**: Find where tool configs are stored/loaded and ensure they're deserialized into the proper model class (not left as raw dicts). This is a separate project from the E2E harness review.

### 7.2 Formatter Warning on Save

**Seen in**: ext_edit_cascade (#12)

**Warning**: `Formatter failed. See :ConformInfo for details`

**Cause**: The nv2 config has `conform.nvim` or similar auto-formatter configured, but the demo project doesn't have ruff/black configured. The formatter runs on save but can't find its config.

**Impact**: Non-blocking (file saves successfully). But in CI, this could add unexpected noise or timing variance.

**Fix**: Either configure a formatter for the demo project or disable auto-format in the nv2 test config.

### 7.3 Rewrite LSP Readiness Check

**Seen in**: rewrite (#3), proposal (#4), reject (#6)

**Issue**: The `<leader>rr` command has a stricter LSP readiness check than `<leader>ra` (panel) and `<leader>rc` (chat). The notification `[Remora] LSP not running — is this a supported filetype?` appears even though the LSP has initialized.

**This may be a bug in the nv2 plugin** rather than the Remora LSP server. The plugin may be checking for an LSP client attachment status that hasn't completed yet, even though the LSP server is running and responding to other commands.

**Fix**: Investigate the nv2 plugin's rewrite handler to understand its readiness check. It may need to use the same readiness gate as chat/panel, or the check may need a longer timeout/retry.

---

*Generated from 12 live scenario reports. Individual reports available in `.scratch/projects/verify-e2e-live/`.*
