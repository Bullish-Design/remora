# TEST_SUITE_ADDITIONS.md — File Corruption Bug & Proposed Tests

## Table of Contents

1. [File Corruption Bug Description](#1-file-corruption-bug-description)
2. [Root Cause Analysis](#2-root-cause-analysis)
3. [Reproduction Scenarios](#3-reproduction-scenarios)
4. [Proposed Unit Tests](#4-proposed-unit-tests)
5. [Proposed E2E Tests](#5-proposed-e2e-tests)
6. [Proposed Integration Tests](#6-proposed-integration-tests)
7. [Fix Recommendations](#7-fix-recommendations)

---

## 1. File Corruption Bug Description

When a `RewriteProposal` is accepted, the LSP server applies a `WorkspaceEdit`
that replaces a line range (`start_line` to `end_line`) with the proposed
`new_source`. This range is computed at **proposal creation time** based on the
agent's AST position.

**The bug:** If the file is modified between proposal creation and acceptance,
the `start_line`/`end_line` range becomes stale. The `WorkspaceEdit` replaces
the wrong lines, corrupting the file.

### Key code paths

| File | Function | Role |
|------|----------|------|
| `src/remora/lsp/models.py:52` | `RewriteProposal.to_workspace_edit()` | Builds the `WorkspaceEdit` using `start_line`/`end_line` |
| `src/remora/lsp/runner.py:680-694` | `AgentRunner._handle_rewrite_self()` | Creates the proposal with line range from `agent.start_line`/`agent.end_line` |
| `src/remora/lsp/handlers/commands.py:147` | `cmd_accept_proposal()` | Applies the workspace edit |
| `src/remora/lsp/watcher.py:275` | `inject_ids()` | Writes `# rm_XXXXXXXX` comment tags to source files — modifies line content |
| `src/remora/lsp/handlers/documents.py:150` | `did_save` handler | Calls `inject_ids()` on save |

### Corruption vectors

1. **User edits file while proposal pending:** User adds/removes lines above the
   proposed range. Proposal's `start_line`/`end_line` are now wrong.

2. **`inject_ids()` modifies file:** The `did_save` handler calls `inject_ids()`
   which appends `# rm_XXXXXXXX` comments to function definition lines. This
   changes line content (but not line count) — the `old_source` match may fail
   silently or produce a mangled result.

3. **Concurrent proposals on same file:** Two agents propose rewrites to
   adjacent or overlapping functions. Accepting one invalidates the line range
   of the other.

4. **Background scan modifies EventStore nodes:** The `_background_scan()` in
   `__main__.py` re-parses all files and may update agent line ranges in
   EventStore while a proposal built from old ranges is still pending.

---

## 2. Root Cause Analysis

The fundamental problem is that `RewriteProposal` stores an **absolute line
range** captured at creation time and never validates it at application time.

The `to_workspace_edit()` method (models.py:52) trusts `start_line`/`end_line`
unconditionally:

```python
def to_workspace_edit(self) -> lsp.WorkspaceEdit:
    return lsp.WorkspaceEdit(
        changes={
            self.file_path: [
                lsp.TextEdit(
                    range=lsp.Range(
                        start=lsp.Position(line=self.start_line - 1, character=0),
                        end=lsp.Position(line=self.end_line, character=0),
                    ),
                    new_text=self.new_source + "\n",
                )
            ]
        }
    )
```

There is **no validation** that `old_source` still matches the current file
content at the proposed line range before applying the edit.

---

## 3. Reproduction Scenarios

### Scenario A: User adds lines above proposal range

1. Open `src/config_loader.py` in Neovim
2. Position cursor on `load_config` function (line 10-25)
3. Trigger `<Space>rr` (rewrite request) — agent creates proposal with `start_line=10, end_line=25`
4. Before accepting: add 5 blank lines at top of file (line 1)
5. Accept proposal — edit applies to lines 10-25, but the function is now at lines 15-30
6. **Result:** Lines 10-25 (which now contain different code) are replaced

### Scenario B: inject_ids after proposal

1. Agent creates proposal for `load_config` with `old_source` not containing `# rm_XXXXXXXX`
2. User saves file → `did_save` → `inject_ids()` appends ID comments
3. Accept proposal → the old function text no longer matches what's on disk
4. The proposal overwrites the injected-ID version with un-injected source

### Scenario C: Concurrent proposals

1. Agent A proposes rewrite for `load_config` (lines 10-25)
2. Agent B proposes rewrite for `validate` (lines 27-40)
3. Accept Agent A's proposal — it replaces 16 lines with 20 lines (+4)
4. Agent B's range (27-40) is now stale — the function moved to lines 31-44
5. Accept Agent B — corrupts lines 27-40 (wrong content)

---

## 4. Proposed Unit Tests

### 4.1 `test_proposal_stale_range_detection`

**File:** `tests/unit/test_rewrite_proposal.py`

Test that a proposal can detect when its line range is stale by comparing
`old_source` against the current file content.

```python
class TestRewriteProposalStaleness:
    def test_old_source_matches_current(self):
        """Proposal is valid when old_source matches file content at range."""
        proposal = RewriteProposal(
            proposal_id="p1", agent_id="a1", file_path="/tmp/f.py",
            old_source="def foo():\n    pass\n",
            new_source="def foo():\n    return 42\n",
            start_line=1, end_line=2,
        )
        current_content = "def foo():\n    pass\n"
        assert proposal.old_source == current_content  # Valid

    def test_old_source_mismatch_detects_stale(self):
        """Proposal should be invalid when file was edited."""
        proposal = RewriteProposal(
            proposal_id="p1", agent_id="a1", file_path="/tmp/f.py",
            old_source="def foo():\n    pass\n",
            new_source="def foo():\n    return 42\n",
            start_line=1, end_line=2,
        )
        current_content = "# added\ndef foo():\n    pass\n"
        lines = current_content.splitlines(keepends=True)
        actual = "".join(lines[proposal.start_line - 1 : proposal.end_line])
        assert actual != proposal.old_source  # Range is stale

    def test_inject_ids_changes_old_source(self):
        """inject_ids appending comments makes old_source not match."""
        original = "def foo():\n    pass\n"
        after_inject = "def foo():  # rm_abcd1234\n    pass\n"
        assert original != after_inject
```

### 4.2 `test_concurrent_proposal_invalidation`

```python
class TestConcurrentProposals:
    def test_accepting_one_invalidates_overlapping(self):
        """After accepting proposal A, proposal B's range is stale."""
        p_a = RewriteProposal(
            proposal_id="pA", agent_id="a1", file_path="f.py",
            old_source="def foo():\n    pass\n",
            new_source="def foo():\n    return 1\n    return 2\n",  # +1 line
            start_line=1, end_line=2,
        )
        p_b = RewriteProposal(
            proposal_id="pB", agent_id="a2", file_path="f.py",
            old_source="def bar():\n    pass\n",
            new_source="def bar():\n    return 99\n",
            start_line=4, end_line=5,
        )
        # After accepting p_a: file gains 1 line, so p_b's range shifts by +1
        # p_b.start_line should be 5, not 4
        assert p_b.start_line == 4  # Still stale — no auto-adjustment
```

### 4.3 `test_inject_ids_idempotent`

**File:** `tests/unit/test_watcher.py`

```python
class TestInjectIds:
    def test_double_inject_does_not_duplicate(self, tmp_path):
        """Running inject_ids twice shouldn't add duplicate ID comments."""
        f = tmp_path / "test.py"
        f.write_text("def foo():\n    pass\n")
        nodes = [{"node_id": "rm_abcd1234", "start_line": 1}]
        inject_ids(f, nodes)
        content1 = f.read_text()
        inject_ids(f, nodes)
        content2 = f.read_text()
        assert content1 == content2  # Idempotent

    def test_inject_preserves_line_count(self, tmp_path):
        """inject_ids should not change the number of lines."""
        f = tmp_path / "test.py"
        original = "def foo():\n    pass\ndef bar():\n    pass\n"
        f.write_text(original)
        nodes = [
            {"node_id": "rm_aaaa1111", "start_line": 1},
            {"node_id": "rm_bbbb2222", "start_line": 3},
        ]
        inject_ids(f, nodes)
        assert len(f.read_text().splitlines()) == len(original.splitlines())
```

---

## 5. Proposed E2E Tests

### 5.1 `scenario_stale_proposal`

**Purpose:** Verify that accepting a proposal after editing the file doesn't
corrupt it.

**Steps:**

1. Open nv2 on demo project
2. Navigate to `load_config` function
3. Trigger rewrite → wait for proposal (diagnostic appears)
4. Before accepting: add a comment line above the function (`O# stale test<Esc>`)
5. Save file
6. Accept proposal via code action
7. **Assert:** File should either (a) reject the stale proposal with a warning,
   or (b) correctly adjust the range. It should NOT silently apply to wrong lines.

### 5.2 `scenario_inject_ids_proposal_interaction`

**Purpose:** Verify that `inject_ids` doesn't break pending proposals.

**Steps:**

1. Open nv2, trigger rewrite on `load_config`
2. Wait for proposal to appear
3. Save the file (triggers `did_save` → `inject_ids`)
4. Accept proposal
5. **Assert:** The accepted rewrite should have correct content.
   File should not have duplicate or missing ID comments.

### 5.3 `scenario_concurrent_proposals`

**Purpose:** Verify behavior when multiple proposals exist for the same file.

**Steps:**

1. Open nv2, navigate to first function, trigger rewrite
2. Navigate to second function, trigger rewrite
3. Accept first proposal
4. Check if second proposal's diagnostic is still valid
5. Accept second proposal
6. **Assert:** Both functions have correct content. No overlapping edits.

---

## 6. Proposed Integration Tests

### 6.1 `test_proposal_lifecycle_with_file_edits`

**File:** `tests/integration/test_proposal_lifecycle.py`

Test the full proposal lifecycle using the LSP server directly (no Neovim):

```python
@pytest.mark.asyncio
async def test_proposal_applied_to_modified_file():
    """Proposal created, file modified, proposal accepted."""
    # Setup: create EventStore, RemoraDB, mock LLM
    # 1. Parse file, discover agent at lines 10-25
    # 2. Trigger agent → creates proposal with start_line=10, end_line=25
    # 3. Modify the file (insert 3 lines at top)
    # 4. Apply workspace edit from proposal
    # 5. Read file: verify old_source was NOT blindly replaced at wrong lines
```

### 6.2 `test_proposal_cancelled_on_file_change`

```python
@pytest.mark.asyncio
async def test_pending_proposals_invalidated_on_edit():
    """Proposals for a file are invalidated when did_change fires."""
    # 1. Create proposal for agent in file
    # 2. Simulate textDocument/didChange that shifts line ranges
    # 3. Verify proposal is either invalidated or range-adjusted
```

---

## 7. Fix Recommendations

### Short-term: Validate `old_source` before applying

Add a validation step in `cmd_accept_proposal()` (commands.py:147) that reads
the current file content at the proposed range and compares it to
`proposal.old_source`. If they don't match, reject the application and notify
the user.

```python
@server.command("remora.acceptProposal")
async def cmd_accept_proposal(ls, proposal_id: str) -> None:
    proposal = ls.proposals.get(proposal_id)
    if not proposal:
        return

    # NEW: Validate range is still valid
    doc = ls.workspace.get_text_document(proposal.file_path)
    if doc:
        lines = doc.source.splitlines(keepends=True)
        actual = "".join(lines[proposal.start_line - 1 : proposal.end_line])
        if actual.rstrip() != proposal.old_source.rstrip():
            ls.window_show_message(lsp.ShowMessageParams(
                type=lsp.MessageType.Warning,
                message="Proposal is stale — file has changed since proposal was created",
            ))
            del ls.proposals[proposal_id]
            return

    await ls.workspace_apply_edit(...)
```

### Medium-term: Invalidate proposals on `did_change`

In `handlers/documents.py`, when `did_change` fires for a file, invalidate all
pending proposals for that file (or re-check their ranges).

### Long-term: Content-addressed proposals

Replace line-range based proposals with content-addressed patches. Store the
`old_source` hash and use fuzzy matching to find where the original code block
moved to, similar to how `git apply` handles patches with context.
