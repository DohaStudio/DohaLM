from __future__ import annotations

import json
from pathlib import Path

from src.data.checksums import checksum_value
from src.data.tokenized_dataset import TokenizedJsonlDataset
from src.model import DohaLMTiny, ModelConfig
from src.runtime.paths import repository_root
from src.tokenizer import DohaTokenizer, TrainerConfig, train_smoke_tokenizer
from src.training import CausalLMCollator, PilotPretrainingConfig, Trainer, TrainingConfig, create_dataloader, run_pilot_pretraining


def _tokens(path, count=8):
    record = {"input_ids": [2, 8, 9, 10, 3, 0, 0, 0], "labels": [2, 8, 9, 10, 3, -100, -100, -100], "attention_mask": [1, 1, 1, 1, 1, 0, 0, 0]}
    path.write_text("".join(json.dumps(record) + "\n" for _ in range(count)), encoding="utf-8")


def test_actual_model_trainer_integration_runs_five_steps(tmp_path):
    path = tmp_path / "train.jsonl"
    _tokens(path)
    dataset = TokenizedJsonlDataset(path, context_length=8, vocab_size=32)
    config = TrainingConfig(batch_size=2, micro_batch_size=2, max_steps=5, learning_rate=0.01, save_every=5, output_dir="tests/output/pilot", seed=31)
    loader = create_dataloader(dataset, CausalLMCollator(context_length=8), config, stateful=True, dataset_fingerprint="sha256:dataset")
    model = DohaLMTiny(ModelConfig(vocab_size=32, context_length=8, num_layers=1, hidden_size=16, num_heads=4, head_dim=4, ffn_size=32))
    trainer = Trainer(model=model, dataloader=loader, config=config, dataset_fingerprint="sha256:dataset", tokenizer_fingerprint=checksum_value({"vocab": 32}), output_root=tmp_path / "run", dataset_metadata={"local_experiment_only": True, "publish_allowed": False})
    result = trainer.train()
    assert result.state.global_step == 5
    assert result.checkpoints == ("checkpoint-5",)
    assert all(metric.loss > 0 for metric in result.metrics)


def test_metrics_capture_throughput_memory_and_gradient(tmp_path):
    path = tmp_path / "train.jsonl"
    _tokens(path)
    dataset = TokenizedJsonlDataset(path, context_length=8, vocab_size=32)
    config = TrainingConfig(max_steps=1, save_every=1, output_dir="tests/output/pilot")
    loader = create_dataloader(dataset, CausalLMCollator(context_length=8), config)
    model = DohaLMTiny(ModelConfig(vocab_size=32, context_length=8, num_layers=1, hidden_size=16, num_heads=4, head_dim=4, ffn_size=32))
    trainer = Trainer(model=model, dataloader=loader, config=config, dataset_fingerprint="sha256:d", tokenizer_fingerprint="sha256:t", output_root=tmp_path / "run")
    metric = trainer.train().metrics[0]
    assert metric.tokens_per_second > 0 and metric.gradient_norm >= 0
    assert metric.peak_memory_allocated == metric.peak_memory_reserved == 0


def test_stage_a_full_orchestration_with_synthetic_sentencepiece(monkeypatch, tmp_path):
    corpus = Path("tests/fixtures/tokenizer/corpus.txt").resolve()
    tokenizer_root = tmp_path / "tokenizer"
    train_smoke_tokenizer(corpus, tokenizer_root, synthetic_root=corpus.parent, config=TrainerConfig(vocab_size=256))
    train_path, validation_path = tmp_path / "train.jsonl", tmp_path / "validation.jsonl"
    _tokens(train_path, count=8)
    _tokens(validation_path, count=2)
    corpus_manifest, split_manifest = tmp_path / "corpus-manifest.json", tmp_path / "split-manifest.json"
    corpus_manifest.write_text(json.dumps({"kind": "synthetic", "local_experiment_only": True}), encoding="utf-8")
    split_manifest.write_text(json.dumps({"packing": "synthetic-test"}), encoding="utf-8")
    root = repository_root()
    relative = lambda path: path.resolve().relative_to(root).as_posix()
    model_config = ModelConfig(vocab_size=256, context_length=8, num_layers=1, hidden_size=16, num_heads=4, head_dim=4, ffn_size=32)
    config = PilotPretrainingConfig(
        train_dataset=relative(train_path),
        validation_dataset=relative(validation_path),
        tokenizer_model=relative(tokenizer_root / "tokenizer.model"),
        corpus_manifest=relative(corpus_manifest),
        split_manifest=relative(split_manifest),
        output_dir=relative(tmp_path / "pilot-run"),
        micro_batch_size=2,
        gradient_accumulation_steps=1,
        max_steps=5,
        validation_every=1,
        save_every=5,
        learning_rate=0.01,
        warmup_steps=0,
        device="cpu",
        use_amp=False,
        pin_memory=False,
        max_new_tokens=2,
        model=model_config,
    )
    actual = DohaTokenizer(tokenizer_root / "tokenizer.model")
    monkeypatch.setattr("src.training.pilot_pretraining.validate_pilot_tokenizer", lambda _path: (actual, {"status": "synthetic-smoke"}))
    monkeypatch.setattr("src.training.pilot_pretraining._lineage", lambda _config: {
        "dataset_fingerprint": "sha256:" + "a" * 64,
        "tokenizer_fingerprint": "sha256:" + "b" * 64,
        "local_experiment_only": True,
        "publish_allowed": False,
        "redistribution_allowed": False,
        "model_release_allowed": False,
    })
    result = run_pilot_pretraining(config)
    assert result["global_step"] == 5
    assert len(result["validation"]) == 6
    assert result["generation_before"]["generated_token_count"] > 0
    assert result["generation_after"]["generated_token_count"] > 0
    assert result["checkpoint_sizes_bytes"]["checkpoint-5"] > 0
