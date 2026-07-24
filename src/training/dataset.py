"""Deterministic synthetic token data for trainer verification only."""

from __future__ import annotations

import random
from collections.abc import Sequence

import torch
from torch import Tensor
from torch.utils.data import Dataset

from src.data.checksums import checksum_value

from .errors import TrainingError


class SyntheticTokenDataset(Dataset[dict[str, Tensor]]):
    def __init__(
        self,
        *,
        vocab_size: int,
        sequence_length: int,
        num_records: int,
        seed: int = 17,
        bos_token_id: int = 2,
        eos_token_id: int = 3,
        pattern: Sequence[int] | None = None,
        variable_lengths: bool = False,
    ):
        if num_records <= 0:
            raise TrainingError("EMPTY_DATASET", "synthetic dataset에는 최소 한 record가 필요합니다.")
        if vocab_size <= 8 or sequence_length < 2:
            raise TrainingError("INVALID_TRAINING_CONFIG", "vocab_size는 8보다 크고 sequence_length는 2 이상이어야 합니다.")
        if not 0 <= bos_token_id < vocab_size or not 0 <= eos_token_id < vocab_size:
            raise TrainingError("INVALID_TRAINING_CONFIG", "BOS/EOS ID가 vocabulary 범위를 벗어났습니다.")
        if pattern is not None:
            if len(pattern) < 2 or len(pattern) > sequence_length:
                raise TrainingError("INVALID_TRAINING_CONFIG", "반복 pattern 길이가 유효하지 않습니다.")
            if any(isinstance(token, bool) or not isinstance(token, int) or not 0 <= token < vocab_size for token in pattern):
                raise TrainingError("INVALID_TRAINING_CONFIG", "반복 pattern token이 vocabulary 범위를 벗어났습니다.")
        self.vocab_size = vocab_size
        self.sequence_length = sequence_length
        self.num_records = num_records
        self.seed = seed
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id
        self.pattern = tuple(pattern) if pattern is not None else None
        self.variable_lengths = variable_lengths
        self._records = self._build_records()
        self.fingerprint = checksum_value(
            {
                "kind": "synthetic-token-dataset-v1",
                "vocab_size": vocab_size,
                "sequence_length": sequence_length,
                "num_records": num_records,
                "seed": seed,
                "bos_token_id": bos_token_id,
                "eos_token_id": eos_token_id,
                "pattern": list(self.pattern) if self.pattern is not None else None,
                "variable_lengths": variable_lengths,
            }
        )

    def _build_records(self) -> list[Tensor]:
        if self.pattern is not None:
            return [torch.tensor(self.pattern, dtype=torch.long) for _ in range(self.num_records)]
        rng = random.Random(self.seed)
        records: list[Tensor] = []
        for _ in range(self.num_records):
            length = self.sequence_length
            if self.variable_lengths and self.sequence_length > 2:
                length = rng.randint(2, self.sequence_length)
            interior = [rng.randrange(8, self.vocab_size) for _ in range(max(0, length - 2))]
            records.append(torch.tensor([self.bos_token_id, *interior, self.eos_token_id], dtype=torch.long))
        return records

    def __len__(self) -> int:
        return self.num_records

    def __getitem__(self, index: int) -> dict[str, Tensor]:
        ids = self._records[index].clone()
        return {
            "input_ids": ids,
            "labels": ids.clone(),
            "attention_mask": torch.ones(ids.shape, dtype=torch.bool),
        }
