"""Fast line lookup helpers for byte content."""

from __future__ import annotations


class LineIndex:
    """Maps row index to source text line for UTF-8 bytes."""

    def __init__(self, source: bytes) -> None:
        self._lines = source.splitlines(keepends=False)

    def line_at_row(self, row: int) -> str:
        """Return decoded line or empty string when row is out of range."""

        if row < 0 or row >= len(self._lines):
            return ""
        return self._lines[row].decode("utf-8", errors="replace")

    def line_count(self) -> int:
        """Return number of lines in source content."""

        return len(self._lines)
