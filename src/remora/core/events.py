"""Compatibility alias for moved core events module."""

from __future__ import annotations

import sys as _sys

import remora.core.events.events as _target

_sys.modules[__name__] = _target
