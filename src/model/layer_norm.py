"""DohaLM affine Layer Normalization."""

from __future__ import annotations

import torch
from torch import Tensor, nn


class LayerNorm(nn.Module):
    """Normalize the final hidden dimension while preserving shape and dtype."""

    def __init__(self, hidden_size: int, eps: float):
        super().__init__()
        if isinstance(hidden_size, bool) or not isinstance(hidden_size, int) or hidden_size <= 0:
            raise ValueError("hidden_size must be a positive integer")
        if isinstance(eps, bool) or not isinstance(eps, (int, float)) or eps <= 0:
            raise ValueError("eps must be greater than zero")
        self.hidden_size = hidden_size
        self.eps = float(eps)
        self.weight = nn.Parameter(torch.ones(hidden_size))
        self.bias = nn.Parameter(torch.zeros(hidden_size))

    def forward(self, hidden_states: Tensor) -> Tensor:
        if not isinstance(hidden_states, Tensor):
            raise TypeError("hidden_states must be a torch.Tensor")
        if hidden_states.ndim < 2:
            raise ValueError("hidden_states must have rank 2 or greater")
        if hidden_states.shape[-1] != self.hidden_size:
            raise ValueError("hidden_states final dimension does not match hidden_size")
        if not hidden_states.is_floating_point():
            raise TypeError("hidden_states must use a floating dtype")
        if hidden_states.device != self.weight.device:
            raise ValueError("hidden_states and LayerNorm must be on the same device")
        statistics = hidden_states.float() if hidden_states.dtype in (torch.float16, torch.bfloat16) else hidden_states
        mean = statistics.mean(dim=-1, keepdim=True)
        variance = (statistics - mean).pow(2).mean(dim=-1, keepdim=True)
        normalized = (statistics - mean) * torch.rsqrt(variance + self.eps)
        normalized = normalized.to(hidden_states.dtype)
        return normalized * self.weight.to(hidden_states.dtype) + self.bias.to(hidden_states.dtype)
