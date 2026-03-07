# Decisions

1. Apply immediate fix at highest level (Remora) first.
- Rationale: fast, contained, no dependency release required, resolves active test failures.

2. Keep long-term architecture direction in FSdantic/Cairn.
- Rationale: policy should live near workspace implementation, not be hardcoded at app layer.

3. Prefer explicit policy plumbing over hidden monkeypatching.
- Rationale: maintainability and debuggability across Remora/Cairn/FSdantic boundaries.
