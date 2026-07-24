"""Explicit outputs for the integrated DohaLM model."""

from __future__ import annotations

from dataclasses import dataclass

from torch import Tensor


@dataclass(frozen=True)
class DohaLMOutput:
    """Forward result with optional loss and hidden-state snapshots."""

    logits: Tensor
    loss: Tensor | None = None
    hidden_states: tuple[Tensor, ...] | None = None
