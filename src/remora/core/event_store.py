"""Compatibility alias for moved EventStore module."""

from __future__ import annotations

import sys as _sys

import remora.core.store.event_store as _target

_sys.modules[__name__] = _target
