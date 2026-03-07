"""Compatibility alias for moved agent_node module."""

from __future__ import annotations

import sys as _sys

import remora.core.agents.agent_node as _target

_sys.modules[__name__] = _target
