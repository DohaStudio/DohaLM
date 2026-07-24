"""Direct causal multi-head self-attention implementation."""

from __future__ import annotations

import math

import torch
from torch import Tensor, nn

from .config import ModelConfig


class CausalMultiHeadAttention(nn.Module):
    """Causal self-attention with an optional boolean key padding mask."""

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config
        self.qkv_projection = nn.Linear(
            config.hidden_size,
            3 * config.hidden_size,
            bias=config.linear_bias,
        )
        self.output_projection = nn.Linear(
            config.hidden_size,
            config.hidden_size,
            bias=config.linear_bias,
        )
        self.attention_dropout = nn.Dropout(config.dropout)
        self.output_dropout = nn.Dropout(config.dropout)
        causal_mask = torch.tril(torch.ones(config.context_length, config.context_length, dtype=torch.bool))
        self.register_buffer("causal_mask", causal_mask.view(1, 1, config.context_length, config.context_length), persistent=False)

    def _validate(self, hidden_states: Tensor, padding_mask: Tensor | None) -> tuple[int, int]:
        if not isinstance(hidden_states, Tensor):
            raise TypeError("hidden_states must be a torch.Tensor")
        if hidden_states.ndim != 3:
            raise ValueError("hidden_states must have shape [B, S, H]")
        batch_size, sequence_length, hidden_size = hidden_states.shape
        if batch_size <= 0 or sequence_length <= 0:
            raise ValueError("batch and sequence dimensions must be positive")
        if hidden_size != self.config.hidden_size:
            raise ValueError("hidden_states final dimension does not match hidden_size")
        if sequence_length > self.config.context_length:
            raise ValueError("sequence length exceeds context_length")
        if not hidden_states.is_floating_point():
            raise TypeError("hidden_states must use a floating dtype")
        if hidden_states.device != self.qkv_projection.weight.device:
            raise ValueError("hidden_states and attention parameters must be on the same device")
        if padding_mask is not None:
            if not isinstance(padding_mask, Tensor):
                raise TypeError("padding_mask must be a torch.Tensor or None")
            if padding_mask.shape != (batch_size, sequence_length):
                raise ValueError("padding_mask must have shape [B, S]")
            if padding_mask.dtype != torch.bool:
                raise TypeError("padding_mask must use torch.bool; True means a valid token")
            if padding_mask.device != hidden_states.device:
                raise ValueError("padding_mask and hidden_states must be on the same device")
        return batch_size, sequence_length

    def forward(self, hidden_states: Tensor, padding_mask: Tensor | None = None) -> Tensor:
        batch_size, sequence_length = self._validate(hidden_states, padding_mask)
        qkv = self.qkv_projection(hidden_states)
        query, key, value = qkv.chunk(3, dim=-1)

        def split_heads(tensor: Tensor) -> Tensor:
            return tensor.view(batch_size, sequence_length, self.config.num_heads, self.config.head_dim).transpose(1, 2)

        query, key, value = (split_heads(tensor) for tensor in (query, key, value))
        scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(self.config.head_dim)
        allowed = self.causal_mask[:, :, :sequence_length, :sequence_length]
        if padding_mask is not None:
            allowed = allowed & padding_mask[:, None, None, :]
        scores = scores.masked_fill(~allowed, torch.finfo(scores.dtype).min)
        probabilities = torch.softmax(scores, dim=-1)
        probabilities = self.attention_dropout(probabilities)
        attended = torch.matmul(probabilities, value)
        merged = attended.transpose(1, 2).contiguous().view(batch_size, sequence_length, self.config.hidden_size)
        output = self.output_dropout(self.output_projection(merged))
        if padding_mask is not None:
            output = output * padding_mask.unsqueeze(-1).to(output.dtype)
        return output
