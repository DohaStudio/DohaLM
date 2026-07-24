"""Synthetic smoke corpus tokenizer 통계."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .tokenizer import DohaTokenizer


def collect_statistics(
    tokenizer: DohaTokenizer,
    records: Iterable[str],
    *,
    character_coverage: float,
    byte_fallback: bool,
) -> dict[str, Any]:
    rows = list(records)
    token_counts: list[int] = []
    total_characters = 0
    unknown_count = 0
    piece_usage: Counter[int] = Counter()
    for text in rows:
        encoded = tokenizer.encode(text)
        token_counts.append(len(encoded.ids))
        total_characters += len(text)
        unknown_count += sum(token_id == tokenizer.unk_id for token_id in encoded.ids)
        piece_usage.update(encoded.ids)
    total_tokens = sum(token_counts)
    return {
        "schema_version": "1.0",
        "artifact_kind": "synthetic_tokenizer_smoke_statistics",
        "record_count": len(rows),
        "total_characters": total_characters,
        "total_tokens": total_tokens,
        "average_tokens_per_record": total_tokens / len(rows) if rows else 0.0,
        "average_characters_per_token": total_characters / total_tokens if total_tokens else 0.0,
        "unknown_token_count": unknown_count,
        "unknown_token_ratio": unknown_count / total_tokens if total_tokens else 0.0,
        "character_coverage": character_coverage,
        "byte_fallback": byte_fallback,
        "used_vocab_count": len(piece_usage),
        "vocab_usage_ratio": len(piece_usage) / tokenizer.vocab_size,
        "approval_effect": "none",
    }
