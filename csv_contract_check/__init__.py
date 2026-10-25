"""Validate CSV data against a small, explicit JSON contract, offline."""

from .core import (
    Column,
    Schema,
    SchemaError,
    ValidationError,
    ValidationResult,
    load_schema,
    parse_schema,
    validate_csv,
)

__version__ = "0.1.0"

__all__ = [
    "Column",
    "Schema",
    "SchemaError",
    "ValidationError",
    "ValidationResult",
    "load_schema",
    "parse_schema",
    "validate_csv",
]
