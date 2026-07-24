"""Deterministic fixed-length causal-LM sequence packing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Iterator


@dataclass(frozen=True)
class PackingPolicy:
    context_length: int = 256
    mode: str = "continuous"
    append_eos: bool = True
    remainder: str = "drop"
    eos_token_id: int = 3
    pad_token_id: int = 0
    ignore_index: int = -100

    def __post_init__(self) -> None:
        if self.context_length < 2:
            raise ValueError("context_length는 2 이상이어야 합니다.")
        if self.mode not in {"continuous", "record_boundary"}:
            raise ValueError("packing mode는 continuous 또는 record_boundary여야 합니다.")
        if self.remainder not in {"drop", "pad"}:
            raise ValueError("remainder는 drop 또는 pad여야 합니다.")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _finish(tokens: list[int], policy: PackingPolicy) -> dict[str, list[int]] | None:
    if len(tokens) < policy.context_length:
        if policy.remainder == "drop":
            return None
        pad_count = policy.context_length - len(tokens)
        return {
            "input_ids": tokens + [policy.pad_token_id] * pad_count,
            "labels": tokens + [policy.ignore_index] * pad_count,
            "attention_mask": [1] * len(tokens) + [0] * pad_count,
        }
    return {"input_ids": tokens, "labels": list(tokens), "attention_mask": [1] * len(tokens)}


def pack_sequences(records: Iterable[list[int]], policy: PackingPolicy) -> Iterator[dict[str, list[int]]]:
    buffer: list[int] = []
    for original in records:
        if not original or any(isinstance(token, bool) or not isinstance(token, int) or token < 0 for token in original):
            raise ValueError("record token은 비어 있지 않은 음이 아닌 정수 목록이어야 합니다.")
        tokens = list(original)
        if policy.append_eos and (not tokens or tokens[-1] != policy.eos_token_id):
            tokens.append(policy.eos_token_id)
        if policy.mode == "record_boundary":
            while len(tokens) >= policy.context_length:
                yield _finish(tokens[: policy.context_length], policy)  # type: ignore[misc]
                tokens = tokens[policy.context_length :]
            final = _finish(tokens, policy) if tokens else None
            if final is not None:
                yield final
            continue
        buffer.extend(tokens)
        while len(buffer) >= policy.context_length:
            chunk = buffer[: policy.context_length]
            del buffer[: policy.context_length]
            yield _finish(chunk, policy)  # type: ignore[misc]
    if policy.mode == "continuous" and buffer:
        final = _finish(buffer, policy)
        if final is not None:
            yield final
