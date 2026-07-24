"""Integrated DohaLM-Tiny Decoder-only language model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import torch
from torch import Tensor, nn

from .block import TransformerBlock
from .config import ModelConfig
from .embeddings import LearnedPositionEmbedding, TokenEmbedding, _validate_token_ids
from .errors import ModelValidationError
from .generation import greedy_generate
from .head import LMHead
from .layer_norm import LayerNorm
from .losses import DEFAULT_IGNORE_INDEX, causal_language_modeling_loss
from .outputs import DohaLMOutput
from .parameter_count import ParameterCounter


class DohaLMTiny(nn.Module):
    """Assemble Phase 3 components into the approved Tiny architecture."""

    def __init__(self, config: ModelConfig | None = None):
        super().__init__()
        self.config = config or ModelConfig()
        self.token_embedding = TokenEmbedding(self.config)
        self.position_embedding = LearnedPositionEmbedding(self.config)
        self.embedding_dropout = nn.Dropout(self.config.dropout)
        self.blocks = nn.ModuleList([TransformerBlock(self.config) for _ in range(self.config.num_layers)])
        self.final_norm = LayerNorm(self.config.hidden_size, self.config.layer_norm_eps)
        self.lm_head = LMHead(self.config, self.token_embedding)

    def _validate_attention_mask(self, input_ids: Tensor, attention_mask: Tensor | None) -> None:
        if attention_mask is None:
            return
        if not isinstance(attention_mask, Tensor):
            raise ModelValidationError("ATTENTION_MASK_INVALID_TYPE", "attention_mask must be a torch.Tensor or None")
        if attention_mask.shape != input_ids.shape:
            raise ModelValidationError("ATTENTION_MASK_SHAPE_MISMATCH", "attention_mask must have shape [B, S]")
        if attention_mask.dtype != torch.bool:
            raise ModelValidationError("ATTENTION_MASK_INVALID_DTYPE", "attention_mask must use torch.bool")
        if attention_mask.device != input_ids.device:
            raise ModelValidationError("ATTENTION_MASK_DEVICE_MISMATCH", "attention_mask and input_ids must share a device")

    def forward(
        self,
        input_ids: Tensor,
        *,
        attention_mask: Tensor | None = None,
        labels: Tensor | None = None,
        return_hidden_states: bool = False,
        ignore_index: int = DEFAULT_IGNORE_INDEX,
    ) -> DohaLMOutput:
        _validate_token_ids(input_ids, self.config)
        self._validate_attention_mask(input_ids, attention_mask)
        if not isinstance(return_hidden_states, bool):
            raise ModelValidationError("RETURN_HIDDEN_STATES_INVALID", "return_hidden_states must be boolean")

        hidden_states = self.embedding_dropout(
            self.token_embedding(input_ids) + self.position_embedding(input_ids)
        )
        snapshots: list[Tensor] | None = [hidden_states] if return_hidden_states else None
        for block in self.blocks:
            hidden_states = block(hidden_states, padding_mask=attention_mask)
            if snapshots is not None:
                snapshots.append(hidden_states)
        hidden_states = self.final_norm(hidden_states)
        if snapshots is not None:
            snapshots.append(hidden_states)
        logits = self.lm_head(hidden_states)
        loss = None
        if labels is not None:
            loss = causal_language_modeling_loss(logits, labels, ignore_index=ignore_index)
        return DohaLMOutput(logits=logits, loss=loss, hidden_states=tuple(snapshots) if snapshots is not None else None)

    def generate(
        self,
        input_ids: Tensor,
        *,
        max_new_tokens: int,
        eos_token_id: int | None = None,
        attention_mask: Tensor | None = None,
    ) -> Tensor:
        return greedy_generate(
            self,
            input_ids,
            max_new_tokens=max_new_tokens,
            eos_token_id=eos_token_id,
            attention_mask=attention_mask,
        )

    def parameter_breakdown(self) -> dict[str, int]:
        count = ParameterCounter.count(self)
        tied = self.token_embedding.weight is self.lm_head.weight
        return {
            "total_parameters": count.total,
            "trainable_parameters": count.trainable,
            "token_embedding": self.token_embedding.weight.numel(),
            "position_embedding": self.position_embedding.weight.numel(),
            "blocks": ParameterCounter.count(self.blocks).total,
            "final_layer_norm": ParameterCounter.count(self.final_norm).total,
            "lm_head_unique": 0 if tied else self.lm_head.weight.numel(),
            "tied_parameter_count": self.token_embedding.weight.numel() if tied else 0,
        }

    def state_dict_with_config(self) -> dict[str, Any]:
        """Return an in-memory state bundle; this is not a checkpoint manager."""

        snapshot = {name: tensor.detach().cpu().clone() for name, tensor in self.state_dict().items()}
        return {"config": self.config.to_dict(), "state_dict": snapshot}

    def load_state_dict_with_config(self, payload: Mapping[str, Any], *, strict: bool = True) -> None:
        if not isinstance(payload, Mapping) or set(payload) != {"config", "state_dict"}:
            raise ModelValidationError("STATE_BUNDLE_INVALID", "payload must contain config and state_dict")
        if payload["config"] != self.config.to_dict():
            raise ModelValidationError("MODEL_CONFIG_MISMATCH", "state config does not match the model config")
        state_dict = payload["state_dict"]
        if not isinstance(state_dict, Mapping):
            raise ModelValidationError("STATE_DICT_INVALID", "state_dict must be a mapping")
        try:
            super().load_state_dict(state_dict, strict=strict)
        except RuntimeError as exc:
            raise ModelValidationError("STATE_DICT_INCOMPATIBLE", str(exc)) from exc
        self.lm_head.tie_weights(self.token_embedding)
