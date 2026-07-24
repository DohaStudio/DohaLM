"""Pre-LayerNorm Decoder-only Transformer block."""

from __future__ import annotations

from torch import Tensor, nn

from .attention import CausalMultiHeadAttention
from .config import ModelConfig
from .feed_forward import FeedForward
from .layer_norm import LayerNorm


class TransformerBlock(nn.Module):
    """Apply attention and FFN as ``x + sublayer(LN(x))``."""

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config
        self.attention_norm = LayerNorm(config.hidden_size, config.layer_norm_eps)
        self.attention = CausalMultiHeadAttention(config)
        self.feed_forward_norm = LayerNorm(config.hidden_size, config.layer_norm_eps)
        self.feed_forward = FeedForward(config)

    def forward(self, hidden_states: Tensor, padding_mask: Tensor | None = None) -> Tensor:
        attention_output = self.attention(self.attention_norm(hidden_states), padding_mask=padding_mask)
        hidden_states = hidden_states + attention_output
        return hidden_states + self.feed_forward(self.feed_forward_norm(hidden_states))
