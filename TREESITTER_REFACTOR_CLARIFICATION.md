# Remora Treesitter Refactor Clarification:


## User:
Study the remora library, which was recently refactored to take advantage of its underlying libraries. Unfortunately, the pydantree library is broken without an upcoming fix, and we need to completely refactor the remora library to instead utilize treesitter directly. Please study the TREESITTER_REFACTOR.md document, which is a first attempt (by a junior developer) to provide an overview and roadmap of how to completely refactor the remora library to utilize treesitter directly.

I want you to study the refactoring document, then study the remora library and goals, and then ask me whatever questions you want to be sure we're on the same page before we revise the treesitter refactoring plan

**Note:** We do not care about backwards compatibility - only having the best possible architecture and codebase moving forward.

## Agent:
Now I have a thorough picture of everything. Let me ask my questions.

I've read the TREESITTER_REFACTOR.md, all the key source files, and the existing query packs. Here's what I want to clarify before we revise the plan:
AskUserQuestion
User has answered your questions: "The plan adds a METHOD node type (distinct from FUNCTION). Methods are just function_definition nodes inside a class body in tree-sitter. How should we handle this?"="Detect via tree parent (Recommended)", "The plan proposes a full_name property giving qualified names like 'Greeter.greet'. This requires tracking parent context during tree traversal — non-trivial. Should we include it?"="Yes, track parent context (Recommended)", "The plan renames CSTNode.node_id → id and CSTNode.text → source_text. Both are referenced in runner.py, subagent.py, orchestrator.py, and analyzer.py. Since we're not worried about backwards compat, which naming do you prefer?"="Keep node_id / text (Recommended)", "There are currently two query directories: remora/queries/ (inside the package) and queries/python/remora_core/ (at the project root). The plan defaults query_dir to the project-root 'queries/'. Where should the built-in queries live?"="Inside the package (Recommended)". You can now continue with the user's answers in mind.
AskUserQuestion
User has answered your questions: "The plan adds parallel file processing (ThreadPoolExecutor, max_workers=4) to DiscoveryConfig. Remora's typical use case is one project at a time. Should parallelism be in scope for this refactor?"="Keep it simple for now, but make a note about where/how parallelism should be introduced if/when it becomes necessary", "The plan adds start_line and end_line to CSTNode (tree-sitter provides these for free). The file.scm query currently captures granular items (module docstring, individual imports) that would produce many file-type nodes. Should we simplify the file query to just emit one FILE node per file?"="One FILE node per file (Recommended)", "The plan changes the node_id hash from sha1(file_path::node_type::name) to sha256(file:name:start_byte). Start byte makes IDs unique for overloaded names, but IDs shift when code is reformatted. Which stability guarantee matters more?"="sha256(file:node_type:name) — name-stable (Recommended)", "The plan moves DiscoveryConfig out of config.py into discovery/models.py. But DiscoveryConfig is a field of RemoraConfig (the top-level config). Where should it live?"="Keep in config.py (Recommended)". You can now continue with the user's answers in mind.

One more follow-up question, then I'll have everything I need:
AskUserQuestion
User has answered your questions: "The old remora/queries/function_def.scm gave async functions their own capture (@async_function.def). The newer queries/python/remora_core/ treats async and sync functions identically. With the new NodeType enum, should async functions be distinguishable?"="No — FUNCTION covers both (Recommended)", "The project root has a queries/ directory that duplicates the remora/queries/ content. Once queries move inside the package, what should happen to the project-root queries/?"="Delete it — queries belong in the package". You can now continue with the user's answers in mind.

Here's a summary of every design decision we've aligned on — this is the foundation for the revised plan:

---

**CSTNode model**
- Keep field names `node_id` and `text` (no rename)
- Add `start_line` and `end_line` (free from tree-sitter)
- `node_type` becomes a `NodeType` enum: `FILE`, `CLASS`, `FUNCTION`, `METHOD`
- Add `full_name` property: qualified name like `Greeter.greet` (built by walking tree-sitter parent chain during extraction, not stored)
- `node_id` hash: `sha256(file_path:node_type:name)` — stable across reformatting

**Node type detection**
- `METHOD` vs `FUNCTION` detected by inspecting tree-sitter parents during extraction — no new `.scm` files needed
- Async and sync functions are both `FUNCTION` — no distinction

**Queries**
- Live inside the package: `remora/queries/python/remora_core/`
- Consolidate `remora/queries/` and `queries/python/remora_core/` into one location (the former)
- Delete the project-root `queries/` directory
- `file.scm` simplified to emit exactly one `FILE` node per module root
- `function_def.scm` unified: same capture names for sync and async

**Configuration**
- `DiscoveryConfig` stays in `config.py` as a field of `RemoraConfig`
- Add `query_dir: Path` to `DiscoveryConfig` pointing to the built-in queries inside the package (overridable via `remora.yaml`)
- No `fail_fast`, `max_workers`, or `cache_trees` in this refactor — note in the plan where parallelism/caching would slot in later

**Architecture**
- `remora/discovery.py` → `remora/discovery/` package
- Components: `discoverer.py`, `query_loader.py`, `source_parser.py`, `match_extractor.py`, `models.py`
- No legacy stub — clean break
- Tests rewritten using real tree-sitter (no subprocess mocking)

---

I apologize for the repeated question loops. I now have everything I need. Here is the complete set of aligned decisions:

| Topic | Decision |
|---|---|
| `node_id` / `text` field names | **Keep as-is** |
| Method detection | **Tree-sitter parent inspection** (no new .scm files) |
| Async functions | **`FUNCTION` covers both** |
| `full_name` property | **Yes** — walk parent chain at extraction time |
| Query location | **Inside the package** at `remora/queries/python/remora_core/` |
| Project-root `queries/` dir | **Delete it** |
| `file.scm` | **Simplified to one FILE node per module** |
| `DiscoveryConfig` location | **Stay in `config.py`** |
| `node_id` hash | **`sha256(file:node_type:name)`** — name-stable |
| Parallelism | **Not in this refactor** — document where it would go |
| `NodeType` enum values | `FILE`, `CLASS`, `FUNCTION`, `METHOD` |
| New fields on `CSTNode` | `start_line`, `end_line` added |
| Legacy stub | **None** — clean break |
| Tests | **Real tree-sitter** — no subprocess mocking |

Ready to rewrite `TREESITTER_REFACTOR.md`. Want me to proceed?

## User:

Great. Please rewrite the TREESITTER_REFACTOR.md document into a detailed overview and dev guide that reflects this new plan. Be sure it contains an appropriate level of context so a junior developer has everything they need to be able to follow the refactoring guide step by step to implement the full refactor. 

Be sure to break down changes into discrete chunks of work that can be tested/verified at each step, so we can be sure the work is implemented correctly before continuing. Be sure to provide an overview of the testing/verification that will be required for each discrete chunk of work. 

Be sure to structure the changes in a logical manner so that initial work doesn't have to be reworked later on in later steps. 

Be sure to also introduce some sort of "round trip" test harness for each node type that takes in all python files in an input/ directory and outputs the text of whatever it matches (or the error message/output generated) into an associated output/ directory when its run. It should be easy for a developer to toss new sample files in, run the harness, and check to see the outputs. Save output as '<input_filename>_out', and save duplicate matches as '<input_filename>_out-<num>'.

Be sure that this document outlines **everything** that will need to be updated based on this change - documentation, test suite, demonstration scripts, etc.

