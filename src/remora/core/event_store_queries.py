"""Compatibility alias for moved EventStore query helpers."""

from __future__ import annotations

import sys as _sys

import remora.core.store.event_store_queries as _target

_sys.modules[__name__] = _target
