"""Explicit model integration validation errors."""

from __future__ import annotations


class ModelValidationError(ValueError):
    """A stable error code plus a concise validation message."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
