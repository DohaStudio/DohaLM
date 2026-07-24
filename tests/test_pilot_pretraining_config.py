from __future__ import annotations

import pytest

from src.model import ModelConfig
from src.training import PilotPretrainingConfig, TrainingError


def config(**changes):
    values = dict(
        train_dataset="data/tokenized/pilot/train.jsonl",
        validation_dataset="data/tokenized/pilot/validation.jsonl",
        tokenizer_model="artifacts/tokenizer/tokenizer.model",
        corpus_manifest="data/tokenized/pilot/corpus-manifest.json",
        split_manifest="data/tokenized/pilot/split-manifest.json",
        model=ModelConfig(vocab_size=32, context_length=8, num_layers=1, hidden_size=16, num_heads=4, head_dim=4, ffn_size=32),
    )
    values.update(changes)
    return PilotPretrainingConfig(**values)


def test_candidate_b_defaults_are_bounded():
    value = config()
    assert value.micro_batch_size == 2
    assert value.gradient_accumulation_steps == 4
    assert value.effective_batch_size == 8
    assert value.max_steps == 100 and value.validation_every == 10 and value.save_every == 25
    assert value.to_training_config().scheduler_type == "cosine"


def test_more_than_100_steps_is_blocked():
    with pytest.raises(TrainingError, match="PILOT_STEP_LIMIT"):
        config(max_steps=101)


@pytest.mark.parametrize("changes", [{"local_experiment_only": False}, {"publish_allowed": True}, {"redistribution_allowed": True}, {"model_release_allowed": True}])
def test_non_local_or_publishable_configuration_is_blocked(changes):
    with pytest.raises(TrainingError, match="PILOT_LOCAL_ONLY_VIOLATION"):
        config(**changes)


def test_smoke_is_at_most_five_steps():
    value = config().smoke()
    assert value.max_steps == value.validation_every == value.save_every == 5
