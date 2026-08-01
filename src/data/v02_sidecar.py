"""Deterministic, text-free quality sidecar and sampling package for DohaLM v0.2."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import statistics
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from difflib import SequenceMatcher
from itertools import pairwise
from pathlib import Path

import yaml

from src.data.artifacts import (
    AtomicArtifactDirectory,
    _fsync_directory,
    write_json,
    write_jsonl,
    write_yaml,
)
from src.data.checksums import canonical_json_bytes, checksum_value, file_checksum
from src.data.processing.aihub_71748_processor import join_source_records
from src.data.processing.aihub_71748_reader import (
    discover_sft_sources,
    iter_source_records,
)

SIDECAR_SCHEMA_VERSION = 1
DATASET_VERSION = "v0.2-sidecar"
PACKAGE_FILES = (
    "manifest.yaml",
    "quality-sidecar.jsonl",
    "review-queue.jsonl",
    "sampling-policy.yaml",
    "statistics.json",
    "train.jsonl",
    "validation.jsonl",
)
FINAL_FILES = frozenset((*PACKAGE_FILES, "checksums.sha256"))
SOURCE_FIELDS = frozenset({"instruction", "input", "output", "system"})
QUALITY_FLAGS = frozenset(
    {
        "short",
        "medium",
        "long",
        "very_long",
        "complete",
        "incomplete_candidate",
        "strong_repeat_candidate",
        "near_duplicate_participant",
        "ambiguous_category",
        "unresolved_category",
    }
)
SIDECAR_FIELDS = frozenset(
    {
        "schema_version",
        "record_hash",
        "split",
        "line_index",
        "category",
        "category_status",
        "prompt_tokens",
        "assistant_tokens",
        "total_tokens",
        "answer_characters",
        "prompt_to_assistant_ratio",
        "length_bucket",
        "completion_score",
        "repetition_score",
        "eos_contract_valid",
        "is_complete",
        "is_strong_repeat_candidate",
        "is_near_duplicate_participant",
        "quality_flags",
        "sampling_weight_components",
        "sampling_weight",
        "review_required",
    }
)
REVIEW_FIELDS = frozenset(
    {
        "record_hash",
        "split",
        "line_index",
        "category_status",
        "quality_flags",
        "completion_score",
        "repetition_score",
        "answer_tokens",
        "review_reason",
    }
)
REVIEW_FLAGS = frozenset(
    {
        "incomplete_candidate",
        "strong_repeat_candidate",
        "ambiguous_category",
        "unresolved_category",
    }
)


class V02SidecarError(RuntimeError):
    """Fail-closed error carrying only a stable code."""


def _plain_sha256(path: Path) -> str:
    return file_checksum(path).removeprefix("sha256:")


def _fsync_file(path: Path) -> None:
    # Windows requires a writable descriptor for a reliable FlushFileBuffers call.
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def _canonical_record_hash(
    split: str, line_index: int, record: Mapping[str, object]
) -> str:
    identity = {"line_index": line_index, "record": dict(record), "split": split}
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


def _content_hash(record: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(record))).hexdigest()


def _normalize(value: str) -> str:
    normalized = (
        unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    )
    return " ".join(normalized.split())


def _percentile(values: list[float], percentage: int) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(percentage / 100 * len(ordered)) - 1]


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "mean": statistics.fmean(values),
        "p50": _percentile(values, 50),
        "p90": _percentile(values, 90),
        "p99": _percentile(values, 99),
        "max": max(values),
    }


def load_policy(path: str | Path) -> dict[str, object]:
    try:
        value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise V02SidecarError("POLICY_INVALID") from None
    validate_policy(value)
    return value


def validate_policy(value: object) -> None:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise V02SidecarError("POLICY_INVALID")
    required = {
        "schema_version",
        "policy_id",
        "dataset_id",
        "source",
        "tokenization",
        "length_buckets",
        "target_length_distribution",
        "length_weight",
        "category_weight",
        "quality_weight",
        "final_weight",
        "near_duplicate",
        "validation",
        "execution_allowed",
        "tokenization_allowed",
        "training_allowed",
    }
    if set(value) != required:
        raise V02SidecarError("POLICY_INVALID")
    if any(
        value.get(name) is not False
        for name in ("execution_allowed", "tokenization_allowed", "training_allowed")
    ):
        raise V02SidecarError("POLICY_PERMISSION_INVALID")
    targets = value.get("target_length_distribution")
    if not isinstance(targets, dict) or set(targets) != {
        "short",
        "medium",
        "long",
        "very_long",
    }:
        raise V02SidecarError("POLICY_INVALID")
    if not math.isclose(
        sum(float(item) for item in targets.values()), 1.0, abs_tol=1e-12
    ):
        raise V02SidecarError("POLICY_INVALID")
    buckets = value.get("length_buckets")
    if not isinstance(buckets, dict) or buckets != {
        "short": {"minimum_tokens": 0, "maximum_tokens": 128},
        "medium": {"minimum_tokens": 129, "maximum_tokens": 256},
        "long": {"minimum_tokens": 257, "maximum_tokens": 512},
        "very_long": {"minimum_tokens": 513, "maximum_tokens": None},
    }:
        raise V02SidecarError("POLICY_INVALID")
    near_duplicate = value.get("near_duplicate")
    if not isinstance(near_duplicate, dict) or set(near_duplicate) != {
        "method",
        "review_threshold",
        "high_similarity_threshold",
        "maximum_candidate_pairs",
        "persist_pairs",
    }:
        raise V02SidecarError("POLICY_INVALID")
    review_threshold = float(near_duplicate["review_threshold"])
    high_threshold = float(near_duplicate["high_similarity_threshold"])
    if not 0 < review_threshold <= high_threshold <= 1:
        raise V02SidecarError("POLICY_INVALID")


def length_bucket(tokens: int) -> str:
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
        raise V02SidecarError("TOKEN_LENGTH_INVALID")
    if tokens <= 128:
        return "short"
    if tokens <= 256:
        return "medium"
    if tokens <= 512:
        return "long"
    return "very_long"


def completion_metrics(text: str) -> tuple[float, bool, dict[str, bool]]:
    value = text.rstrip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    last_line = lines[-1] if lines else ""
    terminal = bool(re.search(r"(?:[.!?。！？]|다\.|요\.|습니다\.)$", value))
    open_bracket = any(
        value.count(left) != value.count(right)
        for left, right in (("(", ")"), ("[", "]"), ("{", "}"))
    )
    dangling_number = bool(re.fullmatch(r"(?:\d+|[가-힣A-Za-z])[.)]?", last_line))
    list_interrupted = (
        bool(re.match(r"^(?:[-*•]|\d+[.)])\s*", last_line)) and not terminal
    )
    intermediate = bool(re.search(r"[,;:]$", value))
    strong = open_bracket or dangling_number or list_interrupted or intermediate
    if not value or (not terminal and (dangling_number or list_interrupted)):
        score = 0.0
    elif strong:
        score = 0.5
    elif terminal and not value.endswith(
        ("다.", "요.", "습니다.", "입니다.", "였습니다.")
    ):
        score = 0.75
    elif terminal:
        score = 1.0
    else:
        score = 0.0
    signals = {
        "terminal": terminal,
        "open_bracket": open_bracket,
        "dangling_number": dangling_number,
        "list_interrupted": list_interrupted,
        "intermediate_termination": intermediate,
    }
    return score, score >= 0.75 and not strong, signals


def repetition_metrics(
    text: str, *, near_duplicate: bool
) -> tuple[int, bool, dict[str, object]]:
    normalized = _normalize(text)
    sentences = [
        _normalize(part)
        for part in re.split(r"(?<=[.!?。！？])\s+|\n+", text)
        if _normalize(part)
    ]
    sentence_counts = Counter(sentences)
    sentence_repeat = any(count > 1 for count in sentence_counts.values())
    consecutive = any(left == right for left, right in pairwise(sentences))
    words = normalized.split()
    grams = [tuple(words[index : index + 5]) for index in range(max(0, len(words) - 4))]
    excess = len(grams) - len(set(grams))
    ratio = 0.0 if not grams else excess / len(grams)
    if consecutive:
        score = 3
    elif sentence_repeat or ratio >= 0.10:
        score = 2
    elif excess or near_duplicate:
        score = 1
    else:
        score = 0
    return (
        score,
        score >= 2,
        {
            "consecutive_sentence_repetition": consecutive,
            "sentence_repetition": sentence_repeat,
            "five_gram_repeated_excess": excess,
            "five_gram_repeated_excess_ratio": ratio,
        },
    )


def _trigrams(value: str) -> frozenset[str]:
    return frozenset(
        value[index : index + 3] for index in range(max(1, len(value) - 2))
    )


def near_duplicate_participants(
    values: list[str],
    splits: list[str],
    *,
    review_threshold: float,
    high_similarity_threshold: float,
    maximum_candidate_pairs: int,
) -> tuple[frozenset[int], dict[str, int]]:
    normalized = [_normalize(value) for value in values]
    grams = [_trigrams(value) for value in normalized]
    sizes = [len(value) for value in grams]
    postings: dict[str, list[int]] = defaultdict(list)
    candidates: set[tuple[int, int]] = set()
    for right, features in enumerate(grams):
        counts: dict[int, int] = defaultdict(int)
        for feature in features:
            for left in postings[feature]:
                counts[left] += 1
        for left, overlap in counts.items():
            denominator = sizes[left] + sizes[right] - overlap
            if denominator and overlap / denominator >= max(
                0.25, review_threshold - 0.5
            ):
                candidates.add((left, right))
                if len(candidates) > maximum_candidate_pairs:
                    raise V02SidecarError("NEAR_DUPLICATE_CANDIDATE_LIMIT")
        for feature in features:
            postings[feature].append(right)
    participating: set[int] = set()
    counts = Counter()
    for left, right in sorted(candidates):
        if normalized[left] == normalized[right]:
            continue
        matcher = SequenceMatcher(None, normalized[left], normalized[right])
        if (
            matcher.real_quick_ratio() < review_threshold
            or matcher.quick_ratio() < review_threshold
        ):
            continue
        similarity = matcher.ratio()
        if similarity < review_threshold:
            continue
        participating.update((left, right))
        counts["review_pairs"] += 1
        if similarity >= high_similarity_threshold:
            counts["high_similarity_pairs"] += 1
        counts[
            "cross_split_pairs"
            if splits[left] != splits[right]
            else f"within_{splits[left]}_pairs"
        ] += 1
    return frozenset(participating), {
        "candidate_pairs": len(candidates),
        "review_pairs": counts["review_pairs"],
        "high_similarity_pairs": counts["high_similarity_pairs"],
        "within_train_pairs": counts["within_train_pairs"],
        "within_validation_pairs": counts["within_validation_pairs"],
        "cross_split_pairs": counts["cross_split_pairs"],
        "participating_records": len(participating),
    }


def category_lookup_from_raw(raw_root: str | Path) -> dict[str, Counter[str]]:
    loaded = []
    for source in discover_sft_sources(raw_root):
        loaded.extend(iter_source_records(source))
    joined = join_source_records(loaded)
    lookup: dict[str, Counter[str]] = defaultdict(Counter)
    for record in joined:
        value = {
            "instruction": record.question,
            "input": None,
            "output": record.answer,
            "system": None,
        }
        lookup[_content_hash(value)][record.data_category] += 1
    return lookup


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    try:
        stream = path.open("r", encoding="utf-8", newline="")
    except (OSError, UnicodeError):
        raise V02SidecarError("SOURCE_JSONL_INVALID") from None
    with stream:
        for line in stream:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                raise V02SidecarError("SOURCE_JSONL_INVALID") from None
            if not isinstance(value, dict) or set(value) != SOURCE_FIELDS:
                raise V02SidecarError("SOURCE_SCHEMA_INVALID")
            if not isinstance(value["instruction"], str) or not isinstance(
                value["output"], str
            ):
                raise V02SidecarError("SOURCE_SCHEMA_INVALID")
            records.append(value)
    return records


def _load_tokenized(
    root: Path,
) -> tuple[list[Mapping[str, object]], list[Mapping[str, object]]]:
    try:
        from datasets import load_from_disk

        train = list(load_from_disk(str(root / "train")))
        validation = list(load_from_disk(str(root / "validation")))
    except Exception:  # noqa: BLE001 - third-party datasets exposes multiple backend errors
        raise V02SidecarError("TOKENIZED_DATASET_INVALID") from None
    return train, validation


def _token_metrics(
    record: Mapping[str, object], *, eos_token_id: int
) -> dict[str, int | bool]:
    try:
        ids = list(record["input_ids"])
        labels = list(record["labels"])
        attention = list(record["attention_mask"])
    except (KeyError, TypeError):
        raise V02SidecarError("TOKENIZED_DATASET_INVALID") from None
    if (
        not ids
        or not (len(ids) == len(labels) == len(attention))
        or any(value != 1 for value in attention)
    ):
        raise V02SidecarError("TOKENIZED_DATASET_INVALID")
    first = next(
        (index for index, value in enumerate(labels) if value != -100), len(labels)
    )
    if (
        first == len(labels)
        or any(value != -100 for value in labels[:first])
        or any(value == -100 for value in labels[first:])
    ):
        raise V02SidecarError("LABEL_MASK_INVALID")
    eos_positions = [
        index for index, value in enumerate(labels) if value == eos_token_id
    ]
    valid = len(eos_positions) == 1 and eos_positions[0] == len(labels) - 1
    if not valid:
        raise V02SidecarError("EOS_CONTRACT_INVALID")
    return {
        "prompt_tokens": first,
        "assistant_tokens": len(labels) - first,
        "total_tokens": len(labels),
        "eos_contract_valid": valid,
    }


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _normalize_clamped_mean_one(
    raw: list[float], minimum: float, maximum: float
) -> list[float]:
    if not raw or any(not math.isfinite(value) or value <= 0 for value in raw):
        raise V02SidecarError("SAMPLING_WEIGHT_INVALID")
    low, high = 0.0, maximum / min(raw) * 2
    for _ in range(128):
        scale = (low + high) / 2
        mean = statistics.fmean(
            _clamp(value * scale, minimum, maximum) for value in raw
        )
        if mean < 1.0:
            low = scale
        else:
            high = scale
    result = [_clamp(value * high, minimum, maximum) for value in raw]
    if not math.isclose(statistics.fmean(result), 1.0, abs_tol=1e-10):
        raise V02SidecarError("SAMPLING_NORMALIZATION_FAILED")
    return result


def _quality_tier(flags: set[str], policy: Mapping[str, object]) -> tuple[str, float]:
    values = policy["quality_weight"]
    assert isinstance(values, Mapping)
    candidates = [("complete_and_normal", float(values["complete_and_normal"]))]
    if "strong_repeat_candidate" in flags and "incomplete_candidate" in flags:
        candidates.append(
            ("repeat_and_incomplete", float(values["repeat_and_incomplete"]))
        )
    elif "strong_repeat_candidate" in flags:
        candidates.append(
            ("strong_repeat_candidate", float(values["strong_repeat_candidate"]))
        )
    elif "incomplete_candidate" in flags:
        candidates.append(
            ("incomplete_candidate", float(values["incomplete_candidate"]))
        )
    if "ambiguous_category" in flags:
        candidates.append(("ambiguous_category", float(values["ambiguous_category"])))
    if "near_duplicate_participant" in flags:
        candidates.append(
            ("near_duplicate_participant", float(values["near_duplicate_participant"]))
        )
    return min(candidates, key=lambda item: item[1])


def _copy_fsync(source: Path, destination: Path) -> None:
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    except OSError:
        raise V02SidecarError("SOURCE_COPY_FAILED") from None


def _write_checksums(root: Path) -> dict[str, str]:
    checksums = {name: _plain_sha256(root / name) for name in PACKAGE_FILES}
    with (root / "checksums.sha256").open(
        "x", encoding="ascii", newline="\n"
    ) as stream:
        for name in PACKAGE_FILES:
            stream.write(f"{checksums[name]}  {name}\n")
        stream.flush()
        os.fsync(stream.fileno())
    return checksums


def _validate_checksums(root: Path) -> dict[str, str]:
    try:
        lines = (root / "checksums.sha256").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError):
        raise V02SidecarError("CHECKSUM_INVALID") from None
    parsed: dict[str, str] = {}
    for line in lines:
        pieces = line.split("  ", 1)
        if len(pieces) != 2 or len(pieces[0]) != 64 or pieces[1] in parsed:
            raise V02SidecarError("CHECKSUM_INVALID")
        parsed[pieces[1]] = pieces[0]
    if set(parsed) != set(PACKAGE_FILES):
        raise V02SidecarError("CHECKSUM_INVALID")
    if any(_plain_sha256(root / name) != digest for name, digest in parsed.items()):
        raise V02SidecarError("CHECKSUM_MISMATCH")
    return parsed


def _expected_distribution(
    sidecar: list[dict[str, object]], field: str, *, train_only: bool = True
) -> dict[str, float]:
    selected = [
        record for record in sidecar if not train_only or record["split"] == "train"
    ]
    total = sum(float(record["sampling_weight"]) for record in selected)
    result = Counter()
    for record in selected:
        value = record[field]
        key = "null" if value is None else str(value)
        result[key] += float(record["sampling_weight"])
    return {key: result[key] / total for key in sorted(result)}


def _expected_quality_distribution(
    sidecar: list[dict[str, object]],
) -> dict[str, float]:
    selected = [record for record in sidecar if record["split"] == "train"]
    total = sum(float(record["sampling_weight"]) for record in selected)
    result: Counter[str] = Counter()
    for record in selected:
        components = record["sampling_weight_components"]
        if not isinstance(components, Mapping):
            raise V02SidecarError("SAMPLING_WEIGHT_INVALID")
        result[str(components["quality_tier"])] += float(record["sampling_weight"])
    return {key: result[key] / total for key in sorted(result)}


def build_v02_sidecar_package(
    *,
    source_root: str | Path,
    tokenized_root: str | Path,
    output_root: str | Path,
    policy: Mapping[str, object],
    git_head: str,
    category_lookup: Mapping[str, Counter[str]] | None = None,
    raw_root: str | Path | None = None,
) -> dict[str, object]:
    validate_policy(policy)
    source = Path(source_root).resolve()
    tokenized = Path(tokenized_root).resolve()
    output = Path(output_root).resolve()
    if (
        output.exists()
        or output.with_name(output.name + ".staging").exists()
        or output.with_name(output.name + ".failed").exists()
    ):
        raise V02SidecarError("OUTPUT_ID_ALREADY_USED")
    if source == output or source in output.parents or output in source.parents:
        raise V02SidecarError("OUTPUT_PATH_INVALID")
    source_config = policy["source"]
    assert isinstance(source_config, Mapping)
    expected_checksums = source_config["checksums"]
    assert isinstance(expected_checksums, Mapping)
    for name, expected in expected_checksums.items():
        if _plain_sha256(source / str(name)) != str(expected):
            raise V02SidecarError("SOURCE_CHECKSUM_MISMATCH")

    train = _load_jsonl(source / "train.jsonl")
    validation = _load_jsonl(source / "validation.jsonl")
    expected_rows = source_config["rows"]
    assert isinstance(expected_rows, Mapping)
    if len(train) != int(expected_rows["train"]) or len(validation) != int(
        expected_rows["validation"]
    ):
        raise V02SidecarError("SOURCE_ROW_COUNT_MISMATCH")
    token_train, token_validation = _load_tokenized(tokenized)
    if len(train) != len(token_train) or len(validation) != len(token_validation):
        raise V02SidecarError("SIDECAR_ALIGNMENT_INVALID")
    records = train + validation
    token_records = token_train + token_validation
    splits = ["train"] * len(train) + ["validation"] * len(validation)
    line_indexes = [*range(len(train)), *range(len(validation))]
    lookup = category_lookup
    if lookup is None:
        if raw_root is None:
            raise V02SidecarError("CATEGORY_LINEAGE_REQUIRED")
        lookup = category_lookup_from_raw(raw_root)
    normalized_qa = [
        _normalize(str(record["instruction"]) + "\n" + str(record["output"]))
        for record in records
    ]
    near_config = policy["near_duplicate"]
    assert isinstance(near_config, Mapping)
    near_participants, near_statistics = near_duplicate_participants(
        normalized_qa,
        splits,
        review_threshold=float(near_config["review_threshold"]),
        high_similarity_threshold=float(near_config["high_similarity_threshold"]),
        maximum_candidate_pairs=int(near_config["maximum_candidate_pairs"]),
    )
    eos_id = int(policy["tokenization"]["eos_token_id"])  # type: ignore[index]
    sidecar: list[dict[str, object]] = []
    review_queue: list[dict[str, object]] = []
    record_hashes: set[str] = set()
    train_content_hashes: set[str] = set()
    validation_content_hashes: set[str] = set()
    for ordinal, (record, token_record, split, line_index) in enumerate(
        zip(records, token_records, splits, line_indexes)
    ):
        record_hash = _canonical_record_hash(split, line_index, record)
        if record_hash in record_hashes:
            raise V02SidecarError("RECORD_HASH_COLLISION")
        record_hashes.add(record_hash)
        content_hash = _content_hash(record)
        (train_content_hashes if split == "train" else validation_content_hashes).add(
            content_hash
        )
        choices = lookup.get(content_hash, Counter())
        if not choices:
            category, category_status = None, "unresolved"
        elif len(choices) > 1:
            category, category_status = None, "ambiguous"
        else:
            category, category_status = next(iter(choices)), "resolved"
        metrics = _token_metrics(token_record, eos_token_id=eos_id)
        assistant_tokens = int(metrics["assistant_tokens"])
        bucket = length_bucket(assistant_tokens)
        completion_score, complete, completion_signals = completion_metrics(
            str(record["output"])
        )
        repetition_score, strong_repeat, repetition_signals = repetition_metrics(
            str(record["output"]), near_duplicate=ordinal in near_participants
        )
        flags = {bucket, "complete" if complete else "incomplete_candidate"}
        if strong_repeat:
            flags.add("strong_repeat_candidate")
        if ordinal in near_participants:
            flags.add("near_duplicate_participant")
        if category_status == "ambiguous":
            flags.add("ambiguous_category")
        if category_status == "unresolved":
            flags.add("unresolved_category")
        if not flags <= QUALITY_FLAGS:
            raise V02SidecarError("QUALITY_FLAG_INVALID")
        prompt_tokens = int(metrics["prompt_tokens"])
        item: dict[str, object] = {
            "schema_version": SIDECAR_SCHEMA_VERSION,
            "record_hash": record_hash,
            "split": split,
            "line_index": line_index,
            "category": category,
            "category_status": category_status,
            "prompt_tokens": prompt_tokens,
            "assistant_tokens": assistant_tokens,
            "total_tokens": int(metrics["total_tokens"]),
            "answer_characters": len(str(record["output"])),
            "prompt_to_assistant_ratio": prompt_tokens / assistant_tokens,
            "length_bucket": bucket,
            "completion_score": completion_score,
            "repetition_score": repetition_score,
            "eos_contract_valid": bool(metrics["eos_contract_valid"]),
            "is_complete": complete,
            "is_strong_repeat_candidate": strong_repeat,
            "is_near_duplicate_participant": ordinal in near_participants,
            "quality_flags": sorted(flags),
            "sampling_weight_components": None,
            "sampling_weight": 1.0,
            "review_required": bool(flags & REVIEW_FLAGS),
        }
        sidecar.append(item)
        if item["review_required"]:
            review_queue.append(
                {
                    "record_hash": record_hash,
                    "split": split,
                    "line_index": line_index,
                    "category_status": category_status,
                    "quality_flags": sorted(flags),
                    "completion_score": completion_score,
                    "repetition_score": repetition_score,
                    "answer_tokens": assistant_tokens,
                    "review_reason": sorted(flags & REVIEW_FLAGS),
                }
            )
        del completion_signals, repetition_signals
    if train_content_hashes & validation_content_hashes:
        raise V02SidecarError("SPLIT_ISOLATION_INVALID")

    train_sidecar = [record for record in sidecar if record["split"] == "train"]
    bucket_counts = Counter(str(record["length_bucket"]) for record in train_sidecar)
    resolved_category_counts = Counter(
        str(record["category"])
        for record in train_sidecar
        if record["category_status"] == "resolved"
    )
    targets = policy["target_length_distribution"]
    length_policy = policy["length_weight"]
    category_policy = policy["category_weight"]
    final_policy = policy["final_weight"]
    assert all(
        isinstance(value, Mapping)
        for value in (targets, length_policy, category_policy, final_policy)
    )
    length_weights: dict[str, dict[str, float | bool]] = {}
    for bucket in ("short", "medium", "long", "very_long"):
        observed = bucket_counts[bucket] / len(train_sidecar)
        if observed <= 0:
            raise V02SidecarError("SAMPLING_BUCKET_EMPTY")
        raw = float(targets[bucket]) / observed  # type: ignore[index]
        clamped = _clamp(
            raw, float(length_policy["minimum"]), float(length_policy["maximum"])
        )  # type: ignore[index]
        length_weights[bucket] = {
            "observed_ratio": observed,
            "target_ratio": float(targets[bucket]),
            "raw_weight": raw,
            "clamped_weight": clamped,
            "clamped": not math.isclose(raw, clamped),
        }  # type: ignore[index]
    mean_category_count = statistics.fmean(resolved_category_counts.values())
    category_weights = {
        category: {
            "rows": count,
            "raw_weight": math.sqrt(mean_category_count / count),
            "clamped_weight": _clamp(
                math.sqrt(mean_category_count / count),
                float(category_policy["minimum"]),  # type: ignore[index]
                float(category_policy["maximum"]),  # type: ignore[index]
            ),
        }
        for category, count in sorted(resolved_category_counts.items())
    }
    raw_weights: list[float] = []
    quality_tiers: list[tuple[str, float]] = []
    for record in train_sidecar:
        flags = set(record["quality_flags"])  # type: ignore[arg-type]
        tier = _quality_tier(flags, policy)
        quality_tiers.append(tier)
        category_value = record["category"]
        category_weight = (
            float(category_weights[str(category_value)]["clamped_weight"])
            if category_value is not None
            else 1.0
        )
        raw_weights.append(
            float(length_weights[str(record["length_bucket"])]["clamped_weight"])
            * category_weight
            * tier[1]
        )
    normalized = _normalize_clamped_mean_one(
        raw_weights,
        float(final_policy["minimum"]),  # type: ignore[index]
        float(final_policy["maximum"]),  # type: ignore[index]
    )
    for record, tier, weight in zip(train_sidecar, quality_tiers, normalized):
        category_value = record["category"]
        category_weight = (
            float(category_weights[str(category_value)]["clamped_weight"])
            if category_value is not None
            else 1.0
        )
        record["sampling_weight_components"] = {
            "length": float(
                length_weights[str(record["length_bucket"])]["clamped_weight"]
            ),
            "category": category_weight,
            "quality": tier[1],
            "quality_tier": tier[0],
        }
        record["sampling_weight"] = weight
    for record in sidecar[len(train_sidecar) :]:
        record["sampling_weight_components"] = {
            "length": 1.0,
            "category": 1.0,
            "quality": 1.0,
            "quality_tier": "validation_fixed",
        }
        record["sampling_weight"] = 1.0

    weights = [float(record["sampling_weight"]) for record in train_sidecar]
    ess = sum(weights) ** 2 / sum(value * value for value in weights)
    ess_ratio = ess / len(train_sidecar)
    minimum_ess = float(final_policy["minimum_train_ess_ratio"])  # type: ignore[index]
    if ess_ratio < minimum_ess:
        raise V02SidecarError("SAMPLING_ESS_BELOW_MINIMUM")
    expected_length = _expected_distribution(sidecar, "length_bucket")
    expected_category = _expected_distribution(sidecar, "category")
    expected_quality = _expected_quality_distribution(sidecar)
    observed_length = {
        bucket: bucket_counts[bucket] / len(train_sidecar)
        for bucket in ("short", "medium", "long", "very_long")
    }
    sampling_result = {
        "length_weight": length_weights,
        "category_weight": category_weights,
        "expected_length_distribution": expected_length,
        "expected_category_distribution": expected_category,
        "expected_quality_distribution": expected_quality,
        "effective_sample_size": ess,
        "effective_sample_size_ratio": ess_ratio,
        "weight_statistics": _summary(weights),
        "maximum_record_probability": max(weights) / sum(weights),
        "minimum_record_probability": min(weights) / sum(weights),
        "validation_sampling_weight": 1.0,
    }

    completion_counts = Counter(str(record["completion_score"]) for record in sidecar)
    repetition_counts = Counter(str(record["repetition_score"]) for record in sidecar)
    flag_counts = Counter(
        flag for record in sidecar for flag in record["quality_flags"]
    )  # type: ignore[union-attr]
    category_status_counts = Counter(
        str(record["category_status"]) for record in sidecar
    )
    sidecar_fingerprint = checksum_value({"records": sidecar})
    policy_definition_fingerprint = checksum_value(dict(policy))
    statistics_value = {
        "schema_version": 1,
        "rows": {
            "train": len(train),
            "validation": len(validation),
            "total": len(records),
        },
        "source_checksums": {
            "train.jsonl": _plain_sha256(source / "train.jsonl"),
            "validation.jsonl": _plain_sha256(source / "validation.jsonl"),
        },
        "length_bucket_actual": {
            bucket: {"rows": bucket_counts[bucket], "ratio": observed_length[bucket]}
            for bucket in ("short", "medium", "long", "very_long")
        },
        "length_bucket_expected_sampling": expected_length,
        "category_actual_train": dict(sorted(resolved_category_counts.items())),
        "category_expected_sampling": expected_category,
        "completion_score": dict(sorted(completion_counts.items())),
        "repetition_score": dict(sorted(repetition_counts.items())),
        "quality_flags": dict(sorted(flag_counts.items())),
        "category_status": dict(sorted(category_status_counts.items())),
        "review_queue_rows": len(review_queue),
        "near_duplicate": near_statistics,
        "sampling": sampling_result,
        "content_preservation": {
            "rows_added": 0,
            "rows_removed": 0,
            "rows_modified": 0,
            "eos_embedded_in_jsonl": False,
        },
        "tokenization_started": False,
        "training_started": False,
    }
    statistics_fingerprint = checksum_value(statistics_value)
    policy_semantic = {
        "schema_version": 1,
        "policy_id": policy["policy_id"],
        "definition": {
            "target_length_distribution": dict(targets),
            "length_weight": dict(length_policy),
            "category_weight": dict(category_policy),
            "quality_weight": dict(policy["quality_weight"]),  # type: ignore[arg-type]
            "final_weight": dict(final_policy),
            "validation": dict(policy["validation"]),  # type: ignore[arg-type]
        },
        "calculated": sampling_result,
        "definition_fingerprint": policy_definition_fingerprint,
        "execution_allowed": False,
    }
    policy_fingerprint = checksum_value(policy_semantic)
    policy_document = {
        **policy_semantic,
        "policy_fingerprint": policy_fingerprint,
    }
    manifest_semantic = {
        "schema_version": 1,
        "dataset_id": policy["dataset_id"],
        "dataset_version": DATASET_VERSION,
        "source": {
            "processing_run_id": source_config["processing_run_id"],
            "tokenization_run_id": source_config["tokenization_run_id"],
            "source_dataset_fingerprint": source_config["dataset_fingerprint"],
            "source_train_sha256": expected_checksums["train.jsonl"],
            "source_validation_sha256": expected_checksums["validation.jsonl"],
        },
        "content_policy": {
            "jsonl_byte_identical": True,
            "rows_added": 0,
            "rows_removed": 0,
            "rows_modified": 0,
            "eos_embedded_in_jsonl": False,
        },
        "sidecar": {
            "schema_version": SIDECAR_SCHEMA_VERSION,
            "identity_method": "sha256(canonical-json(split,line_index,record))",
            "row_count": len(sidecar),
            "fingerprint": sidecar_fingerprint,
        },
        "sampling": {
            "policy_id": policy["policy_id"],
            "policy_fingerprint": policy_fingerprint,
            "target_distribution": dict(targets),
            "expected_distribution": expected_length,
            "effective_sample_size": ess,
            "effective_sample_size_ratio": ess_ratio,
        },
    }
    manifest_fingerprint = checksum_value(manifest_semantic)
    package_fingerprint_payload = {
        "algorithm": "canonical-json-ordered-components-v1",
        "components": [
            ["train.jsonl", str(expected_checksums["train.jsonl"])],
            ["validation.jsonl", str(expected_checksums["validation.jsonl"])],
            ["quality-sidecar", sidecar_fingerprint],
            ["sampling-policy", policy_fingerprint],
            ["statistics", statistics_fingerprint],
            ["manifest-semantic", manifest_fingerprint],
        ],
    }
    package_fingerprint = checksum_value(package_fingerprint_payload)
    manifest = {
        **manifest_semantic,
        "quality_version": "v0.2-quality-v1",
        "sampling_version": "v0.2-sampling-v1",
        "sidecar_version": "v1",
        "generation_policy": "no_new_qa_no_summary_no_rewrite",
        "fingerprints": {
            "sidecar": sidecar_fingerprint,
            "sampling_policy": policy_fingerprint,
            "statistics": statistics_fingerprint,
            "manifest": manifest_fingerprint,
            "package": package_fingerprint,
            "package_algorithm": package_fingerprint_payload,
        },
        "lineage": {
            "git_head": git_head,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "tokenization_allowed": False,
        "training_allowed": False,
        "execution_allowed": False,
    }

    # The source package remains immutable throughout calculation. Re-read every
    # governed digest immediately before any output is written.
    for name, expected in expected_checksums.items():
        if _plain_sha256(source / str(name)) != str(expected):
            raise V02SidecarError("SOURCE_CHANGED_DURING_BUILD")

    atomic = AtomicArtifactDirectory(output)
    with atomic as staging:
        _copy_fsync(source / "train.jsonl", staging / "train.jsonl")
        _copy_fsync(source / "validation.jsonl", staging / "validation.jsonl")
        write_jsonl(staging / "quality-sidecar.jsonl", sidecar)
        write_jsonl(staging / "review-queue.jsonl", review_queue)
        write_yaml(staging / "sampling-policy.yaml", policy_document)
        write_yaml(staging / "manifest.yaml", manifest)
        write_json(staging / "statistics.json", statistics_value)
        _fsync_file(staging / "statistics.json")
        checksums = _write_checksums(staging)
        _fsync_directory(staging)
        if checksums["train.jsonl"] != str(
            expected_checksums["train.jsonl"]
        ) or checksums["validation.jsonl"] != str(
            expected_checksums["validation.jsonl"]
        ):
            raise V02SidecarError("SOURCE_COPY_NOT_IDENTICAL")
        validate_v02_package(staging, policy=policy)
        atomic.publish()
    reloaded = validate_v02_package(output, policy=policy)
    return {
        "output": str(output),
        "rows": reloaded["rows"],
        "checksums": reloaded["checksums"],
        "fingerprints": manifest["fingerprints"],
        "sampling": sampling_result,
        "review_queue_rows": len(review_queue),
        "category_status": dict(sorted(category_status_counts.items())),
        "tokenization_started": False,
        "training_started": False,
    }


def validate_v02_package(
    root: str | Path, *, policy: Mapping[str, object]
) -> dict[str, object]:
    directory = Path(root)
    try:
        entries = list(directory.iterdir())
    except OSError:
        raise V02SidecarError("PACKAGE_RELOAD_FAILED") from None
    if {path.name for path in entries} != FINAL_FILES or any(
        path.is_symlink() or not path.is_file() for path in entries
    ):
        raise V02SidecarError("PACKAGE_FILE_SET_INVALID")
    checksums = _validate_checksums(directory)
    train = _load_jsonl(directory / "train.jsonl")
    validation = _load_jsonl(directory / "validation.jsonl")
    sidecar = _load_jsonl_unrestricted(directory / "quality-sidecar.jsonl")
    review = _load_jsonl_unrestricted(directory / "review-queue.jsonl")
    try:
        manifest = yaml.safe_load(
            (directory / "manifest.yaml").read_text(encoding="utf-8")
        )
        sampling = yaml.safe_load(
            (directory / "sampling-policy.yaml").read_text(encoding="utf-8")
        )
        statistics_value = json.loads(
            (directory / "statistics.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, yaml.YAMLError, json.JSONDecodeError):
        raise V02SidecarError("PACKAGE_RELOAD_FAILED") from None
    if len(sidecar) != len(train) + len(validation):
        raise V02SidecarError("SIDECAR_ALIGNMENT_INVALID")
    hashes: set[str] = set()
    for ordinal, value in enumerate(sidecar):
        split = "train" if ordinal < len(train) else "validation"
        index = ordinal if split == "train" else ordinal - len(train)
        source_record = train[index] if split == "train" else validation[index]
        if set(value) != SIDECAR_FIELDS or value.get("schema_version") != 1:
            raise V02SidecarError("SIDECAR_SCHEMA_INVALID")
        if value.get("split") != split or value.get("line_index") != index:
            raise V02SidecarError("SIDECAR_ALIGNMENT_INVALID")
        expected_hash = _canonical_record_hash(split, index, source_record)
        if value.get("record_hash") != expected_hash or expected_hash in hashes:
            raise V02SidecarError("RECORD_HASH_COLLISION")
        hashes.add(expected_hash)
        weight = value.get("sampling_weight")
        if (
            not isinstance(weight, (int, float))
            or isinstance(weight, bool)
            or not math.isfinite(weight)
            or weight <= 0
        ):
            raise V02SidecarError("SAMPLING_WEIGHT_INVALID")
        if split == "validation" and weight != 1.0:
            raise V02SidecarError("VALIDATION_WEIGHT_INVALID")
        flags = value.get("quality_flags")
        if not isinstance(flags, list) or not set(flags) <= QUALITY_FLAGS:
            raise V02SidecarError("QUALITY_FLAG_INVALID")
        integer_fields = (
            "line_index",
            "prompt_tokens",
            "assistant_tokens",
            "total_tokens",
            "answer_characters",
            "repetition_score",
        )
        if any(
            isinstance(value.get(name), bool)
            or not isinstance(value.get(name), int)
            or int(value[name]) < 0
            for name in integer_fields
        ):
            raise V02SidecarError("SIDECAR_SCHEMA_INVALID")
        if value.get("category_status") not in {"resolved", "ambiguous", "unresolved"}:
            raise V02SidecarError("SIDECAR_SCHEMA_INVALID")
        if value.get("length_bucket") not in {"short", "medium", "long", "very_long"}:
            raise V02SidecarError("SIDECAR_SCHEMA_INVALID")
        if any(
            not isinstance(value.get(name), bool)
            for name in (
                "eos_contract_valid",
                "is_complete",
                "is_strong_repeat_candidate",
                "is_near_duplicate_participant",
                "review_required",
            )
        ):
            raise V02SidecarError("SIDECAR_SCHEMA_INVALID")
    if any(set(value) != REVIEW_FIELDS for value in review):
        raise V02SidecarError("REVIEW_QUEUE_INVALID")
    review_hashes = {value.get("record_hash") for value in review}
    expected_review = {
        value["record_hash"] for value in sidecar if value.get("review_required")
    }
    if review_hashes != expected_review or len(review_hashes) != len(review):
        raise V02SidecarError("REVIEW_QUEUE_INVALID")
    if manifest.get("content_policy", {}).get("jsonl_byte_identical") is not True:
        raise V02SidecarError("MANIFEST_INVALID")
    if (
        sampling.get("execution_allowed") is not False
        or statistics_value.get("training_started") is not False
    ):
        raise V02SidecarError("PACKAGE_PERMISSION_INVALID")
    calculated = sampling.get("calculated")
    manifest_sampling = manifest.get("sampling")
    manifest_sidecar = manifest.get("sidecar")
    expected_rows = {
        "train": len(train),
        "validation": len(validation),
        "total": len(train) + len(validation),
    }
    if (
        not isinstance(calculated, Mapping)
        or not isinstance(manifest_sampling, Mapping)
        or not isinstance(manifest_sidecar, Mapping)
        or manifest_sidecar.get("row_count") != len(sidecar)
        or statistics_value.get("rows") != expected_rows
        or statistics_value.get("review_queue_rows") != len(review)
        or manifest_sampling.get("expected_distribution")
        != calculated.get("expected_length_distribution")
        or manifest_sampling.get("effective_sample_size")
        != calculated.get("effective_sample_size")
        or manifest_sampling.get("effective_sample_size_ratio")
        != calculated.get("effective_sample_size_ratio")
        or statistics_value.get("sampling") != calculated
    ):
        raise V02SidecarError("PACKAGE_CONSISTENCY_INVALID")
    fingerprints = manifest.get("fingerprints")
    if not isinstance(fingerprints, Mapping):
        raise V02SidecarError("FINGERPRINT_INVALID")
    sampling_semantic = dict(sampling)
    stored_policy_fingerprint = sampling_semantic.pop("policy_fingerprint", None)
    sidecar_fingerprint = checksum_value({"records": sidecar})
    policy_fingerprint = checksum_value(sampling_semantic)
    statistics_fingerprint = checksum_value(statistics_value)
    manifest_semantic_keys = (
        "schema_version",
        "dataset_id",
        "dataset_version",
        "source",
        "content_policy",
        "sidecar",
        "sampling",
    )
    manifest_semantic = {key: manifest.get(key) for key in manifest_semantic_keys}
    manifest_fingerprint = checksum_value(manifest_semantic)
    package_algorithm = fingerprints.get("package_algorithm")
    if not isinstance(package_algorithm, Mapping):
        raise V02SidecarError("FINGERPRINT_INVALID")
    package_fingerprint = checksum_value(dict(package_algorithm))
    expected_fingerprints = {
        "sidecar": sidecar_fingerprint,
        "sampling_policy": policy_fingerprint,
        "statistics": statistics_fingerprint,
        "manifest": manifest_fingerprint,
        "package": package_fingerprint,
    }
    if stored_policy_fingerprint != policy_fingerprint or any(
        fingerprints.get(name) != value for name, value in expected_fingerprints.items()
    ):
        raise V02SidecarError("FINGERPRINT_MISMATCH")
    source_config = policy["source"]
    assert isinstance(source_config, Mapping)
    source_checksums = source_config["checksums"]
    assert isinstance(source_checksums, Mapping)
    expected_package_algorithm = {
        "algorithm": "canonical-json-ordered-components-v1",
        "components": [
            ["train.jsonl", str(source_checksums["train.jsonl"])],
            ["validation.jsonl", str(source_checksums["validation.jsonl"])],
            ["quality-sidecar", sidecar_fingerprint],
            ["sampling-policy", policy_fingerprint],
            ["statistics", statistics_fingerprint],
            ["manifest-semantic", manifest_fingerprint],
        ],
    }
    if dict(package_algorithm) != expected_package_algorithm:
        raise V02SidecarError("FINGERPRINT_MISMATCH")
    if (
        checksums["train.jsonl"] != source_checksums["train.jsonl"]
        or checksums["validation.jsonl"] != source_checksums["validation.jsonl"]
    ):
        raise V02SidecarError("SOURCE_COPY_NOT_IDENTICAL")
    return {
        "rows": {
            "train": len(train),
            "validation": len(validation),
            "sidecar": len(sidecar),
        },
        "checksums": checksums,
        "review_rows": len(review),
    }


def _load_jsonl_unrestricted(path: Path) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise V02SidecarError("PACKAGE_RELOAD_FAILED")
                values.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise V02SidecarError("PACKAGE_RELOAD_FAILED") from None
    return values
