"""Compatibility alias for moved swarm_executor module."""

from __future__ import annotations

import sys as _sys

import remora.core.agents.swarm_executor as _target

_sys.modules[__name__] = _target
