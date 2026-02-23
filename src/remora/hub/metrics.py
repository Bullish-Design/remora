"""
src/remora/hub/metrics.py

Metrics collection for Hub daemon observability.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HubMetrics:
    """Collects and exposes Hub daemon metrics."""

    # Counters
    files_indexed: int = 0
    nodes_extracted: int = 0
    files_failed: int = 0
    file_changes_processed: int = 0

    # Timing (seconds)
    total_index_time: float = 0.0
    last_index_duration: float = 0.0
    cold_start_duration: float = 0.0

    # Gauges
    current_node_count: int = 0
    current_file_count: int = 0
    workspace_size_bytes: int = 0

    # Internal
    _start_times: dict[str, float] = field(default_factory=dict)

    def start_timer(self, name: str) -> None:
        """Start a named timer."""
        self._start_times[name] = time.monotonic()

    def stop_timer(self, name: str) -> float:
        """Stop a timer and return elapsed seconds."""
        if name not in self._start_times:
            return 0.0
        elapsed = time.monotonic() - self._start_times.pop(name)
        return elapsed

    def record_file_indexed(self, nodes: int, duration: float) -> None:
        """Record a successful file index."""
        self.files_indexed += 1
        self.nodes_extracted += nodes
        self.total_index_time += duration
        self.last_index_duration = duration

    def record_file_failed(self) -> None:
        """Record a failed file index."""
        self.files_failed += 1

    def record_file_change(self) -> None:
        """Record a file change event processed."""
        self.file_changes_processed += 1

    def to_dict(self) -> dict[str, Any]:
        """Export metrics as dictionary."""
        return {
            "counters": {
                "files_indexed": self.files_indexed,
                "nodes_extracted": self.nodes_extracted,
                "files_failed": self.files_failed,
                "file_changes_processed": self.file_changes_processed,
            },
            "timing": {
                "total_index_time_seconds": round(self.total_index_time, 3),
                "last_index_duration_seconds": round(self.last_index_duration, 3),
                "cold_start_duration_seconds": round(self.cold_start_duration, 3),
                "avg_index_time_seconds": round(
                    self.total_index_time / max(self.files_indexed, 1), 3
                ),
            },
            "gauges": {
                "current_node_count": self.current_node_count,
                "current_file_count": self.current_file_count,
                "workspace_size_bytes": self.workspace_size_bytes,
            },
        }


# Global metrics instance
_metrics: HubMetrics | None = None


def get_metrics() -> HubMetrics:
    """Get or create the global metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = HubMetrics()
    return _metrics


def reset_metrics() -> None:
    """Reset metrics (for testing)."""
    global _metrics
    _metrics = None
