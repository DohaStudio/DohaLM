"""Deterministic evaluation subset selection without copying token records."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from torch.utils.data import Dataset

from src.data.checksums import checksum_value


def deterministic_indices(total: int, maximum: int, *, seed: int, dataset_fingerprint: str) -> list[int]:
    if total <= 0 or maximum <= 0:
        raise ValueError("dataset and subset sizes must be positive")
    ranked = []
    for index in range(total):
        key = f"{dataset_fingerprint}\0{seed}\0{index}".encode("utf-8")
        ranked.append((hashlib.sha256(key).digest(), index))
    return sorted(index for _, index in sorted(ranked)[: min(total, maximum)])


@dataclass(frozen=True)
class IndexedSubset(Dataset):
    dataset: Dataset
    indices: tuple[int, ...]

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, index: int) -> Any:
        return self.dataset[self.indices[index]]

    @property
    def manifest(self) -> dict[str, Any]:
        index_fingerprint = checksum_value(list(self.indices))
        return {
            "selection": "sha256_rank_v1", "selected_sequences": len(self.indices),
            "index_fingerprint": index_fingerprint, "raw_text_stored": False, "token_ids_stored": False,
        }
