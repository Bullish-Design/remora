"""Compatibility alias for moved subscriptions module."""

from __future__ import annotations

import sys as _sys

import remora.core.events.subscriptions as _target

_sys.modules[__name__] = _target
