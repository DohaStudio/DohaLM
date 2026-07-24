from __future__ import annotations

import pytest
import torch

from src.training import CausalLMCollator, SyntheticTokenDataset, TrainingError, create_dataloader

from tests._training_helpers import repeated_dataset, training_config


def test_synthetic_dataset_is_deterministic():
    args = dict(vocab_size=32, sequence_length=7, num_records=4, seed=9)
    one, two = SyntheticTokenDataset(**args), SyntheticTokenDataset(**args)
    assert one.fingerprint == two.fingerprint
    assert all(torch.equal(one[index]["input_ids"], two[index]["input_ids"]) for index in range(4))


def test_synthetic_dataset_seed_changes_content_and_fingerprint():
    one = SyntheticTokenDataset(vocab_size=32, sequence_length=7, num_records=2, seed=1)
    two = SyntheticTokenDataset(vocab_size=32, sequence_length=7, num_records=2, seed=2)
    assert one.fingerprint != two.fingerprint
    assert not torch.equal(one[0]["input_ids"], two[0]["input_ids"])


def test_synthetic_records_have_bos_eos_labels_and_mask():
    record = SyntheticTokenDataset(vocab_size=32, sequence_length=5, num_records=1)[0]
    assert record["input_ids"][0].item() == 2 and record["input_ids"][-1].item() == 3
    assert torch.equal(record["input_ids"], record["labels"])
    assert record["attention_mask"].dtype == torch.bool and record["attention_mask"].all()


def test_repeated_pattern_is_exact_and_cloned():
    dataset = repeated_dataset()
    first = dataset[0]
    first["input_ids"][0] = 31
    assert dataset[1]["input_ids"].tolist() == [2, 10, 11, 12, 3]


def test_variable_length_records_are_bounded():
    dataset = SyntheticTokenDataset(
        vocab_size=32, sequence_length=8, num_records=20, seed=3, variable_lengths=True
    )
    lengths = {len(dataset[index]["input_ids"]) for index in range(len(dataset))}
    assert min(lengths) >= 2 and max(lengths) <= 8 and len(lengths) > 1


@pytest.mark.parametrize("kwargs,code", [
    ({"num_records": 0}, "EMPTY_DATASET"),
    ({"sequence_length": 1}, "INVALID_TRAINING_CONFIG"),
    ({"vocab_size": 8}, "INVALID_TRAINING_CONFIG"),
    ({"pattern": [2]}, "INVALID_TRAINING_CONFIG"),
    ({"pattern": [2, 99, 3]}, "INVALID_TRAINING_CONFIG"),
])
def test_invalid_synthetic_dataset(kwargs, code):
    values = dict(vocab_size=32, sequence_length=5, num_records=2)
    values.update(kwargs)
    with pytest.raises(TrainingError, match=code):
        SyntheticTokenDataset(**values)


def test_dataloader_same_seed_produces_same_first_batch():
    dataset = SyntheticTokenDataset(vocab_size=32, sequence_length=6, num_records=12, seed=4)
    collator = CausalLMCollator(context_length=8)
    config = training_config(seed=77)
    first = next(iter(create_dataloader(dataset, collator, config, shuffle=True)))
    second = next(iter(create_dataloader(dataset, collator, config, shuffle=True)))
    assert torch.equal(first["input_ids"], second["input_ids"])


def test_empty_dataloader_dataset_is_rejected():
    class Empty(torch.utils.data.Dataset):
        def __len__(self): return 0
        def __getitem__(self, index): raise IndexError

    with pytest.raises(TrainingError, match="EMPTY_DATASET"):
        create_dataloader(Empty(), CausalLMCollator(context_length=8), training_config())
