"""Writeback scaffold for adding missing inline graph IDs."""

from __future__ import annotations

from pathlib import Path


def annotate_missing_ids(path: Path, *, dry_run: bool = True) -> str:
    """Return an annotation plan for a file.

    TODO: implement AST-aware writeback logic with duplicate detection and safe edits.
    """

    mode = "dry-run" if dry_run else "apply"
    return f"{mode}: annotation not implemented for {path}"
