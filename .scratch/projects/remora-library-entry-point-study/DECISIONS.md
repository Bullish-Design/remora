# DECISIONS

## Decision 1: Prioritize runtime bootstraps before deep internals
Reason:
- Studying execution entry points first (`cli`, `lsp`, `serve`) reveals how subsystems are composed in real runs.
- This reduces confusion when later reading low-level modules (store, projection, runner internals).

## Decision 2: Present multiple call-chain views (CLI, LSP, HTTP)
Reason:
- Remora has different operational modes that share core components.
- Seeing each path clarifies what is common core versus adapter-specific behavior.

## Decision 3: Include architecture docs as stage 0, then code
Reason:
- The docs contain the intended model; code tracing validates current implementation.
- This avoids jumping into code with no conceptual framing.

## Decision 4: Flag the `remora-index` script mismatch as an anomaly
Reason:
- It affects how a new reader interprets script entry points.
- Calling this out early avoids wasted time looking for a missing package.
