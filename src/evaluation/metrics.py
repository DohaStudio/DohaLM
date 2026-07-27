"""Pure numeric evaluation metrics; no decoded text is retained."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Iterable, Sequence

from src.tokenizer.tokenizer import SPECIAL_TOKEN_IDS


def safe_perplexity(loss: float) -> dict[str, float | bool | None]:
    finite = math.isfinite(loss)
    overflow = finite and loss > math.log(float.fromhex("0x1.fffffffffffffp+1023"))
    value = math.exp(loss) if finite and not overflow else None
    return {"loss": loss, "log_perplexity": loss, "perplexity": value, "perplexity_overflow": overflow, "finite_perplexity": value is not None and math.isfinite(value)}


def quantiles(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {key: None for key in ("minimum", "p10", "p25", "median", "mean", "p75", "p90", "p95", "p99", "maximum")}
    ordered = sorted(values)
    def percentile(value: float) -> float:
        position = (len(ordered) - 1) * value
        lower, upper = math.floor(position), math.ceil(position)
        return ordered[lower] if lower == upper else ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return {
        "minimum": ordered[0], "p10": percentile(.10), "p25": percentile(.25),
        "median": statistics.median(ordered), "mean": statistics.fmean(ordered),
        "p75": percentile(.75), "p90": percentile(.90), "p95": percentile(.95),
        "p99": percentile(.99), "maximum": ordered[-1],
    }


def token_category(piece: str, token_id: int) -> str:
    if token_id in SPECIAL_TOKEN_IDS.values():
        return "eos" if token_id == SPECIAL_TOKEN_IDS["<eos>"] else "special"
    cleaned = piece.replace("▁", "")
    if piece.startswith("<0x") and piece.endswith(">"):
        return "byte_fallback"
    if cleaned and all("가" <= char <= "힣" or "ㄱ" <= char <= "ㅎ" or "ㅏ" <= char <= "ㅣ" for char in cleaned):
        return "korean"
    if cleaned and all(char.isascii() and char.isalpha() for char in cleaned):
        return "english"
    if cleaned and all(char.isdigit() for char in cleaned):
        return "number"
    if cleaned and all(not char.isalnum() and not char.isspace() for char in cleaned):
        return "symbol"
    return "unclassified"


def generation_statistics(tokens: Sequence[int], *, eos_id: int, unk_id: int, special_ids: set[int], byte_ids: set[int]) -> dict[str, float | int | bool | str]:
    count = len(tokens)
    pairs = list(zip(tokens, tokens[1:]))
    repeated_adjacent = sum(left == right for left, right in pairs)
    ngrams = {}
    for n in (1, 2, 3):
        grams = [tuple(tokens[i:i+n]) for i in range(max(0, count - n + 1))]
        ngrams[n] = len(set(grams)) / len(grams) if grams else 0.0
    four = [tuple(tokens[i:i+4]) for i in range(max(0, count - 3))]
    repeated_four = sum(amount - 1 for amount in Counter(four).values() if amount > 1)
    return {
        "token_hash": __import__("hashlib").sha256(",".join(map(str, tokens)).encode()).hexdigest(),
        "length": count, "eos_reached": eos_id in tokens, "maximum_length_reached": count > 0,
        "empty": count == 0, "unique_token_ratio": len(set(tokens)) / count if count else 0.0,
        "adjacent_repetition_rate": repeated_adjacent / len(pairs) if pairs else 0.0,
        "repeated_4gram_rate": repeated_four / len(four) if four else 0.0,
        "distinct_1": ngrams[1], "distinct_2": ngrams[2], "distinct_3": ngrams[3],
        "degenerate_loop": repeated_four >= 2, "special_token_rate": sum(t in special_ids for t in tokens) / count if count else 0.0,
        "unk_rate": sum(t == unk_id for t in tokens) / count if count else 0.0,
        "byte_fallback_rate": sum(t in byte_ids for t in tokens) / count if count else 0.0,
    }


def prefix_metrics(predicted: Sequence[int], expected: Sequence[int]) -> dict[str, float | int | bool]:
    length = min(len(predicted), len(expected))
    matches = [predicted[index] == expected[index] for index in range(length)]
    prefix = 0
    for match in matches:
        if not match:
            break
        prefix += 1
    return {
        "first_token_accuracy": float(bool(matches and matches[0])),
        "first_4_accuracy": sum(matches[:4]) / min(4, length) if length else 0.0,
        "first_8_accuracy": sum(matches[:8]) / min(8, length) if length else 0.0,
        "first_16_accuracy": sum(matches[:16]) / min(16, length) if length else 0.0,
        "prefix_match_length": prefix, "exact_continuation": len(predicted) == len(expected) and all(matches),
        "autoregressive_token_match": sum(matches) / length if length else 0.0,
    }
