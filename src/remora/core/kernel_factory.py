"""Compatibility alias for moved kernel_factory module."""

from __future__ import annotations

import sys as _sys

import remora.core.agents.kernel_factory as _target

_sys.modules[__name__] = _target
