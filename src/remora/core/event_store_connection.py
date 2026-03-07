"""Compatibility alias for moved EventStore connection helpers."""

from __future__ import annotations

import sys as _sys

import remora.core.store.event_store_connection as _target

_sys.modules[__name__] = _target
