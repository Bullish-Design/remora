# src/remora/errors.py
from __future__ import annotations

class RemoraError(Exception):
    """Base exception for all Remora errors."""
    code: str = "REMORA-UNKNOWN"
    recoverable: bool = False
    
    def __init__(self, message: str, code: str | None = None, recoverable: bool | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code
        if recoverable is not None:
            self.recoverable = recoverable

class ConfigurationError(RemoraError):
    code = "REMORA-CONFIG"

class DiscoveryError(RemoraError):
    code = "REMORA-DISCOVERY"

class ExecutionError(RemoraError):
    code = "REMORA-EXEC"
    recoverable = True

class SubagentError(RemoraError):
    code = "REMORA-AGENT"
