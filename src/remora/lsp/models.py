"""Compatibility alias for moved LSP/runner event models."""

from __future__ import annotations

import sys as _sys

import remora.runner.events as _target

_sys.modules[__name__] = _target

