"""Compatibility alias for moved LSP/runner tool implementations."""

from __future__ import annotations

import sys as _sys

import remora.runner.tools as _target

_sys.modules[__name__] = _target

