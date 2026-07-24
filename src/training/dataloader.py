"""Deterministic DataLoader construction for synthetic training."""

from __future__ import annotations

import random
from collections.abc import Sized

import torch
from torch.utils.data import DataLoader, Dataset

from .collator import CausalLMCollator
from .config import TrainingConfig
from .errors import TrainingError
from .sampler_state import StatefulBatchSampler


def _seed_worker(worker_id: int) -> None:
    seed = torch.initial_seed() % (2**32)
    random.seed(seed + worker_id)


def create_dataloader(
    dataset: Dataset,
    collator: CausalLMCollator,
    config: TrainingConfig,
    *,
    shuffle: bool = True,
    stateful: bool = False,
    dataset_fingerprint: str | None = None,
) -> DataLoader:
    if not isinstance(dataset, Sized) or len(dataset) == 0:
        raise TrainingError("EMPTY_DATASET", "DataLoader 입력 dataset이 비어 있습니다.")
    if stateful:
        if not dataset_fingerprint:
            raise TrainingError("INVALID_TRAINING_CONFIG", "stateful DataLoader에는 dataset fingerprint가 필요합니다.")
        batch_sampler = StatefulBatchSampler(
            dataset_size=len(dataset),
            batch_size=config.micro_batch_size,
            seed=config.seed,
            dataset_fingerprint=dataset_fingerprint,
            drop_last=config.drop_last,
        )
        return DataLoader(
            dataset,
            batch_sampler=batch_sampler,
            collate_fn=collator,
            num_workers=config.num_workers,
            pin_memory=config.pin_memory,
            worker_init_fn=_seed_worker,
        )
    generator = torch.Generator()
    generator.manual_seed(config.seed)
    return DataLoader(
        dataset,
        batch_size=config.micro_batch_size,
        shuffle=shuffle,
        collate_fn=collator,
        num_workers=config.num_workers,
        pin_memory=config.pin_memory,
        drop_last=config.drop_last,
        generator=generator,
        worker_init_fn=_seed_worker,
    )
