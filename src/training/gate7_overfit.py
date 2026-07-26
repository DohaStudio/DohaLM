"""Fail-closed Gate 7 preparation and bounded real-corpus Tiny overfit."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import shutil
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import torch
import yaml

from src.data.aihub_71748_tokenizer_corpus import (
    CorpusBuildConfig,
    _DataInfoArrayStream,
    _eligible_archives,
    resolve_local_paths,
    verify_existing_tokenizer_corpus,
)
from src.data.checksums import canonical_json_bytes, checksum_value, file_checksum
from src.data.normalization import normalize_text
from src.data.sequence_packing import PackingPolicy, pack_sequences
from src.data.tokenized_dataset import TokenizedJsonlDataset
from src.model import DohaLMTiny, ModelConfig
from src.runtime.paths import resolve_repository_path
from src.tokenizer import DohaTokenizer
from src.tokenizer.operating import validate_operating_candidate

from .checkpoint import CheckpointManager
from .collator import CausalLMCollator
from .config import TrainingConfig
from .dataloader import create_dataloader
from .errors import TrainingError
from .trainer import Trainer, seed_everything


EXPECTED_TOKENIZER = "sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff"
EXPECTED_MODEL = "sha256:11e536f275b9377794a52c8f3f5fadfe358f631c4b7af51bf9e371d2124fff0a"
EXPECTED_VOCAB = "sha256:9030a0cdc2fba938ac2a3fc8d0f7ae259d22b30ab22a2c57edb3d7cbcdfab11b"
EXPECTED_CORPUS = "sha256:2812606509281c9246c56c5bad2efbcf53897a105b75e1843d61b2101891f28c"
EXPECTED_CORPUS_SHA = "sha256:0c7119106261e9a8487b5e2e1ba76ba220761a2fdaeb14738e968b91fdbeeb00"
SPECIAL_IDS = {"<pad>": 0, "<unk>": 1, "<bos>": 2, "<eos>": 3, "<|system|>": 4, "<|user|>": 5, "<|assistant|>": 6, "<|end|>": 7}


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise TrainingError("GATE7_CONFIG_INVALID", f"YAML을 읽을 수 없습니다: {path.name}") from exc
    if not isinstance(value, dict):
        raise TrainingError("GATE7_CONFIG_INVALID", f"YAML root가 mapping이 아닙니다: {path.name}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _relative_path(name: str, value: str) -> None:
    raw = value.replace("\\", "/")
    if not raw or PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute() or ".." in PurePosixPath(raw).parts:
        raise TrainingError("GATE7_CONFIG_INVALID", f"{name}은 안전한 상대경로여야 합니다.")


@dataclass(frozen=True)
class Gate7OverfitConfig:
    local_dataset_config: str
    approval_manifest: str
    package_manifest: str
    checksum_inventory: str
    source_corpus: str
    tokenizer_bundle: str
    output_base: str
    document_count: int = 64
    sampling_seed: int = 7174807
    max_document_characters: int = 4096
    max_document_bytes: int = 16384
    context_length: int = 256
    packing_mode: str = "continuous"
    packing_remainder: str = "pad"
    micro_batch_size: int = 1
    gradient_accumulation_steps: int = 4
    max_steps: int = 500
    learning_rate: float = 1e-3
    weight_decay: float = 0.0
    warmup_steps: int = 10
    min_lr_ratio: float = 0.1
    max_grad_norm: float = 1.0
    seed: int = 17
    device: str = "cuda"
    use_amp: bool = True
    num_workers: int = 0
    pin_memory: bool = True
    generation_prefix_tokens: int = 16
    generation_target_tokens: int = 16

    def __post_init__(self) -> None:
        for name in ("local_dataset_config", "approval_manifest", "package_manifest", "checksum_inventory", "source_corpus", "tokenizer_bundle", "output_base"):
            _relative_path(name, getattr(self, name))
        integers = (self.document_count, self.sampling_seed, self.max_document_characters, self.max_document_bytes, self.context_length,
                    self.micro_batch_size, self.gradient_accumulation_steps, self.max_steps, self.warmup_steps, self.seed,
                    self.generation_prefix_tokens, self.generation_target_tokens)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in integers):
            raise TrainingError("GATE7_CONFIG_INVALID", "Gate 7 정수 설정이 유효하지 않습니다.")
        if not 1 <= self.document_count <= 64 or not 1 <= self.max_steps <= 500 or self.context_length != 256:
            raise TrainingError("GATE7_SCOPE_EXCEEDED", "문서 64개·500 step·context 256 상한을 위반했습니다.")
        if min(self.max_document_characters, self.max_document_bytes, self.micro_batch_size, self.gradient_accumulation_steps) <= 0:
            raise TrainingError("GATE7_CONFIG_INVALID", "크기와 batch 설정은 양수여야 합니다.")
        if self.packing_mode != "continuous" or self.packing_remainder != "pad":
            raise TrainingError("GATE7_CONFIG_INVALID", "Gate 7 packing은 continuous+pad로 고정합니다.")
        if self.device not in {"cpu", "cuda"} or self.use_amp != (self.device == "cuda"):
            raise TrainingError("GATE7_CONFIG_INVALID", "CUDA는 FP16 AMP, CPU는 AMP 비활성으로 사용해야 합니다.")
        if self.generation_prefix_tokens + self.generation_target_tokens > self.context_length:
            raise TrainingError("GATE7_CONFIG_INVALID", "generation 범위가 context를 초과합니다.")

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Gate7OverfitConfig":
        value = _load_yaml(Path(path))
        unknown = set(value) - set(cls.__dataclass_fields__)
        if unknown:
            raise TrainingError("GATE7_CONFIG_INVALID", f"알 수 없는 설정: {sorted(unknown)}")
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def training_config(self, *, run_id: str, attempt: str, save_every: int) -> TrainingConfig:
        return TrainingConfig(
            batch_size=self.micro_batch_size * self.gradient_accumulation_steps,
            micro_batch_size=self.micro_batch_size,
            gradient_accumulation_steps=self.gradient_accumulation_steps,
            max_steps=self.max_steps,
            learning_rate=self.learning_rate,
            weight_decay=self.weight_decay,
            warmup_steps=self.warmup_steps,
            scheduler_type="cosine",
            min_lr_ratio=self.min_lr_ratio,
            max_grad_norm=self.max_grad_norm,
            use_amp=self.use_amp,
            seed=self.seed,
            log_every=1,
            save_every=save_every,
            output_dir=f"artifacts/gate7-tiny-overfit/{run_id}/{attempt}",
            device=self.device,
            num_workers=self.num_workers,
            pin_memory=self.pin_memory,
        )


@dataclass(frozen=True)
class Gate7Paths:
    external_root: Path
    dataset_root: Path
    source_corpus: Path
    tokenizer_bundle: Path
    output_root: Path
    approval_manifest: Path
    package_manifest: Path
    checksum_inventory: Path


def resolve_gate7_paths(config: Gate7OverfitConfig, run_id: str) -> Gate7Paths:
    _relative_path("run_id", run_id)
    external_root, dataset_root = resolve_local_paths(resolve_repository_path(config.local_dataset_config))
    source = (external_root / config.source_corpus).resolve()
    bundle = (external_root / config.tokenizer_bundle).resolve()
    output = (external_root / config.output_base / run_id).resolve()
    for name, path in (("source", source), ("bundle", bundle), ("output", output)):
        if external_root not in path.parents:
            raise TrainingError("GATE7_PATH_INVALID", f"{name} 경로가 external_root 밖입니다.")
    return Gate7Paths(
        external_root,
        dataset_root,
        source,
        bundle,
        output,
        resolve_repository_path(config.approval_manifest),
        resolve_repository_path(config.package_manifest),
        resolve_repository_path(config.checksum_inventory),
    )


def _validate_approval(config: Gate7OverfitConfig, path: Path) -> dict[str, Any]:
    value = _load_yaml(path)
    approval = value.get("approval", {})
    limits = value.get("limits", {})
    identity = value.get("identity", {})
    restrictions = value.get("restrictions", {})
    if value.get("manifest_status") != "approved" or approval.get("purpose") != "gate7_tiny_overfit_only" or approval.get("approved_by") != "user":
        raise TrainingError("GATE7_NOT_APPROVED", "Gate 7 Tiny Overfit 목적 승인이 없습니다.")
    if identity != {"corpus_fingerprint": EXPECTED_CORPUS, "tokenizer_fingerprint": EXPECTED_TOKENIZER,
                    "model_sha256": EXPECTED_MODEL, "vocab_sha256": EXPECTED_VOCAB}:
        raise TrainingError("GATE7_IDENTITY_MISMATCH", "승인 artifact identity가 일치하지 않습니다.")
    if limits.get("document_count_max") != 64 or limits.get("step_max") != 500 or config.document_count > 64 or config.max_steps > 500:
        raise TrainingError("GATE7_SCOPE_EXCEEDED", "승인된 문서/step 상한을 초과했습니다.")
    required = {"pretraining": "not_approved", "gate7_status_change": "not_approved", "validation_use": "not_approved",
                "evaluation_benchmark_use": "not_approved", "redistribution": "not_approved"}
    if any(restrictions.get(key) != expected for key, expected in required.items()):
        raise TrainingError("GATE7_CONFIG_INVALID", "승인 manifest의 제한 조건이 불완전합니다.")
    return value


def _percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]


class _SelectionQuotaReached(Exception):
    pass


def _select_documents(dataset_root: Path, checksum_inventory: Path, config: Gate7OverfitConfig) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Select actual records while replaying the approved corpus-builder rules."""

    from scripts.datasets.json_record_stream import RECORD_OK, scan_json_array_records

    heap: list[tuple[int, int, dict[str, Any]]] = []
    seen: set[str] = set()
    counts = {"source_records": 0, "empty": 0, "duplicate": 0, "oversize": 0, "eligible": 0}
    build_config = CorpusBuildConfig()
    global_index = 0
    for archive in _eligible_archives(dataset_root, checksum_inventory):
        accepted = byte_count = 0
        with zipfile.ZipFile(archive["path"]) as zipped:
            entries = sorted(
                (item for item in zipped.infolist() if not item.is_dir() and item.filename.lower().endswith(".json")),
                key=lambda item: item.filename,
            )
            for entry in entries:
                if accepted >= build_config.records_per_archive or byte_count >= build_config.bytes_per_archive:
                    break
                with zipped.open(entry) as raw:
                    stream = _DataInfoArrayStream(raw)

                    def on_record(event: Any) -> None:
                        nonlocal accepted, byte_count, global_index
                        if event.status != RECORD_OK or not isinstance(event.value, dict):
                            return
                        value = event.value.get("contents")
                        if not isinstance(value, str):
                            return
                        try:
                            text = normalize_text(value)
                        except (UnicodeError, ValueError):
                            return
                        encoded = text.encode("utf-8")
                        identifier = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
                        if identifier in seen:
                            counts["duplicate"] += 1
                            return
                        payload_bytes = len(encoded) + 1
                        if accepted >= build_config.records_per_archive or byte_count + payload_bytes > build_config.bytes_per_archive:
                            raise _SelectionQuotaReached
                        seen.add(identifier)
                        accepted += 1
                        byte_count += payload_bytes
                        counts["source_records"] += 1
                        index = global_index
                        global_index += 1
                        if not text:
                            counts["empty"] += 1
                            return
                        if len(encoded) > config.max_document_bytes or len(text) > config.max_document_characters:
                            counts["oversize"] += 1
                            return
                        counts["eligible"] += 1
                        rank = int.from_bytes(hashlib.sha256(f"{config.sampling_seed}:{identifier}".encode("ascii")).digest(), "big")
                        row = {
                            "document_id": identifier,
                            "source_archive": archive["relative_path"],
                            "source_entry_sha256": f"sha256:{hashlib.sha256(entry.filename.encode('utf-8')).hexdigest()}",
                            "source_record_index": event.record_index,
                            "source_corpus_record_index": index,
                            "rank_sha256": f"sha256:{rank:064x}",
                            "text": text,
                        }
                        item = (-rank, -index, row)
                        if len(heap) < config.document_count:
                            heapq.heappush(heap, item)
                        elif item > heap[0]:
                            heapq.heapreplace(heap, item)

                    try:
                        scan_json_array_records(
                            stream,
                            max_record_bytes=build_config.max_record_bytes,
                            max_read_bytes=entry.file_size,
                            on_record=on_record,
                        )
                    except _SelectionQuotaReached:
                        break
                if accepted >= build_config.records_per_archive or byte_count >= build_config.bytes_per_archive:
                    break
    if len(heap) != config.document_count:
        raise TrainingError("GATE7_CORPUS_INVALID", "승인 상한을 만족하는 문서가 부족합니다.")
    selected = [item[2] for item in sorted(heap, key=lambda item: (-item[0], -item[1]))]
    return selected, counts


