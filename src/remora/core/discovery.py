"""Compatibility alias for moved discovery module."""

from __future__ import annotations

import sys as _sys

import remora.core.code.discovery as _target

_sys.modules[__name__] = _target
