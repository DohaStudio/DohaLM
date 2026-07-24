"""Dynamic padding collator for causal language-model batches."""

from __future__ import annotations

from collections.abc import Sequence

import torch
from torch import Tensor

from .errors import TrainingError


class CausalLMCollator:
    def __init__(self, *, context_length: int, pad_token_id: int = 0, ignore_index: int = -100):
        if context_length <= 0:
            raise TrainingError("INVALID_TRAINING_CONFIG", "context_length는 양수여야 합니다.")
        self.context_length = context_length
        self.pad_token_id = pad_token_id
        self.ignore_index = ignore_index

    def __call__(self, records: Sequence[dict[str, Tensor]]) -> dict[str, Tensor]:
        if not records:
            raise TrainingError("EMPTY_BATCH", "빈 batch는 허용되지 않습니다.")
        checked: list[tuple[Tensor, Tensor]] = []
        for record in records:
            if not isinstance(record, dict) or "input_ids" not in record or "labels" not in record:
                raise TrainingError("EMPTY_BATCH", "batch record에 input_ids와 labels가 필요합니다.")
            input_ids, labels = record["input_ids"], record["labels"]
            if not isinstance(input_ids, Tensor) or not isinstance(labels, Tensor):
                raise TrainingError("INVALID_TRAINING_CONFIG", "input_ids와 labels는 tensor여야 합니다.")
            if input_ids.ndim != 1 or labels.ndim != 1 or input_ids.shape != labels.shape or input_ids.numel() == 0:
                raise TrainingError("INVALID_TRAINING_CONFIG", "각 record는 같은 길이의 비어 있지 않은 rank-1 tensor여야 합니다.")
            if input_ids.dtype != torch.long or labels.dtype != torch.long:
                raise TrainingError("INVALID_TRAINING_CONFIG", "input_ids와 labels는 torch.long이어야 합니다.")
            if input_ids.numel() > self.context_length:
                raise TrainingError("INVALID_TRAINING_CONFIG", "record 길이가 context_length를 초과했습니다.")
            checked.append((input_ids, labels))
        width = max(ids.numel() for ids, _ in checked)
        batch = len(checked)
        input_batch = torch.full((batch, width), self.pad_token_id, dtype=torch.long)
        label_batch = torch.full((batch, width), self.ignore_index, dtype=torch.long)
        attention_mask = torch.zeros((batch, width), dtype=torch.bool)
        for row, (ids, labels) in enumerate(checked):
            length = ids.numel()
            input_batch[row, :length] = ids
            label_batch[row, :length] = labels
            attention_mask[row, :length] = True
        return {"input_ids": input_batch, "labels": label_batch, "attention_mask": attention_mask}
