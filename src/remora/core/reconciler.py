"""Compatibility alias for moved reconciler module."""

from __future__ import annotations

import sys as _sys

import remora.core.code.reconciler as _target

_sys.modules[__name__] = _target
