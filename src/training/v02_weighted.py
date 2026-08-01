"""Fail-closed DohaLM v0.2 tokenized package and weighted sampling support."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import statistics
import struct
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Iterator

import torch
import yaml
from torch.utils.data import Sampler, SequentialSampler, WeightedRandomSampler

from src.data.artifacts import AtomicArtifactDirectory, _fsync_directory, write_jsonl, write_yaml
from src.data.checksums import canonical_json_bytes, checksum_value, file_checksum

TOKENIZATION_ID = "DOHALM-V0.2-TOKENIZATION-20260801-0001"
SIMULATION_ID = "DOHALM-V0.2-SAMPLING-SIMULATION-20260801-0001"
DATASET_ID = "DOHALM-V0.2-DATASET-SIDECAR-20260801-0001"
SOURCE_TOKENIZATION_ID = "DOHALM-TOKENIZATION-20260730-0001"
TOKENIZER_FINGERPRINT = "ad0a85da869c2e4577b9409df0c91e35be70f0395a20c94765c6f4fa02ea6a55"
DATASET_FINGERPRINT = "b6848e9413ecd0f63008cf18f505dda0b3197e562b5c6a9f955c1a7d41bc98a0"
PACKAGE_FINGERPRINT = "b1b760710ced0b47addc4bffed51f25185ff72bbb4fba1724782a65d7f11229f"
SIDECAR_FINGERPRINT = "4a13952b3f59937a19badad67630f18fd3a0b2902b7c57e0d1ea746699fdfe9c"
POLICY_FINGERPRINT = "30f1b4e3f8318f6086e19898bbe16edae7d6d5428326bada04bc0f8004eabb93"
SOURCE_SHA256 = {
    "train": "dc4e38778e34910e28fb46804e0bbafed947170a5faf155c699acbcf2ccb1cbb",
    "validation": "56266aa5b422c8de12e1c5b5cf6490f11d5f2dfc907d55c397e87ea5c7a66363",
}
ROWS = {"train": 10374, "validation": 1287}
EOS_TOKEN_ID = 151645
VOCAB_SIZE = 152064
MAX_SEQ_LENGTH = 1536


class V02WeightedError(RuntimeError):
    """Stable fail-closed error without source text."""


def _plain_sha(path: Path) -> str:
    return file_checksum(path).removeprefix("sha256:")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise V02WeightedError("ARTIFACT_RELOAD_FAILED") from None


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise V02WeightedError("ARTIFACT_RELOAD_FAILED") from None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError
                values.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise V02WeightedError("ARTIFACT_RELOAD_FAILED") from None
    return values


def _write_json_durable(path: Path, value: object) -> None:
    try:
        with path.open("wb") as stream:
            stream.write(canonical_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise V02WeightedError("ARTIFACT_WRITE_FAILED") from None


def _fingerprint_order(values: Iterable[object]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(canonical_json_bytes(value))
    return f"sha256:{digest.hexdigest()}"


def _write_checksums(root: Path) -> dict[str, str]:
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.name != "checksums.sha256"
    )
    checksums = {path.relative_to(root).as_posix(): _plain_sha(path) for path in files}
    target = root / "checksums.sha256"
    with target.open("w", encoding="ascii", newline="\n") as stream:
        for name, digest in checksums.items():
            stream.write(f"{digest}  {name}\n")
        stream.flush()
        os.fsync(stream.fileno())
    return checksums


def _validate_checksums(root: Path) -> dict[str, str]:
    path = root / "checksums.sha256"
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError):
        raise V02WeightedError("CHECKSUM_RELOAD_FAILED") from None
    expected: dict[str, str] = {}
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            raise V02WeightedError("CHECKSUM_FORMAT_INVALID")
        digest, relative = line[:64], line[66:]
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise V02WeightedError("CHECKSUM_FORMAT_INVALID")
        candidate = (root / relative).resolve()
        if root.resolve() not in candidate.parents or relative in expected:
            raise V02WeightedError("CHECKSUM_FORMAT_INVALID")
        expected[relative] = digest
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "checksums.sha256"
    }
    if set(expected) != actual_files or any(_plain_sha(root / name) != digest for name, digest in expected.items()):
        raise V02WeightedError("CHECKSUM_MISMATCH")
    return expected


def write_safetensors_f64(path: Path, tensors: Mapping[str, Sequence[float]]) -> None:
    """Write the small subset of safetensors needed for deterministic F64 weights."""

    offset = 0
    header: dict[str, object] = {}
    payload = bytearray()
    for name in sorted(tensors):
        values = [float(value) for value in tensors[name]]
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise V02WeightedError("SAMPLING_WEIGHT_INVALID")
        encoded = struct.pack(f"<{len(values)}d", *values)
        header[name] = {"dtype": "F64", "shape": [len(values)], "data_offsets": [offset, offset + len(encoded)]}
        payload.extend(encoded)
        offset += len(encoded)
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    header_bytes += b" " * ((8 - len(header_bytes) % 8) % 8)
    with path.open("wb") as stream:
        stream.write(struct.pack("<Q", len(header_bytes)))
        stream.write(header_bytes)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def read_safetensors_f64(path: Path) -> dict[str, list[float]]:
    try:
        raw = path.read_bytes()
        header_length = struct.unpack("<Q", raw[:8])[0]
        header = json.loads(raw[8:8 + header_length])
    except (OSError, ValueError, struct.error, json.JSONDecodeError):
        raise V02WeightedError("WEIGHT_ARTIFACT_INVALID") from None
    payload = raw[8 + header_length:]
    result: dict[str, list[float]] = {}
    if not isinstance(header, dict):
        raise V02WeightedError("WEIGHT_ARTIFACT_INVALID")
    for name, metadata in header.items():
        if not isinstance(metadata, dict) or metadata.get("dtype") != "F64":
            raise V02WeightedError("WEIGHT_ARTIFACT_INVALID")
        shape, offsets = metadata.get("shape"), metadata.get("data_offsets")
        if not isinstance(shape, list) or len(shape) != 1 or not isinstance(offsets, list) or len(offsets) != 2:
            raise V02WeightedError("WEIGHT_ARTIFACT_INVALID")
        count, start, end = int(shape[0]), int(offsets[0]), int(offsets[1])
        if count < 0 or start < 0 or end != start + count * 8 or end > len(payload):
            raise V02WeightedError("WEIGHT_ARTIFACT_INVALID")
        result[str(name)] = list(struct.unpack(f"<{count}d", payload[start:end]))
    return result


class EpochWeightedSampler(Sampler[int]):
    """Weighted replacement sampler with an explicit epoch-derived seed."""

    def __init__(self, weights: Sequence[float], *, num_samples: int, base_seed: int = 42) -> None:
        values = torch.as_tensor(list(weights), dtype=torch.float64, device="cpu")
        if values.ndim != 1 or not len(values) or not torch.isfinite(values).all() or not torch.all(values > 0):
            raise V02WeightedError("SAMPLING_WEIGHT_INVALID")
        if num_samples <= 0 or base_seed < 0:
            raise V02WeightedError("SAMPLER_CONFIG_INVALID")
        self.weights = values
        self.num_samples = num_samples
        self.base_seed = base_seed
        self.epoch = 0

    def set_epoch(self, epoch: int) -> None:
        if epoch < 0:
            raise V02WeightedError("SAMPLER_EPOCH_INVALID")
        self.epoch = int(epoch)

    def draw_order(self) -> list[int]:
        generator = torch.Generator(device="cpu").manual_seed(self.base_seed + self.epoch)
        sampler = WeightedRandomSampler(
            self.weights,
            num_samples=self.num_samples,
            replacement=True,
            generator=generator,
        )
        return list(sampler)

    def draw_order_fingerprint(self) -> str:
        return checksum_value({"epoch": self.epoch, "seed": self.base_seed + self.epoch, "indices": self.draw_order()})

    def __iter__(self) -> Iterator[int]:
        return iter(self.draw_order())

    def __len__(self) -> int:
        return self.num_samples


def build_train_sampler(
    weights: Sequence[float], *, dataset_size: int, world_size: int, rank: int, base_seed: int = 42
) -> EpochWeightedSampler:
    if world_size != 1 or rank != 0:
        raise V02WeightedError("DISTRIBUTED_WEIGHTED_SAMPLING_UNSUPPORTED")
    if len(weights) != dataset_size:
        raise V02WeightedError("SAMPLING_WEIGHT_ALIGNMENT_INVALID")
    return EpochWeightedSampler(weights, num_samples=dataset_size, base_seed=base_seed)


def build_validation_sampler(dataset: Sequence[object]) -> SequentialSampler:
    return SequentialSampler(dataset)


class SidecarWeightedTrainerMixin:
    """Mixin for Transformers Trainer that changes only the train sampler.

    The runtime class must inherit from this mixin before ``transformers.Trainer``.
    Keeping Transformers out of this module preserves the model-free artifact path.
    """

    def __init__(self, *args: Any, train_sampling_weights: Sequence[float], sampling_base_seed: int = 42, **kwargs: Any) -> None:
        self._train_sampling_weights = tuple(float(value) for value in train_sampling_weights)
        self._sampling_base_seed = sampling_base_seed
        super().__init__(*args, **kwargs)  # type: ignore[misc]

    def _get_train_sampler(self, train_dataset: Any | None = None) -> Sampler[int] | None:
        selected = self.train_dataset if train_dataset is None else train_dataset  # type: ignore[attr-defined]
        if selected is None:
            return None
        world_size = int(getattr(self.args, "world_size", 1))  # type: ignore[attr-defined]
        rank = int(getattr(self.args, "process_index", 0))  # type: ignore[attr-defined]
        return build_train_sampler(
            self._train_sampling_weights,
            dataset_size=len(selected),
            world_size=world_size,
            rank=rank,
            base_seed=self._sampling_base_seed,
        )


def _load_hf_split(path: Path) -> Any:
    try:
        from datasets import load_from_disk
        return load_from_disk(str(path))
    except (ImportError, OSError, ValueError):
        raise V02WeightedError("TOKENIZED_DATASET_INVALID") from None


def _validate_token_row(row: Mapping[str, object], sidecar: Mapping[str, object]) -> dict[str, int]:
    if set(row) != {"input_ids", "attention_mask", "labels"}:
        raise V02WeightedError("TOKENIZED_SCHEMA_INVALID")
    input_ids, attention, labels = row["input_ids"], row["attention_mask"], row["labels"]
    if not all(isinstance(value, list) for value in (input_ids, attention, labels)):
        raise V02WeightedError("TOKENIZED_SCHEMA_INVALID")
    assert isinstance(input_ids, list) and isinstance(attention, list) and isinstance(labels, list)
    prompt_tokens = int(sidecar["prompt_tokens"])
    assistant_tokens = int(sidecar["assistant_tokens"])
    if (
        not input_ids or len(input_ids) != len(attention) or len(input_ids) != len(labels)
        or len(input_ids) != int(sidecar["total_tokens"])
        or len(input_ids) > MAX_SEQ_LENGTH
        or prompt_tokens + assistant_tokens != len(input_ids)
        or any(not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < VOCAB_SIZE for value in input_ids)
        or any(value != 1 for value in attention)
        or any(value != -100 for value in labels[:prompt_tokens])
        or any(value == -100 for value in labels[prompt_tokens:])
        or labels[-1] != EOS_TOKEN_ID
        or labels.count(EOS_TOKEN_ID) != 1
    ):
        raise V02WeightedError("TOKENIZATION_CONTRACT_INVALID")
    return {"total_tokens": len(input_ids), "assistant_tokens": assistant_tokens}


def _validate_source_package(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    expected_files = {
        "manifest.yaml", "quality-sidecar.jsonl", "review-queue.jsonl",
        "sampling-policy.yaml", "statistics.json", "train.jsonl",
        "validation.jsonl", "checksums.sha256",
    }
    if {path.name for path in root.iterdir()} != expected_files or any(path.is_symlink() for path in root.iterdir()):
        raise V02WeightedError("SOURCE_PACKAGE_INVALID")
    _validate_checksums(root)
    manifest = _read_yaml(root / "manifest.yaml")
    statistics_value = _read_json(root / "statistics.json")
    if not isinstance(manifest, dict) or not isinstance(statistics_value, dict):
        raise V02WeightedError("SOURCE_PACKAGE_INVALID")
    fingerprints = manifest.get("fingerprints")
    if (
        manifest.get("dataset_id") != DATASET_ID
        or not isinstance(fingerprints, dict)
        or str(fingerprints.get("package")) != f"sha256:{PACKAGE_FINGERPRINT}"
        or str(fingerprints.get("sidecar")) != f"sha256:{SIDECAR_FINGERPRINT}"
        or str(fingerprints.get("sampling_policy")) != f"sha256:{POLICY_FINGERPRINT}"
        or _plain_sha(root / "train.jsonl") != SOURCE_SHA256["train"]
        or _plain_sha(root / "validation.jsonl") != SOURCE_SHA256["validation"]
    ):
        raise V02WeightedError("SOURCE_PACKAGE_INVALID")
    sidecar = _read_jsonl(root / "quality-sidecar.jsonl")
    train = [value for value in sidecar if value.get("split") == "train"]
    validation = [value for value in sidecar if value.get("split") == "validation"]
    if len(train) != ROWS["train"] or len(validation) != ROWS["validation"]:
        raise V02WeightedError("SIDECAR_ALIGNMENT_INVALID")
    for split, values in (("train", train), ("validation", validation)):
        for index, value in enumerate(values):
            if value.get("line_index") != index or not isinstance(value.get("record_hash"), str):
                raise V02WeightedError("SIDECAR_ALIGNMENT_INVALID")
    return train, validation, statistics_value


def _validate_reuse_artifact(root: Path) -> tuple[Any, Any, dict[str, Any], dict[str, Any]]:
    checksums = _validate_checksums(root)
    result = _read_yaml(root / "tokenization-result.yaml")
    statistics_value = _read_json(root / "tokenization-statistics.json")
    config = _read_yaml(root / "tokenization-config.yaml")
    if not all(isinstance(value, dict) for value in (result, statistics_value, config)):
        raise V02WeightedError("REUSE_CONTRACT_INVALID")
    assert isinstance(result, dict) and isinstance(statistics_value, dict) and isinstance(config, dict)
    tokenization = config.get("tokenization")
    if (
        result.get("tokenization_run_id") != SOURCE_TOKENIZATION_ID
        or result.get("tokenizer_fingerprint") != TOKENIZER_FINGERPRINT
        or result.get("dataset_fingerprint") != DATASET_FINGERPRINT
        or result.get("source_checksums", {}).get("train.jsonl") != SOURCE_SHA256["train"]
        or result.get("source_checksums", {}).get("validation.jsonl") != SOURCE_SHA256["validation"]
        or not isinstance(tokenization, dict)
        or tokenization.get("max_seq_length") != MAX_SEQ_LENGTH
        or tokenization.get("packing") is not False
        or tokenization.get("assistant_only_loss") is not True
        or statistics_value.get("truncation", {}).get("records") != 0
        or len(checksums) != 9
    ):
        raise V02WeightedError("REUSE_CONTRACT_INVALID")
    return _load_hf_split(root / "train"), _load_hf_split(root / "validation"), result, statistics_value


def _copy_tree_durable(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination)
    for path in destination.rglob("*"):
        if path.is_file():
            with path.open("r+b") as stream:
                os.fsync(stream.fileno())
    for directory in sorted((path for path in destination.rglob("*") if path.is_dir()), reverse=True):
        _fsync_directory(directory)
    _fsync_directory(destination)


def _generation_subset(train_sidecar: Sequence[Mapping[str, object]], count: int = 20) -> list[str]:
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for value in train_sidecar:
        groups[(str(value.get("category")), str(value["length_bucket"]))].append(str(value["record_hash"]))
    for values in groups.values():
        values.sort()
    selected: list[str] = []
    keys = sorted(groups)
    cursor = 0
    while len(selected) < count and keys:
        key = keys[cursor % len(keys)]
        values = groups[key]
        if values:
            selected.append(values.pop(0))
        else:
            keys.remove(key)
            cursor -= 1
        cursor += 1
    if len(selected) != count:
        raise V02WeightedError("GENERATION_SUBSET_INVALID")
    return selected


def build_v02_tokenized_package(*, source_root: Path, reuse_root: Path, output_root: Path, git_head: str) -> dict[str, object]:
    if output_root.exists() or list(output_root.parent.glob(f".{output_root.name}.staging-*")):
        raise V02WeightedError("OUTPUT_ID_ALREADY_USED")
    train_sidecar, validation_sidecar, source_statistics = _validate_source_package(source_root)
    train_dataset, validation_dataset, reuse_result, reuse_statistics = _validate_reuse_artifact(reuse_root)
    if len(train_dataset) != len(train_sidecar) or len(validation_dataset) != len(validation_sidecar):
        raise V02WeightedError("ROW_COUNT_MISMATCH")
    token_order: dict[str, str] = {}
    token_stats: dict[str, dict[str, int | float]] = {}
    for split, dataset, sidecar in (
        ("train", train_dataset, train_sidecar),
        ("validation", validation_dataset, validation_sidecar),
    ):
        row_digests: list[str] = []
        total_lengths: list[int] = []
        assistant_lengths: list[int] = []
        for row, metadata in zip(dataset, sidecar, strict=True):
            values = _validate_token_row(row, metadata)
            row_digests.append(checksum_value(dict(row)))
            total_lengths.append(values["total_tokens"])
            assistant_lengths.append(values["assistant_tokens"])
        token_order[split] = _fingerprint_order(row_digests)
        token_stats[split] = {
            "rows": len(total_lengths), "total_tokens": sum(total_lengths),
            "assistant_tokens": sum(assistant_lengths), "minimum_length": min(total_lengths),
            "maximum_length": max(total_lengths), "mean_length": round(statistics.fmean(total_lengths), 6),
        }
    combined = token_stats["train"]["total_tokens"] + token_stats["validation"]["total_tokens"]
    if combined != reuse_statistics.get("lengths", {}).get("total", {}).get("sum"):
        raise V02WeightedError("LENGTH_DISTRIBUTION_MISMATCH")
    train_weights = [float(value["sampling_weight"]) for value in train_sidecar]
    validation_weights = [float(value["sampling_weight"]) for value in validation_sidecar]
    mean = statistics.fmean(train_weights)
    ess = sum(train_weights) ** 2 / sum(value * value for value in train_weights)
    if (
        not math.isclose(mean, 1.0, abs_tol=1e-12)
        or not math.isclose(ess / len(train_weights), 0.6389483441895093, abs_tol=1e-12)
        or any(value != 1.0 for value in validation_weights)
    ):
        raise V02WeightedError("SAMPLING_WEIGHT_INVALID")
    order = {
        "train_record_order_fingerprint": _fingerprint_order(value["record_hash"] for value in train_sidecar),
        "validation_record_order_fingerprint": _fingerprint_order(value["record_hash"] for value in validation_sidecar),
        "sidecar_order_fingerprint": _fingerprint_order(value["record_hash"] for value in (*train_sidecar, *validation_sidecar)),
        "tokenized_order_fingerprint": checksum_value(token_order),
        "weight_order_fingerprint": _fingerprint_order(
            {"record_hash": value["record_hash"], "sampling_weight": value["sampling_weight"]}
            for value in train_sidecar
        ),
    }
    alignment = {"schema_version": 1, "train_rows": len(train_sidecar), "validation_rows": len(validation_sidecar), **order, "alignment_valid": True}
    sampling_metadata = {
        "schema_version": 1, "replacement": True, "draws_per_epoch": len(train_sidecar),
        "base_seed": 42, "epoch_seed_formula": "base_seed + epoch_index", "world_size": 1, "rank": 0,
        "weight_dtype": "float64", "weight_serialization": "safetensors-f64-little-endian-v1",
        "train_weight_statistics": {"min": min(train_weights), "mean": mean, "max": max(train_weights), "effective_sample_size": ess, "effective_sample_size_ratio": ess / len(train_weights)},
        "validation_weight_statistics": {"min": 1.0, "mean": 1.0, "max": 1.0},
        "validation_policy": {"sampler": "sequential", "weighted": False, "shuffle": False},
        "generation_evaluation_subset": {"count": 20, "record_hashes": _generation_subset(train_sidecar), "category_balanced": True, "length_balanced": True, "deterministic": True},
        "training_started": False, "optimizer_steps": 0,
    }
    statistics_output = {
        "schema_version": 1, "rows": {**ROWS, "total": sum(ROWS.values())}, "tokens": token_stats,
        "truncation": {"records": 0, "assistant_records": 0}, "prompt_trainable_labels": 0,
        "assistant_masked_labels": 0, "eos_contract_valid": True, "packing": False,
        "max_seq_length": MAX_SEQ_LENGTH, "source_length_distribution_fingerprint": reuse_result["length_distribution_fingerprint"],
    }
    manifest_semantic = {
        "schema_version": 1, "tokenization_id": TOKENIZATION_ID, "mode": "verified_byte_reuse",
        "source": {"dataset_id": DATASET_ID, "package_fingerprint": f"sha256:{PACKAGE_FINGERPRINT}", "dataset_fingerprint": DATASET_FINGERPRINT, "jsonl_checksums": SOURCE_SHA256, "sidecar_fingerprint": f"sha256:{SIDECAR_FINGERPRINT}", "sampling_policy_fingerprint": f"sha256:{POLICY_FINGERPRINT}"},
        "reuse": {"tokenization_id": SOURCE_TOKENIZATION_ID, "artifact_fingerprint": "f626e00c2c4cfc065623f857e4655865f793fc8781a319200bc81bb0489d6045", "token_fingerprints": reuse_result["token_fingerprints"], "byte_identical": True},
        "tokenizer": {"model": "Qwen/Qwen2.5-1.5B-Instruct", "revision": "989aa7980e4cf806f80c7fef2b1adb7bc71aa306", "fingerprint": TOKENIZER_FINGERPRINT, "eos_token_id": EOS_TOKEN_ID, "pad_token_id": 151643},
        "contract": {"max_seq_length": MAX_SEQ_LENGTH, "packing": False, "dynamic_padding": True, "assistant_only_loss": True, "row_order_preserved": True},
        "lineage": {"git_head": git_head}, "training_allowed": False, "training_started": False, "execution_allowed": False,
    }
    manifest = {**manifest_semantic, "fingerprints": {"manifest": checksum_value(manifest_semantic), "alignment": checksum_value(alignment), "sampling_metadata": checksum_value(sampling_metadata), "statistics": checksum_value(statistics_output)}}
    atomic = AtomicArtifactDirectory(output_root)
    try:
        with atomic as staging:
            _copy_tree_durable(reuse_root / "train", staging / "train")
            _copy_tree_durable(reuse_root / "validation", staging / "validation")
            write_safetensors_f64(staging / "sampling-weights.safetensors", {"train": train_weights, "validation": validation_weights})
            _write_json_durable(staging / "row-alignment.json", alignment)
            write_yaml(staging / "tokenization-manifest.yaml", manifest)
            _write_json_durable(staging / "tokenization-statistics.json", statistics_output)
            _write_json_durable(staging / "sampling-metadata.json", sampling_metadata)
            _write_checksums(staging)
            validate_v02_tokenized_package(staging)
            atomic.publish()
    except Exception:
        raise
    result = validate_v02_tokenized_package(output_root)
    return {"output": str(output_root), **result}


def validate_v02_tokenized_package(root: Path) -> dict[str, object]:
    checksums = _validate_checksums(root)
    expected_top = {"train", "validation", "sampling-weights.safetensors", "row-alignment.json", "tokenization-manifest.yaml", "tokenization-statistics.json", "sampling-metadata.json", "checksums.sha256"}
    if {path.name for path in root.iterdir()} != expected_top or any(path.is_symlink() for path in root.rglob("*")):
        raise V02WeightedError("PACKAGE_FILE_SET_INVALID")
    manifest = _read_yaml(root / "tokenization-manifest.yaml")
    alignment = _read_json(root / "row-alignment.json")
    metadata = _read_json(root / "sampling-metadata.json")
    statistics_value = _read_json(root / "tokenization-statistics.json")
    weights = read_safetensors_f64(root / "sampling-weights.safetensors")
    if (
        not isinstance(manifest, dict) or manifest.get("tokenization_id") != TOKENIZATION_ID
        or manifest.get("training_started") is not False or manifest.get("execution_allowed") is not False
        or not isinstance(alignment, dict) or alignment.get("alignment_valid") is not True
        or len(weights.get("train", [])) != ROWS["train"] or len(weights.get("validation", [])) != ROWS["validation"]
        or any(value != 1.0 for value in weights["validation"])
        or metadata.get("optimizer_steps") != 0 or statistics_value.get("truncation", {}).get("records") != 0
    ):
        raise V02WeightedError("PACKAGE_CONSISTENCY_INVALID")
    artifact_fingerprint = checksum_value({"algorithm": "ordered-file-checksums-v1", "files": sorted(checksums.items())})
    return {"tokenization_id": TOKENIZATION_ID, "artifact_fingerprint": artifact_fingerprint, "checksums": checksums, "rows": ROWS, "tokens": statistics_value["tokens"], "alignment": alignment, "sampling": metadata}


def simulate_sampling(*, tokenized_root: Path, sidecar_root: Path, output_root: Path, git_head: str, epochs: int = 10) -> dict[str, object]:
    if output_root.exists() or list(output_root.parent.glob(f".{output_root.name}.staging-*")):
        raise V02WeightedError("OUTPUT_ID_ALREADY_USED")
    tokenized = validate_v02_tokenized_package(tokenized_root)
    train, _, source_statistics = _validate_source_package(sidecar_root)
    weights = read_safetensors_f64(tokenized_root / "sampling-weights.safetensors")["train"]
    epoch_values: list[dict[str, object]] = []
    aggregate_indices: list[int] = []
    for epoch in range(epochs):
        sampler = EpochWeightedSampler(weights, num_samples=len(train), base_seed=42)
        sampler.set_epoch(epoch)
        indices = sampler.draw_order()
        aggregate_indices.extend(indices)
        counts = Counter(indices)
        lengths = [int(train[index]["total_tokens"]) for index in indices]
        assistants = [int(train[index]["assistant_tokens"]) for index in indices]
        epoch_values.append({
            "epoch": epoch, "seed": 42 + epoch, "draws": len(indices), "draw_order_fingerprint": sampler.draw_order_fingerprint(),
            "unique_rows": len(counts), "coverage_ratio": len(counts) / len(train), "duplicate_draws": len(indices) - len(counts),
            "unsampled_rows": len(train) - len(counts), "maximum_single_record_draws": max(counts.values()),
            "p95_draw_count": _percentile(list(counts.values()), 95), "p99_draw_count": _percentile(list(counts.values()), 99),
            "total_tokens": sum(lengths), "assistant_tokens": sum(assistants), "mean_sequence_length": statistics.fmean(lengths),
        })
    aggregate = [train[index] for index in aggregate_indices]
    length_counts = Counter(str(value["length_bucket"]) for value in aggregate)
    category_counts = Counter(str(value.get("category")) for value in aggregate)
    expected_length = source_statistics["sampling"]["expected_length_distribution"]
    expected_category = source_statistics["sampling"]["expected_category_distribution"]
    simulated_length = {key: length_counts[key] / len(aggregate) for key in sorted(expected_length)}
    simulated_category = {key: category_counts[key] / len(aggregate) for key in sorted(expected_category)}
    length_deviation = {key: abs(simulated_length[key] - float(expected_length[key])) for key in expected_length}
    category_deviation = {key: abs(simulated_category[key] - float(expected_category[key])) for key in expected_category}
    quality = {
        "completion_score": _ratio_counts(aggregate, "completion_score"),
        "repetition_score": _ratio_counts(aggregate, "repetition_score"),
        "review_required": _ratio_counts(aggregate, "review_required"),
        "near_duplicate_participant": _ratio_counts(aggregate, "is_near_duplicate_participant"),
        "ambiguous_category": _ratio_counts(aggregate, "category_status"),
    }
    coverage = {
        "mean_unique_rows": statistics.fmean(int(value["unique_rows"]) for value in epoch_values),
        "mean_coverage_ratio": statistics.fmean(float(value["coverage_ratio"]) for value in epoch_values),
        "mean_duplicate_draws": statistics.fmean(int(value["duplicate_draws"]) for value in epoch_values),
        "mean_unsampled_rows": statistics.fmean(int(value["unsampled_rows"]) for value in epoch_values),
        "maximum_single_record_draws": max(int(value["maximum_single_record_draws"]) for value in epoch_values),
        "coverage_warning_threshold": 0.45, "maximum_draw_warning_threshold": 12,
    }
    token_budget = {
        "v01_original_epoch_total_tokens": int(tokenized["tokens"]["train"]["total_tokens"]),
        "weighted_mean_epoch_total_tokens": statistics.fmean(int(value["total_tokens"]) for value in epoch_values),
        "weighted_mean_epoch_assistant_tokens": statistics.fmean(int(value["assistant_tokens"]) for value in epoch_values),
        "difference_total_tokens": statistics.fmean(int(value["total_tokens"]) for value in epoch_values) - int(tokenized["tokens"]["train"]["total_tokens"]),
    }
    passed = max(length_deviation.values()) <= 0.015 and max(category_deviation.values()) <= 0.015
    aggregate_metrics = {
        "schema_version": 1, "simulation_id": SIMULATION_ID, "epochs": epochs,
        "draws_per_epoch": len(train), "total_draws": len(aggregate), "base_seed": 42,
        "maximum_length_deviation": max(length_deviation.values()), "maximum_category_deviation": max(category_deviation.values()),
        "expected_distribution_match": passed, "coverage_valid": coverage["mean_coverage_ratio"] >= 0.45,
        "maximum_draws_valid": coverage["maximum_single_record_draws"] <= 12,
        "training_started": False, "optimizer_steps": 0,
    }
    if not passed:
        raise V02WeightedError("SIMULATION_DISTRIBUTION_INVALID")
    config = {"schema_version": 1, "simulation_id": SIMULATION_ID, "tokenization_id": TOKENIZATION_ID, "epochs": epochs, "draws_per_epoch": len(train), "base_seed": 42, "git_head": git_head, "model_loaded": False, "token_payload_read": False}
    atomic = AtomicArtifactDirectory(output_root)
    with atomic as staging:
        write_yaml(staging / "simulation-config.yaml", config)
        write_jsonl(staging / "epoch-metrics.jsonl", epoch_values)
        _write_json_durable(staging / "aggregate-metrics.json", aggregate_metrics)
        _write_json_durable(staging / "length-distribution.json", {"original": source_statistics["length_bucket_actual"], "expected": expected_length, "simulated": simulated_length, "absolute_deviation": length_deviation})
        _write_json_durable(staging / "category-distribution.json", {"original": source_statistics["category_actual_train"], "expected": expected_category, "simulated": simulated_category, "absolute_deviation": category_deviation})
        _write_json_durable(staging / "quality-distribution.json", quality)
        _write_json_durable(staging / "coverage-metrics.json", coverage)
        _write_json_durable(staging / "token-budget.json", token_budget)
        _write_checksums(staging)
        _validate_simulation_package(staging)
        atomic.publish()
    verified = _validate_simulation_package(output_root)
    return {"output": str(output_root), **verified}


def _percentile(values: Sequence[int], percentage: int) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percentage / 100) - 1)]


def _ratio_counts(values: Sequence[Mapping[str, object]], field: str) -> dict[str, float]:
    counts = Counter(str(value.get(field)) for value in values)
    return {key: count / len(values) for key, count in sorted(counts.items())}


def _validate_simulation_package(root: Path) -> dict[str, object]:
    expected = {"simulation-config.yaml", "epoch-metrics.jsonl", "aggregate-metrics.json", "length-distribution.json", "category-distribution.json", "quality-distribution.json", "coverage-metrics.json", "token-budget.json", "checksums.sha256"}
    if {path.name for path in root.iterdir()} != expected or any(path.is_symlink() for path in root.iterdir()):
        raise V02WeightedError("SIMULATION_FILE_SET_INVALID")
    checksums = _validate_checksums(root)
    config, aggregate, epochs = _read_yaml(root / "simulation-config.yaml"), _read_json(root / "aggregate-metrics.json"), _read_jsonl(root / "epoch-metrics.jsonl")
    if not isinstance(config, dict) or config.get("simulation_id") != SIMULATION_ID or len(epochs) != 10 or aggregate.get("expected_distribution_match") is not True or aggregate.get("training_started") is not False:
        raise V02WeightedError("SIMULATION_CONSISTENCY_INVALID")
    return {"simulation_id": SIMULATION_ID, "artifact_fingerprint": checksum_value({"algorithm": "ordered-file-checksums-v1", "files": sorted(checksums.items())}), "checksums": checksums, "aggregate": aggregate}
