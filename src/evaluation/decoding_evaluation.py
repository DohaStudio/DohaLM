"""Deterministic decoding-grid metrics for DohaLM v0.1 evaluation only."""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from src.data.checksums import checksum_value
from src.evaluation.qlora_sft import (
    PII_PATTERNS,
    PromptRecord,
    QLoRAEvaluationError,
    _canonical_hash,
    _character_f1,
    _model_device,
    _normalized_text,
    _rouge_l,
)


BASELINE = {
    "character_f1": 0.4105867990028522,
    "rouge_l": 0.2725672754797666,
}
TERMINATION_REASONS = (
    "eos_token", "max_new_tokens", "other_stopping_criteria", "generation_error", "empty_output",
)


@dataclass(frozen=True, order=True)
class DecodingPreset:
    max_new_tokens: int
    repetition_penalty: float
    no_repeat_ngram_size: int

    @property
    def preset_id(self) -> str:
        penalty = f"{self.repetition_penalty:.2f}".replace(".", "p")
        return f"m{self.max_new_tokens}-r{penalty}-n{self.no_repeat_ngram_size}"


def validate_decoding_config(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "status", "evaluation_id", "git_head", "training_run_id", "model", "dataset", "baseline", "prompts", "grid", "targets", "execution"}
    if set(value) != required or value.get("schema_version") != 1:
        raise QLoRAEvaluationError("DECODING_CONFIG_INVALID")
    model = value.get("model")
    prompts = value.get("prompts")
    grid = value.get("grid")
    execution = value.get("execution")
    if not all(isinstance(item, Mapping) for item in (model, prompts, grid, execution)):
        raise QLoRAEvaluationError("DECODING_CONFIG_INVALID")
    assert isinstance(model, Mapping) and isinstance(prompts, Mapping)
    assert isinstance(grid, Mapping) and isinstance(execution, Mapping)
    if (
        model.get("candidates") != ["checkpoint-1750", "final-adapter"]
        or prompts.get("total") != 80
        or prompts.get("synthetic") != 30
        or prompts.get("held_out_validation") != 50
        or grid.get("max_new_tokens") != [64, 96, 128, 192, 256]
        or grid.get("repetition_penalty") != [1.0, 1.05, 1.1, 1.15, 1.2]
        or grid.get("no_repeat_ngram_size") != [0, 3, 4, 5]
        or grid.get("deterministic_repeats") != 2
        or grid.get("seed") != 42
        or execution != {
            "training_allowed": False,
            "optimizer_allowed": False,
            "adapter_write_allowed": False,
            "overwrite_allowed": False,
        }
    ):
        raise QLoRAEvaluationError("DECODING_CONFIG_INVALID")
    return dict(value)


def validate_eos_contract(tokenizer: Any, model: Any) -> dict[str, Any]:
    tokenizer_eos = int(tokenizer.eos_token_id)
    tokenizer_pad = int(tokenizer.pad_token_id)
    model_eos = getattr(model.generation_config, "eos_token_id", None)
    model_pad = getattr(model.generation_config, "pad_token_id", None)
    config_eos = getattr(model.config, "eos_token_id", None)
    expected_eos = 151645
    expected_pad = 151643
    eos_values = model_eos if isinstance(model_eos, list) else [model_eos]
    if tokenizer_eos != expected_eos or expected_eos not in eos_values or config_eos != expected_eos:
        raise QLoRAEvaluationError("EOS_ID_MISMATCH")
    if tokenizer_pad != expected_pad or model_pad not in (None, expected_pad):
        raise QLoRAEvaluationError("PAD_ID_MISMATCH")
    return {
        "tokenizer_eos_token_id": tokenizer_eos,
        "tokenizer_pad_token_id": tokenizer_pad,
        "model_config_eos_token_id": config_eos,
        "generation_config_eos_token_id": model_eos,
        "generation_config_pad_token_id": model_pad,
        "explicit_override_eos_token_id": expected_eos,
        "explicit_override_pad_token_id": expected_pad,
        "override_consistent": True,
    }


def termination_reason(tokens: Sequence[int], *, eos_token_id: int, max_new_tokens: int) -> str:
    if not tokens:
        return "empty_output"
    if int(tokens[-1]) == eos_token_id:
        return "eos_token"
    if len(tokens) >= max_new_tokens:
        return "max_new_tokens"
    return "other_stopping_criteria"


