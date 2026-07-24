from __future__ import annotations

import json

import pytest

from src.data.tokenized_dataset import TokenizedJsonlDataset
from src.model import DohaLMTiny, ModelConfig
from src.training import CausalLMCollator, Trainer, TrainingConfig, TrainingError, create_dataloader


def build(tmp_path, *, resume=False, dataset_fingerprint="sha256:dataset"):
    path = tmp_path / "tokens.jsonl"
    if not path.exists():
        record = {"input_ids": [2, 8, 9, 3], "labels": [2, 8, 9, 3], "attention_mask": [1, 1, 1, 1]}
        path.write_text("".join(json.dumps(record) + "\n" for _ in range(8)), encoding="utf-8")
    dataset = TokenizedJsonlDataset(path, context_length=4, vocab_size=32)
    config = TrainingConfig(max_steps=2, save_every=1, output_dir="tests/output/pilot-resume", seed=7)
    loader = create_dataloader(dataset, CausalLMCollator(context_length=4), config, stateful=True, dataset_fingerprint=dataset_fingerprint)
    model = DohaLMTiny(ModelConfig(vocab_size=32, context_length=4, num_layers=1, hidden_size=16, num_heads=4, head_dim=4, ffn_size=32))
    return Trainer(model=model, dataloader=loader, config=config, dataset_fingerprint=dataset_fingerprint, tokenizer_fingerprint="sha256:tokenizer", output_root=tmp_path / "run", resume=resume)


def test_resume_from_step_one_continues_to_step_two(tmp_path):
    first = build(tmp_path)
    first.train(target_steps=1)
    resumed = build(tmp_path, resume=True)
    resumed.resume_from(tmp_path / "run" / "checkpoint-1")
    assert resumed.train(target_steps=2).state.global_step == 2


def test_resume_blocks_dataset_lineage_change(tmp_path):
    first = build(tmp_path)
    first.train(target_steps=1)
    resumed = build(tmp_path, resume=True, dataset_fingerprint="sha256:changed")
    with pytest.raises(TrainingError, match="CHECKPOINT_DATASET_MISMATCH"):
        resumed.resume_from(tmp_path / "run" / "checkpoint-1")
