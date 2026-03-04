"""configlib - Configuration file handling library."""

from configlib.loader import load_config, detect_format
from configlib.schema import validate, SchemaError
from configlib.merge import deep_merge

__all__ = ["load_config", "detect_format", "validate", "SchemaError", "deep_merge"]
