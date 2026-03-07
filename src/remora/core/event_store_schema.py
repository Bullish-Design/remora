"""Compatibility alias for moved EventStore schema helpers."""

from __future__ import annotations

import sys as _sys

import remora.core.store.event_store_schema as _target

_sys.modules[__name__] = _target
