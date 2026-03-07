"""Compatibility alias for moved state_manager module."""

from __future__ import annotations

import sys as _sys

import remora.core.agents.state_manager as _target

_sys.modules[__name__] = _target
