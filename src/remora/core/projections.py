"""Compatibility alias for moved projections module."""

from __future__ import annotations

import sys as _sys

import remora.core.code.projections as _target

_sys.modules[__name__] = _target
