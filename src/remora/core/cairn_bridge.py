"""Compatibility alias for moved cairn_bridge module."""

from __future__ import annotations

import sys as _sys

import remora.core.agents.cairn_bridge as _target

_sys.modules[__name__] = _target
