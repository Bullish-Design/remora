# Implementation Guide: Step 15 - Release Readiness

## Target
Ensure the v0.4.0 refactor is fully documented, packaged, and ready for release by updating README, change logs, and verifying `remora` installs cleanly with the new layout.

## Overview
- Document the new architecture in README and `docs/plans/V040_GROUND_UP_REFACTOR_PLAN.md` for easy onboarding.
- Add release notes capturing the clean break from previous versions and note future work (e.g., extended metrics, caching indexes).
- Run `pip install -e .` to verify the package installs with the new CLI entry points and dependencies.

## Steps
1. Update `README.md` to describe the new structure: the unified event bus, Cairn workspace integration, indexer/dashboard services, and human-in-the-loop flow.
2. Publish release notes (e.g., in `docs/RELEASE.md`) summarizing the v0.4.0 goals, breaking changes, and new CLI commands.
3. Run `pip install -e .`, then run `remora --help`, `remora-index --help`, and `remora-dashboard --help` to ensure packaging works.
4. Tag the release branch appropriately and optionally create a branch for future improvements (metrics, caching, extended tooling).
