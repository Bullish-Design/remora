# Implementation Guide: Step 9 - Pure-Function .pym Scripts

## Target
Rework each agent bundle so `.pym` tools rely on `Input()`/virtual files and return structured results; reserve `@external` solely for `ask_user` and other true external services.

## Overview
- Data flows in via `CairnDataProvider` with bundle-specific `load_files()` hooks that populate the Grail virtual filesystem before execution.
- Tools run as pure functions: no `@external` file or command IO, just `Input()` declarations describing required data and a dict return value describing mutations.
- `CairnResultHandler` implementations per bundle interpret the returned dicts and persist new files, fixes, or metadata back into the workspace.

## Steps
1. For each bundle (`lint`, `docstring`, `test`, `sample_data`, `harness`), audit every `.pym` tool and replace file I/O externals with `Input()`-declared values (source code, config, test fixtures). Remove redundant helper scripts that merely wrapped filesystem reads.
2. Build bundle-specific `DataProvider` subclasses of `CairnDataProvider` that know which files (target, configs, tests) need to be preloaded into `files={}` before tool execution.
3. Build bundle-specific `ResultHandler` subclasses of `CairnResultHandler` that interpret outputs such as `fixed_code`, `issues`, `generated_tests`, and persist them via `workspace.write()`.
4. Run `grail check` on each rewritten `.pym` and add smoke tests verifying the DataProvider → tool → ResultHandler flow, ensuring no script uses `@external` for filesystem access except `ask_user`.