def prepare_gate7_overfit(config: Gate7OverfitConfig, run_id: str) -> dict[str, Any]:
    paths = resolve_gate7_paths(config, run_id)
    _validate_approval(config, paths.approval_manifest)
    if not paths.source_corpus.is_file() or not paths.tokenizer_bundle.is_dir():
        raise TrainingError("GATE7_ARTIFACT_MISSING", "corpus 또는 tokenizer bundle이 없습니다.")
    if file_checksum(paths.source_corpus) != EXPECTED_CORPUS_SHA:
        raise TrainingError("GATE7_CORPUS_MISMATCH", "source corpus checksum이 일치하지 않습니다.")
    tokenizer_report = validate_operating_candidate(paths.tokenizer_bundle)
    manifest = json.loads((paths.tokenizer_bundle / "tokenizer-manifest.json").read_text(encoding="utf-8"))
    if tokenizer_report.get("tokenizer_fingerprint") != EXPECTED_TOKENIZER or manifest.get("model_checksum") != EXPECTED_MODEL or manifest.get("vocab_checksum") != EXPECTED_VOCAB:
        raise TrainingError("GATE7_TOKENIZER_MISMATCH", "운영 tokenizer identity가 일치하지 않습니다.")
    if manifest.get("special_tokens") != SPECIAL_IDS:
        raise TrainingError("GATE7_TOKENIZER_MISMATCH", "special token ID가 일치하지 않습니다.")
    if paths.output_root.exists():
        raise TrainingError("GATE7_OUTPUT_EXISTS", "기존 run을 덮어쓸 수 없습니다.")
    paths.output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = paths.output_root.with_name(f".{paths.output_root.name}.staging-{os.getpid()}")
    staging.mkdir()
    try:
        corpus_verification = verify_existing_tokenizer_corpus(
            local_config=resolve_repository_path(config.local_dataset_config),
            package_manifest=paths.package_manifest,
            checksum_inventory=paths.checksum_inventory,
            corpus_dir=paths.source_corpus.parent,
        )
        if corpus_verification.get("corpus_fingerprint") != EXPECTED_CORPUS:
            raise TrainingError("GATE7_CORPUS_MISMATCH", "verified source corpus fingerprint does not match approval")
        selected, selection_counts = _select_documents(paths.dataset_root, paths.checksum_inventory, config)
        dataset_path = staging / "overfit-dataset.jsonl"
        with dataset_path.open("x", encoding="utf-8", newline="\n") as handle:
            for row in selected:
                handle.write(json.dumps({"document_id": row["document_id"], "text": row["text"]}, ensure_ascii=False, sort_keys=True) + "\n")
        selected_public = [{key: row[key] for key in ("document_id", "source_archive", "source_entry_sha256", "source_record_index", "source_corpus_record_index", "rank_sha256")} for row in selected]
        dataset_sha = file_checksum(dataset_path)
        dataset_fingerprint = checksum_value({"schema_version": "1.0", "source_corpus_fingerprint": EXPECTED_CORPUS,
                                              "sampling_seed": config.sampling_seed, "selected": selected_public,
                                              "limits": {"characters": config.max_document_characters, "bytes": config.max_document_bytes}})
        tokenizer = DohaTokenizer(paths.tokenizer_bundle / "tokenizer.model")
        token_rows: list[list[int]] = []
        lengths: list[int] = []
        unknown = out_of_range = empty = roundtrip_failures = 0
        tokenized_path = staging / "tokenized-documents.jsonl"
        with tokenized_path.open("x", encoding="utf-8", newline="\n") as handle:
            for row in selected:
                encoded = tokenizer.encode(row["text"], add_bos=True, add_eos=True)
                ids = encoded.ids
                unknown += ids.count(1)
                out_of_range += sum(not 0 <= token < 16_000 for token in ids)
                empty += int(not ids)
                roundtrip_failures += int(tokenizer.decode(ids, skip_special_tokens=True) != row["text"])
                lengths.append(len(ids))
                token_rows.append(ids)
                handle.write(json.dumps({"document_id": row["document_id"], "input_ids": ids}, sort_keys=True) + "\n")
        if unknown or out_of_range or empty or roundtrip_failures:
            raise TrainingError("GATE7_TOKENIZATION_INVALID", "UNK·범위·empty·round-trip 계약을 만족하지 못했습니다.")
        tokenized_sha = file_checksum(tokenized_path)
        tokenization_fingerprint = checksum_value({"dataset_fingerprint": dataset_fingerprint, "tokenizer_fingerprint": EXPECTED_TOKENIZER,
                                                   "bos": 2, "eos": 3, "tokenized_sha256": tokenized_sha})
        policy = PackingPolicy(context_length=config.context_length, mode=config.packing_mode, append_eos=False,
                               remainder=config.packing_remainder, eos_token_id=3, pad_token_id=0)
        packed = list(pack_sequences(token_rows, policy))
        packed_path = staging / "train.jsonl"
        padding_tokens = 0
        with packed_path.open("x", encoding="utf-8", newline="\n") as handle:
            for row in packed:
                padding_tokens += row["attention_mask"].count(0)
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        packed_sha = file_checksum(packed_path)
        valid_tokens = sum(sum(row["attention_mask"]) for row in packed)
        packing_fingerprint = checksum_value({"tokenization_fingerprint": tokenization_fingerprint, "policy": policy.to_dict(), "packed_sha256": packed_sha})
        dataset_manifest = {
            "schema_version": "1.0", "purpose": "gate7_tiny_overfit_only", "dataset_id": "AIHUB-71748",
            "source_split": "Training", "document_count": len(selected), "character_count": sum(len(row["text"]) for row in selected),
            "byte_count": sum(len(row["text"].encode("utf-8")) for row in selected), "sampling_seed": config.sampling_seed,
            "selection": selected_public, "selection_counts": selection_counts, "dataset_sha256": dataset_sha,
            "dataset_fingerprint": dataset_fingerprint, "source_corpus_fingerprint": EXPECTED_CORPUS,
            "source_corpus_sha256": EXPECTED_CORPUS_SHA, "tokenizer_fingerprint": EXPECTED_TOKENIZER,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "text_values_in_manifest": False,
        }
        token_manifest = {
            "schema_version": "1.0", "dataset_fingerprint": dataset_fingerprint, "tokenizer_fingerprint": EXPECTED_TOKENIZER,
            "tokenized_sha256": tokenized_sha, "tokenization_fingerprint": tokenization_fingerprint, "document_count": len(token_rows),
            "token_count": sum(lengths), "unknown_token_count": unknown, "out_of_range_count": out_of_range, "empty_sequence_count": empty,
            "roundtrip_failure_count": roundtrip_failures, "bos_policy": "prepend_id_2", "eos_policy": "append_id_3",
            "truncation": False, "length": {"min": min(lengths), "max": max(lengths), "p50": _percentile(lengths, .5),
                                                   "p90": _percentile(lengths, .9), "p95": _percentile(lengths, .95), "p99": _percentile(lengths, .99)},
        }
        packing_manifest = {
            "schema_version": "1.0", "tokenization_fingerprint": tokenization_fingerprint, "packing_fingerprint": packing_fingerprint,
            "packed_sha256": packed_sha, "policy": policy.to_dict(), "sequence_count": len(packed), "valid_token_count": valid_tokens,
            "padding_token_count": padding_tokens, "dropped_token_count": 0,
            "utilization": valid_tokens / (len(packed) * config.context_length), "document_boundary": "bos_2_eos_3_markers_in_continuous_stream",
            "attention_mask_verified": True, "labels_shift_owner": "model_causal_language_modeling_loss", "last_incomplete_block": "pad_ignore_index_-100",
        }
        _write_json(staging / "dataset-manifest.json", dataset_manifest)
        _write_json(staging / "tokenization-manifest.json", token_manifest)
        _write_json(staging / "packing-manifest.json", packing_manifest)
        _write_json(staging / "run-config-resolved.json", {"config": config.to_dict(), "config_fingerprint": checksum_value(config.to_dict()),
                                                             "logical_external_root": "configured_external_root", "run_id": run_id})
        os.replace(staging, paths.output_root)
        return {"status": "prepared", "run_id": run_id, "output": f"configured_external_root/{config.output_base}/{run_id}",
                "dataset": dataset_manifest, "tokenization": token_manifest, "packing": packing_manifest}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _load_prepared(config: Gate7OverfitConfig, run_id: str) -> tuple[Gate7Paths, dict[str, Any], dict[str, Any], dict[str, Any]]:
    paths = resolve_gate7_paths(config, run_id)
    _validate_approval(config, paths.approval_manifest)
    try:
        dataset = json.loads((paths.output_root / "dataset-manifest.json").read_text(encoding="utf-8"))
        tokenization = json.loads((paths.output_root / "tokenization-manifest.json").read_text(encoding="utf-8"))
        packing = json.loads((paths.output_root / "packing-manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrainingError("GATE7_ARTIFACT_MISSING", "준비 manifest를 읽을 수 없습니다.") from exc
    if dataset.get("dataset_sha256") != file_checksum(paths.output_root / "overfit-dataset.jsonl"):
        raise TrainingError("GATE7_DATASET_MISMATCH", "overfit dataset checksum이 일치하지 않습니다.")
    if tokenization.get("tokenized_sha256") != file_checksum(paths.output_root / "tokenized-documents.jsonl"):
        raise TrainingError("GATE7_DATASET_MISMATCH", "tokenized document checksum이 일치하지 않습니다.")
    if packing.get("packed_sha256") != file_checksum(paths.output_root / "train.jsonl"):
        raise TrainingError("GATE7_DATASET_MISMATCH", "packed dataset checksum이 일치하지 않습니다.")
    if dataset.get("tokenizer_fingerprint") != EXPECTED_TOKENIZER or dataset.get("document_count") != config.document_count:
        raise TrainingError("GATE7_IDENTITY_MISMATCH", "prepared lineage가 config와 일치하지 않습니다.")
    validate_operating_candidate(paths.tokenizer_bundle)
    return paths, dataset, tokenization, packing


def _generation_metrics(model: DohaLMTiny, tokenized_path: Path, config: Gate7OverfitConfig, device: torch.device) -> dict[str, Any]:
    first = json.loads(tokenized_path.open("r", encoding="utf-8").readline())
    ids = [token for token in first["input_ids"] if token not in {0}]
    prefix_len = min(config.generation_prefix_tokens, max(1, len(ids) - config.generation_target_tokens))
    target = ids[prefix_len: prefix_len + config.generation_target_tokens]
    prefix = ids[:prefix_len]
    model.eval()
    input_ids = torch.tensor([prefix], dtype=torch.long, device=device)
    generated = model.generate(input_ids, max_new_tokens=len(target), eos_token_id=3)[0].detach().cpu().tolist()[prefix_len:]
    compared = min(len(generated), len(target))
    accuracy = sum(generated[index] == target[index] for index in range(compared)) / max(1, len(target))
    exact = generated == target
    full = torch.tensor([prefix + target], dtype=torch.long, device=device)
    labels = full.clone()
    labels[:, :prefix_len] = -100
    with torch.no_grad(), torch.amp.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
        loss = model(full, labels=labels).loss
    return {"prefix_token_count": prefix_len, "target_token_count": len(target), "generated_token_count": len(generated),
            "exact_continuation_match": exact, "token_accuracy": accuracy, "continuation_loss": float(loss.detach().float().cpu().item()),
            "adjacent_repeat_count": sum(generated[i] == generated[i - 1] for i in range(1, len(generated))),
            "eos_generated": 3 in generated, "special_token_exposure_count": sum(token < 8 for token in generated), "text_values_stored": False}


def run_gate7_training(config: Gate7OverfitConfig, run_id: str, *, target_steps: int, save_every: int,
                       attempt: str = "training", resume_checkpoint: str | None = None) -> dict[str, Any]:
    if not 1 <= target_steps <= config.max_steps or not 1 <= save_every <= target_steps:
        raise TrainingError("GATE7_SCOPE_EXCEEDED", "target/save step이 승인 범위를 벗어났습니다.")
    _relative_path("attempt", attempt)
    paths, dataset_manifest, _, _ = _load_prepared(config, run_id)
    training_config = config.training_config(run_id=run_id, attempt=attempt, save_every=save_every)
    seed_everything(config.seed)
    dataset = TokenizedJsonlDataset(paths.output_root / "train.jsonl", context_length=config.context_length, vocab_size=16_000)
    loader = create_dataloader(dataset, CausalLMCollator(context_length=config.context_length), training_config,
                               shuffle=True, stateful=True, dataset_fingerprint=dataset_manifest["dataset_fingerprint"])
    model = DohaLMTiny(ModelConfig())
    output_root = paths.output_root / attempt
    resume = resume_checkpoint is not None
    trainer = Trainer(model=model, dataloader=loader, config=training_config, dataset_fingerprint=dataset_manifest["dataset_fingerprint"],
                      tokenizer_fingerprint=EXPECTED_TOKENIZER, output_root=output_root,
                      dataset_metadata={"kind": "gate7-real-corpus-overfit-v1", "dataset_id": "AIHUB-71748", "document_count": config.document_count,
                                        "dataset_fingerprint": dataset_manifest["dataset_fingerprint"], "tokenizer_fingerprint": EXPECTED_TOKENIZER,
                                        "local_experiment_only": True, "pretraining_allowed": False}, resume=resume,
                      metric_filename="gate7-training-metrics.jsonl")
    previous_loss = None
    if resume:
        checkpoint_name = Path(resume_checkpoint or "").name
        if checkpoint_name != resume_checkpoint or not checkpoint_name.startswith("checkpoint-"):
            raise TrainingError("GATE7_PATH_INVALID", "resume checkpoint는 단순 checkpoint 이름이어야 합니다.")
        checkpoint = output_root / checkpoint_name
        CheckpointManager.inspect(checkpoint)
        state_doc = json.loads((checkpoint / "training-state.json").read_text(encoding="utf-8"))
        previous_loss = state_doc["state"].get("last_loss")
        trainer.resume_from(checkpoint)
    before = _generation_metrics(trainer.model, paths.output_root / "tokenized-documents.jsonl", config, trainer.device)
    started = time.perf_counter()
    result = trainer.train(target_steps=target_steps)
    elapsed = time.perf_counter() - started
    after = _generation_metrics(trainer.model, paths.output_root / "tokenized-documents.jsonl", config, trainer.device)
    checkpoint = output_root / f"checkpoint-{target_steps}"
    inspection = CheckpointManager.inspect(checkpoint).to_dict() if checkpoint.is_dir() else None
    checkpoint_bytes = sum(item.stat().st_size for item in checkpoint.iterdir() if item.is_file()) if checkpoint.is_dir() else 0
    metrics = [item.to_dict() for item in result.metrics]
    losses = [item["loss"] for item in metrics]
    cpu_rss = None
    try:
        import psutil
        cpu_rss = psutil.Process().memory_info().rss
    except ImportError:
        pass
    summary = {
        "status": "completed_gate7_tiny_overfit_segment", "gate_effect": "none", "pretraining_effect": "none", "run_id": run_id,
        "attempt": attempt, "resumed_from": resume_checkpoint, "start_step": target_steps - len(metrics), "final_step": result.state.global_step,
        "elapsed_seconds": elapsed, "initial_loss": losses[0], "minimum_loss": min(losses), "final_loss": losses[-1],
        "loss_reduction_ratio": (losses[0] - losses[-1]) / losses[0], "final_perplexity": math.exp(min(losses[-1], 80.0)),
        "nonfinite_count": 0, "mean_tokens_per_second": sum(item["tokens_per_second"] for item in metrics) / len(metrics),
        "mean_step_time_seconds": sum(item["step_time"] for item in metrics) / len(metrics),
        "peak_vram_allocated_bytes": max(item["peak_memory_allocated"] for item in metrics),
        "peak_vram_reserved_bytes": max(item["peak_memory_reserved"] for item in metrics), "cpu_rss_bytes": cpu_rss,
        "checkpoint": inspection, "checkpoint_bytes": checkpoint_bytes, "checkpoint_save_seconds": trainer.checkpoints.last_save_seconds,
        "resume_loss_previous": previous_loss, "resume_first_loss": losses[0] if resume else None,
        "resume_loss_relative_delta": abs(losses[0] - previous_loss) / previous_loss if resume and previous_loss else None,
        "generation_before": before, "generation_after": after,
        "dataset_fingerprint": dataset_manifest["dataset_fingerprint"], "tokenizer_fingerprint": EXPECTED_TOKENIZER,
        "training_config_fingerprint": training_config.fingerprint(), "training_resume_fingerprint": training_config.resume_fingerprint(),
        "python": sys.version.split()[0], "torch": torch.__version__, "cuda": torch.version.cuda, "device": str(trainer.device),
    }
    _write_json(output_root / f"segment-summary-{target_steps}.json", summary)
    return summary
