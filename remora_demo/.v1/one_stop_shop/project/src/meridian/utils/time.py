"""Time utilities for Meridian."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable


def parse_date(value: str | date) -> date:
    """Parse an ISO date string into a date object."""
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_range(start: date, days: int) -> list[date]:
    """Return a list of dates from start for N days."""
    return [start + timedelta(days=offset) for offset in range(days)]


def days_between(start: date, end: date) -> int:
    """Compute the number of days between two dates."""
    return (end - start).days


def align_to_weekday(values: Iterable[date], weekday: int) -> list[date]:
    """Align dates to a given weekday (0=Monday)."""
    aligned = []
    for value in values:
        delta = (weekday - value.weekday()) % 7
        aligned.append(value + timedelta(days=delta))
    return aligned


__all__ = ["parse_date", "date_range", "days_between", "align_to_weekday"]
