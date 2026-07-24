from __future__ import annotations

import pytest

from src.training import StatefulBatchSampler, TrainingError


def sampler(*, seed: int = 17, fingerprint: str = "dataset-a") -> StatefulBatchSampler:
    return StatefulBatchSampler(dataset_size=10, batch_size=3, seed=seed, dataset_fingerprint=fingerprint)


def test_sampler_state_round_trip_preserves_next_batch() -> None:
    original = sampler()
    next(iter(original))
    state = original.state_dict()
    expected = next(iter(original))
    restored = sampler()
    restored.load_state_dict(state)
    assert next(iter(restored)) == expected


def test_sampler_state_records_required_fields() -> None:
    value = sampler().state_dict()
    assert set(value) == {
        "epoch", "sample_offset", "permutation_seed", "permutation_fingerprint",
        "batches_yielded", "records_yielded", "dataset_fingerprint",
    }


def test_sampler_updates_batch_and_record_counts_before_yield() -> None:
    value = sampler()
    batch = next(iter(value))
    assert value.state().batches_yielded == 1
    assert value.state().records_yielded == len(batch)


def test_sampler_rejects_dataset_mismatch() -> None:
    state = sampler().state_dict()
    with pytest.raises(TrainingError, match="dataset fingerprint"):
        sampler(fingerprint="dataset-b").load_state_dict(state)


def test_sampler_rejects_seed_mismatch() -> None:
    state = sampler().state_dict()
    with pytest.raises(TrainingError, match="seed"):
        sampler(seed=18).load_state_dict(state)


def test_sampler_rejects_permutation_fingerprint_tamper() -> None:
    state = sampler().state_dict()
    state["permutation_fingerprint"] = "tampered"
    with pytest.raises(TrainingError, match="permutation fingerprint"):
        sampler().load_state_dict(state)


def test_sampler_data_loader_recreation_is_deterministic() -> None:
    left = sampler()
    right = sampler()
    assert list(left) == list(right)


def test_sampler_advances_epoch_after_exhaustion() -> None:
    value = sampler()
    list(value)
    first = value.state_dict()
    next(iter(value))
    assert value.epoch == first["epoch"] + 1
    assert value.state().permutation_fingerprint != first["permutation_fingerprint"]
