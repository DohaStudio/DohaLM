"""Validated configuration for DohaLM Transformer components."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SPECIAL_TOKEN_COUNT = 8


@dataclass(frozen=True)
class ModelConfig:
    """Immutable DohaLM-Tiny component configuration.

    ``dropout`` and ``layer_norm_eps`` are provisional component-smoke
    defaults, not approved training hyperparameters. ``initialization`` stays
    unset until a later decision defines a DohaLM-wide initialization policy.
    """

    vocab_size: int = 16_000
    context_length: int = 256
    num_layers: int = 6
    hidden_size: int = 384
    num_heads: int = 6
    head_dim: int = 64
    ffn_size: int = 1_536
    dropout: float = 0.0
    layer_norm_eps: float = 1e-5
    linear_bias: bool = True
    lm_head_bias: bool = False
    tie_word_embeddings: bool = True
    initialization: str | None = None

    def __post_init__(self) -> None:
        integer_fields = (
            "vocab_size",
            "context_length",
            "num_layers",
            "hidden_size",
            "num_heads",
            "head_dim",
            "ffn_size",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.vocab_size <= SPECIAL_TOKEN_COUNT:
            raise ValueError("vocab_size must be greater than the special token count")
        if self.hidden_size % self.num_heads != 0:
            raise ValueError("hidden_size must be divisible by num_heads")
        if self.head_dim != self.hidden_size // self.num_heads:
            raise ValueError("head_dim must equal hidden_size // num_heads")
        if isinstance(self.dropout, bool) or not isinstance(self.dropout, (int, float)):
            raise ValueError("dropout must be a number")
        if not 0.0 <= float(self.dropout) < 1.0:
            raise ValueError("dropout must satisfy 0 <= dropout < 1")
        if isinstance(self.layer_norm_eps, bool) or not isinstance(self.layer_norm_eps, (int, float)):
            raise ValueError("layer_norm_eps must be a number")
        if float(self.layer_norm_eps) <= 0:
            raise ValueError("layer_norm_eps must be greater than zero")
        for name in ("linear_bias", "lm_head_bias", "tie_word_embeddings"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")
        if not self.linear_bias:
            raise ValueError("DohaLM-Tiny requires linear_bias=True")
        if self.lm_head_bias:
            raise ValueError("DohaLM-Tiny requires lm_head_bias=False")
        if not self.tie_word_embeddings:
            raise ValueError("DohaLM-Tiny requires tie_word_embeddings=True")
        if self.initialization is not None:
            raise ValueError("initialization is not decided; it must remain None")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
