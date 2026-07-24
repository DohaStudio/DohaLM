from __future__ import annotations

import json

import pytest
import torch

from src.data.tokenized_dataset import TokenizedJsonlDataset


def _write(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def test_lazy_token_dataset_returns_contract_tensors(tmp_path):
    path = tmp_path / "tokens.jsonl"
    _write(path, {"input_ids": [2, 8, 3, 0], "labels": [2, 8, 3, -100], "attention_mask": [1, 1, 1, 0]})
    dataset = TokenizedJsonlDataset(path, context_length=4, vocab_size=16)
    record = dataset[0]
    assert record["input_ids"].dtype == torch.long
    assert record["attention_mask"].dtype == torch.bool
    assert record["labels"].tolist()[-1] == -100


def test_token_dataset_rejects_out_of_range_token(tmp_path):
    path = tmp_path / "tokens.jsonl"
    _write(path, {"input_ids": [2, 99], "labels": [2, 99], "attention_mask": [1, 1]})
    dataset = TokenizedJsonlDataset(path, context_length=2, vocab_size=16)
    with pytest.raises(ValueError, match="vocabulary"):
        dataset[0]


def test_token_artifact_contains_no_raw_text_field(tmp_path):
    path = tmp_path / "tokens.jsonl"
    _write(path, {"input_ids": [2, 3], "labels": [2, 3], "attention_mask": [1, 1]})
    assert "text" not in path.read_text(encoding="utf-8")
