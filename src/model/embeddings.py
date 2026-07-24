"""Token and learned absolute position embeddings."""

from __future__ import annotations

import torch
from torch import Tensor, nn

from .config import ModelConfig


def _validate_token_ids(input_ids: Tensor, config: ModelConfig) -> None:
    if not isinstance(input_ids, Tensor):
        raise TypeError("input_ids must be a torch.Tensor")
    if input_ids.ndim != 2:
        raise ValueError("input_ids must have rank 2 with shape [B, S]")
    if input_ids.dtype != torch.long:
        raise TypeError("input_ids must use torch.long dtype")
    if input_ids.shape[0] <= 0 or input_ids.shape[1] <= 0:
        raise ValueError("input_ids batch and sequence dimensions must be positive")
    if input_ids.shape[1] > config.context_length:
        raise ValueError("sequence length exceeds context_length")
    minimum, maximum = torch.aminmax(input_ids)
    if minimum.item() < 0 or maximum.item() >= config.vocab_size:
        raise ValueError("input_ids contain a token outside the vocabulary")


class TokenEmbedding(nn.Module):
    """Map token IDs ``[B, S]`` to hidden states ``[B, S, H]``."""

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config
        self.embedding = nn.Embedding(config.vocab_size, config.hidden_size)

    @property
    def weight(self) -> nn.Parameter:
        return self.embedding.weight

    def forward(self, input_ids: Tensor) -> Tensor:
        _validate_token_ids(input_ids, self.config)
        if input_ids.device != self.weight.device:
            raise ValueError("input_ids and token embedding must be on the same device")
        return self.embedding(input_ids)


class LearnedPositionEmbedding(nn.Module):
    """Generate ``0..S-1`` and return learned positions ``[B, S, H]``."""

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config
        self.embedding = nn.Embedding(config.context_length, config.hidden_size)

    @property
    def weight(self) -> nn.Parameter:
        return self.embedding.weight

    def position_ids(self, input_ids: Tensor) -> Tensor:
        _validate_token_ids(input_ids, self.config)
        if input_ids.device != self.weight.device:
            raise ValueError("input_ids and position embedding must be on the same device")
        return torch.arange(input_ids.shape[1], device=input_ids.device, dtype=torch.long)

    def forward(self, input_ids: Tensor) -> Tensor:
        positions = self.position_ids(input_ids)
        values = self.embedding(positions)
        return values.unsqueeze(0).expand(input_ids.shape[0], -1, -1)
