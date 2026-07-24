"""Shared corpus adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AdapterPolicy:
    """Bounded text policy for a dataset adapter."""

    minimum_text_characters: int = 1
    maximum_text_characters: int = 100_000

    def __post_init__(self) -> None:
        if self.minimum_text_characters < 1:
            raise ValueError("minimum_text_characters must be at least 1")
        if self.maximum_text_characters < self.minimum_text_characters:
            raise ValueError("maximum_text_characters must not be smaller than the minimum")


@dataclass(frozen=True)
class AdapterOutcome:
    """Exactly one accepted record or one privacy-safe rejection."""

    accepted: dict[str, Any] | None = None
    rejected: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if (self.accepted is None) == (self.rejected is None):
            raise ValueError("an adapter outcome must contain exactly one result")
