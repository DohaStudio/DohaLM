"""Shifted causal language-modeling loss."""

from __future__ import annotations

import torch
import torch.nn.functional as functional
from torch import Tensor

from .errors import ModelValidationError


DEFAULT_IGNORE_INDEX = -100


def causal_language_modeling_loss(
    logits: Tensor,
    labels: Tensor,
    *,
    ignore_index: int = DEFAULT_IGNORE_INDEX,
) -> Tensor:
    """Compute next-token cross entropy using ``logits[:-1]`` and ``labels[1:]``."""

    if not isinstance(logits, Tensor) or logits.ndim != 3:
        raise ModelValidationError("LOGITS_INVALID_SHAPE", "logits must have shape [B, S, V]")
    if not isinstance(labels, Tensor):
        raise ModelValidationError("LABELS_INVALID_TYPE", "labels must be a torch.Tensor")
    if labels.ndim != 2 or tuple(labels.shape) != tuple(logits.shape[:2]):
        raise ModelValidationError("LABELS_SHAPE_MISMATCH", "labels must match logits batch and sequence dimensions")
    if labels.dtype != torch.long:
        raise ModelValidationError("LABELS_INVALID_DTYPE", "labels must use torch.long dtype")
    if labels.device != logits.device:
        raise ModelValidationError("LABELS_DEVICE_MISMATCH", "labels and logits must be on the same device")
    if isinstance(ignore_index, bool) or not isinstance(ignore_index, int):
        raise ModelValidationError("IGNORE_INDEX_INVALID", "ignore_index must be an integer")
    if logits.shape[1] < 2:
        raise ModelValidationError("SEQUENCE_TOO_SHORT_FOR_LOSS", "at least two positions are required for shifted loss")
    vocabulary_size = logits.shape[-1]
    valid_or_ignored = (labels == ignore_index) | ((labels >= 0) & (labels < vocabulary_size))
    if not bool(valid_or_ignored.all().item()):
        raise ModelValidationError(
            "LABEL_TOKEN_OUT_OF_RANGE",
            "labels must be within the vocabulary or equal ignore_index",
        )

    shifted_logits = logits[:, :-1, :].contiguous()
    shifted_labels = labels[:, 1:].contiguous()
    if not bool((shifted_labels != ignore_index).any().item()):
        raise ModelValidationError("ALL_LABELS_IGNORED", "shifted labels contain no valid targets")
    return functional.cross_entropy(
        shifted_logits.view(-1, vocabulary_size),
        shifted_labels.view(-1),
        ignore_index=ignore_index,
    )
