# DECISIONS — Demo Rebuild

## D1: Two-subdirectory structure with separate devenv.nix
**Date:** 2026-03-02
**Decision:** Split `remora_demo/` into `neovim/` (Python 3.13) and `web/` (Python 3.14) subdirectories, each with their own `devenv.nix`.
**Rationale:** Stario requires Python 3.14. vllm (used by Remora's LLM integration) requires Python 3.13. Can't satisfy both in one env.
**Constraint from:** User requirement.

## D2: configlib project lives in remora_demo/project/
**Date:** 2026-03-02
**Decision:** The demo project files (configlib source, tests, remora.yaml, .remora/) live in `remora_demo/project/`, accessible to both subdirectories.
**Rationale:** Both the neovim LSP side and the web graph viewer need to reference the same project files.

## D3: Archive existing remora_demo/ before rebuilding
**Date:** 2026-03-02
**Decision:** Move existing `remora_demo/` to `remora_demo.old/` before creating the new structure.
**Rationale:** Preserve the old code for reference. The old code already has a `.v1` backup inside it.

## D4: Start with demo project + MockLLM (T1, T2, T14), skip re-evaluating T3-T13
**Date:** 2026-03-02
**Decision:** Begin with the independent tasks (configlib files, extension configs, MockLLM) rather than re-auditing the core migration tasks.
**Rationale:** T3-T13 overlap heavily with Option A which is already complete. The demo project files and MockLLM are net-new work with no dependencies.

## D5: Stario runs in web/ subdirectory with its own Python 3.14 devenv
**Date:** 2026-03-02
**Decision:** Stario is NOT available in the main Remora environment (Python 3.13). It will be installed in `remora_demo/web/` which has its own `devenv.nix` running Python 3.14. We write code targeting Stario's API; it runs in that separate environment. Unit tests for framework-independent pieces (ForceLayout, SVG string builders, CSS) can run in the main env. Tests that import Stario can only run under the web devenv.
**Rationale:** vllm requires Python 3.13; Stario requires Python 3.14. Two separate Python environments are needed. User confirmed this architecture.
**Implication:** For TDD, split tests into: (a) pure-logic tests (layout, SVG output, CSS) — run in main env, no Stario import; (b) integration tests (app, handlers, bridge) — run only under web devenv.
