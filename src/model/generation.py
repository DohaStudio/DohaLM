"""Minimal full-prefix greedy autoregressive generation."""

from __future__ import annotations

from typing import Protocol

import torch
from torch import Tensor

from .errors import ModelValidationError
from .outputs import DohaLMOutput


class _GreedyModel(Protocol):
    training: bool
    config: object

    def eval(self) -> object: ...
    def train(self, mode: bool = True) -> object: ...
    def __call__(self, input_ids: Tensor, *, attention_mask: Tensor | None = None) -> DohaLMOutput: ...


def greedy_generate(
    model: _GreedyModel,
    input_ids: Tensor,
    *,
    max_new_tokens: int,
    eos_token_id: int | None = None,
    attention_mask: Tensor | None = None,
) -> Tensor:
    """Generate with argmax only; finished batch rows repeat EOS until all finish."""

    if isinstance(max_new_tokens, bool) or not isinstance(max_new_tokens, int) or max_new_tokens <= 0:
        raise ModelValidationError("MAX_NEW_TOKENS_INVALID", "max_new_tokens must be a positive integer")
    context_length = getattr(model.config, "context_length", None)
    vocabulary_size = getattr(model.config, "vocab_size", None)
    if not isinstance(context_length, int) or not isinstance(vocabulary_size, int):
        raise ModelValidationError("MODEL_CONFIG_INVALID", "model config must define context_length and vocab_size")
    if not isinstance(input_ids, Tensor) or input_ids.ndim != 2:
        raise ModelValidationError("INPUT_IDS_INVALID_SHAPE", "input_ids must have shape [B, S]")
    if input_ids.shape[1] + max_new_tokens > context_length:
        raise ModelValidationError("GENERATION_CONTEXT_EXCEEDED", "prompt plus max_new_tokens exceeds context_length")
    if eos_token_id is not None:
        if isinstance(eos_token_id, bool) or not isinstance(eos_token_id, int):
            raise ModelValidationError("EOS_TOKEN_INVALID", "eos_token_id must be an integer or None")
        if not 0 <= eos_token_id < vocabulary_size:
            raise ModelValidationError("EOS_TOKEN_OUT_OF_RANGE", "eos_token_id is outside the vocabulary")
    if attention_mask is not None:
        if not isinstance(attention_mask, Tensor) or attention_mask.shape != input_ids.shape:
            raise ModelValidationError("ATTENTION_MASK_SHAPE_MISMATCH", "attention_mask must match input_ids")
        if attention_mask.dtype != torch.bool:
            raise ModelValidationError("ATTENTION_MASK_INVALID_DTYPE", "attention_mask must use torch.bool")
        if attention_mask.device != input_ids.device:
            raise ModelValidationError("ATTENTION_MASK_DEVICE_MISMATCH", "attention_mask and input_ids must share a device")

    generated = input_ids.clone()
    current_mask = attention_mask.clone() if attention_mask is not None else None
    finished = torch.zeros(input_ids.shape[0], dtype=torch.bool, device=input_ids.device)
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            for _ in range(max_new_tokens):
                output = model(generated, attention_mask=current_mask)
                next_tokens = torch.argmax(output.logits[:, -1, :], dim=-1)
                if eos_token_id is not None:
                    next_tokens = torch.where(
                        finished,
                        torch.full_like(next_tokens, eos_token_id),
                        next_tokens,
                    )
                    finished = finished | (next_tokens == eos_token_id)
                generated = torch.cat((generated, next_tokens.unsqueeze(1)), dim=1)
                if current_mask is not None:
                    current_mask = torch.cat(
                        (current_mask, torch.ones((current_mask.shape[0], 1), dtype=torch.bool, device=current_mask.device)),
                        dim=1,
                    )
                if eos_token_id is not None and bool(finished.all().item()):
                    break
    finally:
        model.train(was_training)
    return generated
