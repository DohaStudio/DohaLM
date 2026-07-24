"""Bias-free language-model projection with explicit weight tying."""

from __future__ import annotations

import torch
from torch import Tensor, nn

from .config import ModelConfig
from .embeddings import TokenEmbedding


class LMHead(nn.Module):
    """Project ``[B, S, H]`` to ``[B, S, V]`` and optionally share embedding weight."""

    def __init__(self, config: ModelConfig, token_embedding: TokenEmbedding | nn.Embedding | None = None):
        super().__init__()
        self.config = config
        self.projection = nn.Linear(config.hidden_size, config.vocab_size, bias=config.lm_head_bias)
        if token_embedding is not None:
            self.tie_weights(token_embedding)

    @staticmethod
    def _embedding_weight(token_embedding: TokenEmbedding | nn.Embedding) -> nn.Parameter:
        if isinstance(token_embedding, TokenEmbedding):
            return token_embedding.weight
        if isinstance(token_embedding, nn.Embedding):
            return token_embedding.weight
        raise TypeError("token_embedding must be TokenEmbedding or torch.nn.Embedding")

    def tie_weights(self, token_embedding: TokenEmbedding | nn.Embedding) -> None:
        weight = self._embedding_weight(token_embedding)
        expected = (self.config.vocab_size, self.config.hidden_size)
        if tuple(weight.shape) != expected:
            raise ValueError(f"token embedding weight must have shape {expected}")
        self.projection.weight = weight

    @property
    def weight(self) -> nn.Parameter:
        return self.projection.weight

    def forward(self, hidden_states: Tensor) -> Tensor:
        if not isinstance(hidden_states, Tensor):
            raise TypeError("hidden_states must be a torch.Tensor")
        if hidden_states.ndim != 3:
            raise ValueError("hidden_states must have shape [B, S, H]")
        if hidden_states.shape[-1] != self.config.hidden_size:
            raise ValueError("hidden_states final dimension does not match hidden_size")
        if not hidden_states.is_floating_point():
            raise TypeError("hidden_states must use a floating dtype")
        if hidden_states.device != self.weight.device:
            raise ValueError("hidden_states and LMHead parameters must be on the same device")
        return self.projection(hidden_states)
