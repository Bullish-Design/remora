"""Compatibility alias for moved agent_context module."""

from __future__ import annotations

import sys as _sys

import remora.core.agents.agent_context as _target

_sys.modules[__name__] = _target
