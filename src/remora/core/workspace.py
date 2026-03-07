"""Compatibility alias for moved workspace module."""

from __future__ import annotations

import sys as _sys

import remora.core.agents.workspace as _target

_sys.modules[__name__] = _target
