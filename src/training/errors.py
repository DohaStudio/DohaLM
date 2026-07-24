"""Stable errors for bounded training and checkpoint operations."""

from __future__ import annotations


class TrainingError(ValueError):
    """Training failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")
