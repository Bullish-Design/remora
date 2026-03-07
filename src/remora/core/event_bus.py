"""Compatibility alias for moved event bus module."""

from __future__ import annotations

import sys as _sys

import remora.core.events.event_bus as _target

_sys.modules[__name__] = _target
