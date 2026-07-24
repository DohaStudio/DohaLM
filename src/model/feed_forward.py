"""DohaLM position-wise feed-forward network."""

from __future__ import annotations

from torch import Tensor, nn

from .config import ModelConfig


class FeedForward(nn.Module):
    """Apply ``H -> 4H -> H`` with GELU and provisional dropout."""

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config
        self.input_projection = nn.Linear(config.hidden_size, config.ffn_size, bias=config.linear_bias)
        self.activation = nn.GELU()
        self.output_projection = nn.Linear(config.ffn_size, config.hidden_size, bias=config.linear_bias)
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, hidden_states: Tensor) -> Tensor:
        if not isinstance(hidden_states, Tensor):
            raise TypeError("hidden_states must be a torch.Tensor")
        if hidden_states.ndim != 3:
            raise ValueError("hidden_states must have shape [B, S, H]")
        if hidden_states.shape[-1] != self.config.hidden_size:
            raise ValueError("hidden_states final dimension does not match hidden_size")
        if not hidden_states.is_floating_point():
            raise TypeError("hidden_states must use a floating dtype")
        if hidden_states.device != self.input_projection.weight.device:
            raise ValueError("hidden_states and FeedForward parameters must be on the same device")
        return self.dropout(self.output_projection(self.activation(self.input_projection(hidden_states))))
