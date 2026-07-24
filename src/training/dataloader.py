"""Deterministic DataLoader construction for synthetic training."""

from __future__ import annotations

import random
from collections.abc import Sized

import torch
from torch.utils.data import DataLoader, Dataset

from .collator import CausalLMCollator
from .config import TrainingConfig
from .errors import TrainingError


def _seed_worker(worker_id: int) -> None:
    seed = torch.initial_seed() % (2**32)
    random.seed(seed + worker_id)


def create_dataloader(
    dataset: Dataset,
    collator: CausalLMCollator,
    config: TrainingConfig,
    *,
    shuffle: bool = True,
) -> DataLoader:
    if not isinstance(dataset, Sized) or len(dataset) == 0:
        raise TrainingError("EMPTY_DATASET", "DataLoader 입력 dataset이 비어 있습니다.")
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
