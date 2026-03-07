"""Compatibility alias for moved execution module."""

from __future__ import annotations

import sys as _sys

import remora.core.agents.execution as _target

_sys.modules[__name__] = _target