def _repeated_ngram(tokens: Sequence[int], size: int, minimum_count: int = 3) -> bool:
    if len(tokens) < size:
        return False
    grams = Counter(tuple(tokens[index:index + size]) for index in range(len(tokens) - size + 1))
    return any(count >= minimum_count for count in grams.values())


def _consecutive_phrase_loop(tokens: Sequence[int]) -> bool:
    for size in range(3, min(13, len(tokens) // 2 + 1)):
        for index in range(len(tokens) - 2 * size + 1):
            if tokens[index:index + size] == tokens[index + size:index + 2 * size]:
                return True
    return False


def repetition_signals(text: str, tokens: Sequence[int]) -> dict[str, bool]:
    normalized = _normalized_text(text)
    words = re.findall(r"[\w가-힣]+", normalized, flags=re.UNICODE)
    sentences = [
        segment.strip() for segment in re.split(r"(?<=[.!?。！？])|\n+", normalized) if segment.strip()
    ]
    character = bool(re.search(r"([^\s])\1{4,}", normalized))
    word = any(count >= 3 for count in Counter(words).values()) if words else False
    sentence = any(count >= 2 for count in Counter(sentences).values()) if sentences else False
    trigram = _repeated_ngram(tokens, 3)
    fourgram = _repeated_ngram(tokens, 4)
    consecutive = _consecutive_phrase_loop(tokens)
    long_loop = _repeated_ngram(tokens, 4, minimum_count=4) or consecutive
    return {
        "character_repetition": character,
        "word_repetition": word,
        "sentence_repetition": sentence,
        "three_gram_repetition": trigram,
        "four_gram_repetition": fourgram,
        "consecutive_phrase_repetition": consecutive,
        "ngram_repetition": trigram or fourgram,
        "long_loop": long_loop,
        "repetition_any": character or word or sentence or trigram or fourgram or consecutive,
        "legacy_repetition": fourgram,
    }


def automatic_incomplete(text: str, reason: str) -> dict[str, Any]:
    normalized = text.strip()
    terminal = bool(re.search(r"(?:[.!?。！？]|다\.|요\.|니다\.)\s*$", normalized))
    max_length = reason == "max_new_tokens"
    empty = reason == "empty_output"
    return {
        "max_length_truncation": max_length,
        "missing_terminal_punctuation": bool(normalized) and not terminal,
        "automatic_incomplete": empty or max_length or (bool(normalized) and not terminal),
        "semantic_incomplete": "not_assessed_without_approved_judge",
        "reference_mismatch": "reported_separately_not_incomplete",
    }


def _percentile(values: Sequence[int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def summarize_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    if not values:
        raise QLoRAEvaluationError("EMPTY_DECODING_RESULT")
    count = len(values)
    token_counts = [int(row["output_token_count"]) for row in values]
    character_counts = [int(row["output_character_count"]) for row in values]
    reasons = Counter(str(row["termination_reason"]) for row in values)
    return {
        "samples": count,
        "character_f1": sum(float(row["character_f1"]) for row in values) / count,
        "rouge_l": sum(float(row["rouge_l"]) for row in values) / count,
        "exact_match": sum(bool(row["exact_match"]) for row in values) / count,
        "eos_terminated": reasons["eos_token"],
        "max_length_terminated": reasons["max_new_tokens"],
        "other_terminated": reasons["other_stopping_criteria"],
        "errors": reasons["generation_error"],
        "empty_output": reasons["empty_output"],
        "repetition_any": sum(bool(row["repetition_any"]) for row in values),
        "legacy_repetition": sum(bool(row["legacy_repetition"]) for row in values),
        "sentence_repetition": sum(bool(row["sentence_repetition"]) for row in values),
        "ngram_repetition": sum(bool(row["ngram_repetition"]) for row in values),
        "long_loop": sum(bool(row["long_loop"]) for row in values),
        "automatic_incomplete": sum(bool(row["automatic_incomplete"]) for row in values),
        "missing_terminal_punctuation": sum(bool(row["missing_terminal_punctuation"]) for row in values),
        "special_token_exposure": sum(bool(row["special_token_exposure"]) for row in values),
        "prompt_echo": sum(bool(row["prompt_echo"]) for row in values),
        "pii_like": sum(bool(row["pii_like"]) for row in values),
        "average_output_characters": sum(character_counts) / count,
        "average_generated_tokens": sum(token_counts) / count,
        "output_tokens_p50": _percentile(token_counts, 0.50),
        "output_tokens_p90": _percentile(token_counts, 0.90),
        "output_tokens_p95": _percentile(token_counts, 0.95),
    }


def evaluate_decoding(
    model: Any, tokenizer: Any, prompts: Sequence[PromptRecord], preset: DecodingPreset,
    *, train_output_hashes: set[str],
) -> dict[str, Any]:
    import torch

    rows: list[dict[str, Any]] = []
    device = _model_device(model)
    special_tokens = [token for token in tokenizer.all_special_tokens if token]
    started = time.perf_counter()
    for record in prompts:
        ids = tokenizer.apply_chat_template(
            [{"role": "user", "content": record.prompt}], tokenize=True,
            add_generation_prompt=True, return_tensors="pt",
        ).to(device)
        try:
            with torch.inference_mode(), torch.autocast(
                device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda",
            ):
                generated = model.generate(
                    ids, do_sample=False, num_beams=1,
                    max_new_tokens=preset.max_new_tokens,
                    repetition_penalty=preset.repetition_penalty,
                    no_repeat_ngram_size=preset.no_repeat_ngram_size,
                    pad_token_id=151643, eos_token_id=151645, use_cache=True,
                )
        except (RuntimeError, ValueError, TypeError) as exc:
            raise QLoRAEvaluationError("GENERATION_ERROR") from exc
        tokens = generated[0, ids.shape[1]:].tolist()
        if 151645 in tokens[:-1]:
            raise QLoRAEvaluationError("EOS_CONTINUATION_BUG")
        reason = termination_reason(tokens, eos_token_id=151645, max_new_tokens=preset.max_new_tokens)
        text = tokenizer.decode(tokens, skip_special_tokens=True).strip()
        raw = tokenizer.decode(tokens, skip_special_tokens=False)
        normalized = _normalized_text(text)
        reference = _normalized_text(record.reference)
        signals = repetition_signals(text, tokens)
        incomplete = automatic_incomplete(text, reason)
        rows.append({
            "sample_hash": record.sample_hash,
            "kind": record.kind,
            "category": record.category,
            "length_bucket": record.length_bucket,
            "exact_match": normalized == reference,
            "character_f1": _character_f1(text, record.reference),
            "rouge_l": _rouge_l(text, record.reference),
            "termination_reason": reason,
            "output_token_count": len(tokens),
            "output_character_count": len(text),
            "output_hash": _canonical_hash(normalized),
            "generated_token_fingerprint": hashlib.sha256(bytes(str(tokens), "ascii")).hexdigest(),
            "special_token_exposure": any(
                token in raw.removesuffix(tokenizer.eos_token or "") for token in special_tokens
            ),
            "prompt_echo": bool(normalized and _normalized_text(record.prompt) in normalized),
            "pii_like": any(pattern.search(text) for pattern in PII_PATTERNS),
            "memorization_suspicion": _canonical_hash(normalized) in train_output_hashes,
            **signals,
            **incomplete,
        })
    summary = summarize_rows(rows)
    fingerprint_payload = {
        "preset": asdict(preset),
        "rows": [{key: value for key, value in row.items() if key not in {"elapsed_seconds"}} for row in rows],
        "summary": summary,
    }
    return {
        "preset": asdict(preset),
        "preset_id": preset.preset_id,
        "summary": summary,
        "rows": rows,
        "metric_fingerprint": checksum_value(fingerprint_payload),
        "termination_reason_fingerprint": checksum_value([
            {"sample_hash": row["sample_hash"], "reason": row["termination_reason"]} for row in rows
        ]),
        "generated_token_fingerprint": checksum_value([
            {"sample_hash": row["sample_hash"], "fingerprint": row["generated_token_fingerprint"]} for row in rows
        ]),
        "elapsed_seconds": time.perf_counter() - started,
        "raw_text_stored": False,
        "token_ids_stored": False,
    }


def score_result(summary: Mapping[str, Any], *, baseline: Mapping[str, float] = BASELINE) -> dict[str, Any]:
    count = int(summary["samples"])
    eos_rate = int(summary["eos_terminated"]) / count
    max_rate = int(summary["max_length_terminated"]) / count
    repetition_rate = int(summary["repetition_any"]) / count
    incomplete_rate = int(summary["automatic_incomplete"]) / count
    quality_score = (
        0.45 * float(summary["character_f1"])
        + 0.25 * float(summary["rouge_l"])
        + 0.15 * eos_rate
        - 0.10 * repetition_rate
        - 0.05 * incomplete_rate
    )
    blockers = {
        "character_f1_below_base": float(summary["character_f1"]) <= baseline["character_f1"],
        "rouge_l_below_base": float(summary["rouge_l"]) <= baseline["rouge_l"],
        "special_token_exposure": int(summary["special_token_exposure"]) > 0,
        "empty_output": int(summary["empty_output"]) > 0,
        "repetition_over_50_percent": repetition_rate > 0.50,
    }
    early_pruning = {
        "character_f1_below_base": blockers["character_f1_below_base"],
        "rouge_l_below_base": blockers["rouge_l_below_base"],
        "special_token_exposure": blockers["special_token_exposure"],
        "empty_output": blockers["empty_output"],
        "repetition_over_80_percent": repetition_rate > 0.80,
        "max_length_over_80_percent": max_rate > 0.80,
    }
    return {
        "quality_score": quality_score,
        "eos_termination_rate": eos_rate,
        "max_length_hit_rate": max_rate,
        "repetition_rate": repetition_rate,
        "incomplete_rate": incomplete_rate,
        "hard_blockers": blockers,
        "hard_blocked": any(blockers.values()),
        "early_pruning": early_pruning,
        "advance_allowed": not any(early_pruning.values()),
    }


def compact_result(model_name: str, result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model": model_name,
        "preset": result["preset"],
        "preset_id": result["preset_id"],
        "summary": result["summary"],
        "score": score_result(result["summary"]),
        "metric_fingerprint": result["metric_fingerprint"],
        "termination_reason_fingerprint": result["termination_reason_fingerprint"],
        "generated_token_fingerprint": result["generated_token_fingerprint"],
        "elapsed_seconds": result["elapsed_seconds"],
    }


def rank_candidates(values: Sequence[Mapping[str, Any]], limit: int) -> list[dict[str, Any]]:
    viable = [dict(value) for value in values if bool(value["score"]["advance_allowed"])]
    viable.sort(key=lambda item: (-float(item["score"]["quality_score"]), str(item["model"]), str(item["preset_id"])))
    return viable[:limit]


def select_diverse_candidates(values: Sequence[Mapping[str, Any]], limit: int) -> list[dict[str, Any]]:
    ranked = rank_candidates(values, len(values))
    selected: list[dict[str, Any]] = []
    for model in ("checkpoint-1750", "final-adapter"):
        match = next((item for item in ranked if item["model"] == model), None)
        if match is not None:
            selected.append(match)
    for item in ranked:
        if len(selected) >= limit:
            break
        identity = (item["model"], item["preset_id"])
        if all((existing["model"], existing["preset_id"]) != identity for existing in selected):
            selected.append(item)
    selected.sort(key=lambda item: -float(item["score"]["quality_score"]))
    return selected[:limit]


def deployment_verdict(summary: Mapping[str, Any], *, deterministic: bool) -> dict[str, Any]:
    score = score_result(summary)
    quality = (
        float(summary["character_f1"]) > BASELINE["character_f1"]
        and float(summary["rouge_l"]) > BASELINE["rouge_l"]
    )
    pass_contract = (
        quality and float(summary["character_f1"]) >= 0.46
        and float(summary["rouge_l"]) >= 0.30
        and score["eos_termination_rate"] >= 0.80
        and score["repetition_rate"] <= 0.15
        and score["max_length_hit_rate"] <= 0.10
        and score["incomplete_rate"] <= 0.15
        and deterministic and not score["hard_blocked"]
    )
    conditional = (
        quality and score["eos_termination_rate"] >= 0.70
        and score["repetition_rate"] <= 0.30
        and score["max_length_hit_rate"] <= 0.20
        and score["incomplete_rate"] <= 0.25
        and deterministic and not score["hard_blocked"]
    )
    if pass_contract:
        verdict = "PASS"
    elif conditional:
        verdict = "CONDITIONAL_PASS"
    elif quality and deterministic:
        verdict = "NEEDS_MODEL_IMPROVEMENT"
    else:
        verdict = "FAIL"
    return {
        "verdict": verdict,
        "deployment_ready": verdict == "PASS",
        "quality_above_base": quality,
        "deterministic": deterministic,
        "score": score,
        "v0_2_data_or_training_improvement_recommended": (
            score["eos_termination_rate"] < 0.70
            or score["repetition_rate"] > 0.30
            or score["incomplete_rate"] > 0.25
        ),
    }
