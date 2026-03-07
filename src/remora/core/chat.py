"""Compatibility alias for moved chat module."""

from __future__ import annotations

import sys as _sys

import remora.core.agents.chat as _target

_sys.modules[__name__] = _target
