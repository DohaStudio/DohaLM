"""Explicit deterministic sampler state for bounded resume validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterator

import torch
from torch.utils.data import Sampler

from src.data.checksums import checksum_value

from .errors import TrainingError


@dataclass
class SamplerState:
    epoch: int
    sample_offset: int
    permutation_seed: int
    permutation_fingerprint: str
    batches_yielded: int
    records_yielded: int
    dataset_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SamplerState":
        try:
            return cls(**value)
        except (TypeError, ValueError) as exc:
            raise TrainingError("RESUME_STATE_MISMATCH", "sampler state 형식이 유효하지 않습니다.") from exc


class StatefulBatchSampler(Sampler[list[int]]):
    """Yield deterministic shuffled batches while exposing the exact next offset."""

    def __init__(
        self,
        *,
        dataset_size: int,
        batch_size: int,
        seed: int,
        dataset_fingerprint: str,
        drop_last: bool = False,
    ) -> None:
        if dataset_size <= 0 or batch_size <= 0:
            raise TrainingError("EMPTY_DATASET", "stateful sampler 크기와 batch는 양수여야 합니다.")
        if seed < 0 or not dataset_fingerprint:
            raise TrainingError("INVALID_TRAINING_CONFIG", "sampler seed와 dataset fingerprint가 필요합니다.")
        self.dataset_size = dataset_size
        self.batch_size = batch_size
        self.seed = seed
        self.dataset_fingerprint = dataset_fingerprint
        self.drop_last = drop_last
        self.epoch = 0
        self.sample_offset = 0
        self.batches_yielded = 0
        self.records_yielded = 0

    def _permutation(self, epoch: int | None = None) -> list[int]:
        selected_epoch = self.epoch if epoch is None else epoch
        generator = torch.Generator().manual_seed(self.seed + selected_epoch)
        return torch.randperm(self.dataset_size, generator=generator).tolist()

    def _fingerprint(self, epoch: int | None = None) -> str:
        selected_epoch = self.epoch if epoch is None else epoch
        return checksum_value(
            {
                "dataset_fingerprint": self.dataset_fingerprint,
                "epoch": selected_epoch,
                "permutation_seed": self.seed,
                "permutation": self._permutation(selected_epoch),
            }
        )

    def __iter__(self) -> Iterator[list[int]]:
        if self.sample_offset >= self.dataset_size:
            self.epoch += 1
            self.sample_offset = 0
        permutation = self._permutation()
        while self.sample_offset < self.dataset_size:
            end = min(self.sample_offset + self.batch_size, self.dataset_size)
            batch = permutation[self.sample_offset:end]
            if len(batch) < self.batch_size and self.drop_last:
                self.sample_offset = self.dataset_size
                break
            self.sample_offset = end
            self.batches_yielded += 1
            self.records_yielded += len(batch)
            yield batch

    def __len__(self) -> int:
        remaining = max(0, self.dataset_size - self.sample_offset)
        if self.drop_last:
            return remaining // self.batch_size
        return (remaining + self.batch_size - 1) // self.batch_size

    def state(self) -> SamplerState:
        return SamplerState(
            epoch=self.epoch,
            sample_offset=self.sample_offset,
            permutation_seed=self.seed,
            permutation_fingerprint=self._fingerprint(),
            batches_yielded=self.batches_yielded,
            records_yielded=self.records_yielded,
            dataset_fingerprint=self.dataset_fingerprint,
        )

    def state_dict(self) -> dict[str, Any]:
        return self.state().to_dict()

    def load_state_dict(self, value: dict[str, Any]) -> None:
        state = SamplerState.from_dict(value)
        if state.dataset_fingerprint != self.dataset_fingerprint:
            raise TrainingError("CHECKPOINT_DATASET_MISMATCH", "sampler dataset fingerprint가 일치하지 않습니다.")
        if state.permutation_seed != self.seed:
            raise TrainingError("RESUME_STATE_MISMATCH", "sampler permutation seed가 일치하지 않습니다.")
        if state.epoch < 0 or not 0 <= state.sample_offset <= self.dataset_size:
            raise TrainingError("RESUME_STATE_MISMATCH", "sampler epoch 또는 offset이 유효하지 않습니다.")
        if state.batches_yielded < 0 or state.records_yielded < 0:
            raise TrainingError("RESUME_STATE_MISMATCH", "sampler 누적 count가 유효하지 않습니다.")
        if state.permutation_fingerprint != self._fingerprint(state.epoch):
            raise TrainingError("RESUME_STATE_MISMATCH", "sampler permutation fingerprint가 일치하지 않습니다.")
        self.epoch = state.epoch
        self.sample_offset = state.sample_offset
        self.batches_yielded = state.batches_yielded
        self.records_yielded = state.records_yielded
