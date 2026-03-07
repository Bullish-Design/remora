"""Compatibility alias for moved cairn_externals module."""

from __future__ import annotations

import sys as _sys

import remora.core.agents.cairn_externals as _target

_sys.modules[__name__] = _target
