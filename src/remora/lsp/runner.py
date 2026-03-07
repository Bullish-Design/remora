"""Compatibility alias for moved runner module."""

from __future__ import annotations

import sys as _sys

import remora.runner.agent_runner as _target

_sys.modules[__name__] = _target
