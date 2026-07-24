"""Lazy JSONL token dataset containing no raw corpus text."""

from __future__ import annotations

import json
from pathlib import Path

import torch
from torch import Tensor
from torch.utils.data import Dataset


class TokenizedJsonlDataset(Dataset[dict[str, Tensor]]):
    def __init__(self, path: str | Path, *, context_length: int, vocab_size: int):
        self.path = Path(path)
        if not self.path.is_file():
            raise ValueError("tokenized JSONL 파일이 없습니다.")
        self.context_length = context_length
        self.vocab_size = vocab_size
        self._offsets: list[int] = []
        with self.path.open("rb") as handle:
            while True:
                offset = handle.tell()
                line = handle.readline()
                if not line:
                    break
                if line.strip():
                    self._offsets.append(offset)
        if not self._offsets:
            raise ValueError("tokenized dataset이 비어 있습니다.")

    def __len__(self) -> int:
        return len(self._offsets)

    def __getitem__(self, index: int) -> dict[str, Tensor]:
        with self.path.open("rb") as handle:
            handle.seek(self._offsets[index])
            try:
                value = json.loads(handle.readline().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("tokenized JSONL record가 유효하지 않습니다.") from exc
        required = {"input_ids", "labels", "attention_mask"}
        if not isinstance(value, dict) or set(value) != required:
            raise ValueError("tokenized record field 계약이 일치하지 않습니다.")
        ids, labels, mask = value["input_ids"], value["labels"], value["attention_mask"]
        if not all(isinstance(item, list) for item in (ids, labels, mask)):
            raise ValueError("tokenized record 값은 목록이어야 합니다.")
        if not (len(ids) == len(labels) == len(mask) == self.context_length):
            raise ValueError("tokenized record 길이가 context_length와 다릅니다.")
        if any(isinstance(token, bool) or not isinstance(token, int) or not 0 <= token < self.vocab_size for token in ids):
            raise ValueError("input token이 vocabulary 범위를 벗어났습니다.")
        if any(isinstance(token, bool) or not isinstance(token, int) or (token != -100 and not 0 <= token < self.vocab_size) for token in labels):
            raise ValueError("label token이 허용 범위를 벗어났습니다.")
        if any(item not in (0, 1, False, True) for item in mask):
            raise ValueError("attention_mask는 boolean 값이어야 합니다.")
        return {
            "input_ids": torch.tensor(ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(mask, dtype=torch.bool),
        }
