from __future__ import annotations

import pytest
import torch

from src.training import CausalLMCollator, TrainingError


def record(values):
    ids = torch.tensor(values, dtype=torch.long)
    return {"input_ids": ids, "labels": ids.clone()}


def test_dynamic_padding_attention_and_ignore_index():
    batch = CausalLMCollator(context_length=8)([record([2, 10, 3]), record([2, 11, 12, 13, 3])])
    assert batch["input_ids"].tolist()[0] == [2, 10, 3, 0, 0]
    assert batch["labels"].tolist()[0] == [2, 10, 3, -100, -100]
    assert batch["attention_mask"].tolist()[0] == [True, True, True, False, False]
    assert batch["input_ids"].shape == (2, 5)


def test_collator_preserves_long_dtype():
    batch = CausalLMCollator(context_length=5)([record([2, 3])])
    assert batch["input_ids"].dtype == torch.long
    assert batch["labels"].dtype == torch.long
    assert batch["attention_mask"].dtype == torch.bool


def test_empty_batch_is_rejected():
    with pytest.raises(TrainingError, match="EMPTY_BATCH"):
        CausalLMCollator(context_length=8)([])


@pytest.mark.parametrize("bad", [
    {"input_ids": torch.tensor([2, 3])},
    {"input_ids": torch.tensor([[2, 3]]), "labels": torch.tensor([[2, 3]])},
    {"input_ids": torch.tensor([2.0, 3.0]), "labels": torch.tensor([2.0, 3.0])},
    {"input_ids": torch.tensor([2, 3]), "labels": torch.tensor([2])},
])
def test_invalid_record_contract_is_rejected(bad):
    with pytest.raises(TrainingError):
        CausalLMCollator(context_length=8)([bad])


def test_context_overflow_is_rejected():
    with pytest.raises(TrainingError, match="context_length"):
        CausalLMCollator(context_length=2)([record([2, 10, 3])])
