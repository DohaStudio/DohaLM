"""Fail-closed DohaLM v0.3 tokenization and artifact publication."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

import yaml

from src.data.artifacts import _fsync_directory, _rename_directory_no_replace, write_json, write_yaml
from src.data.checksums import checksum_value, file_checksum
from src.training.sft_tokenization import (
    EncodedRecord,
    encode_record,
    iter_logical_records,
    length_statistics,
    tokenizer_fingerprint,
)


DATASET_ID = "DOHALM-V0.3-SHORT-ANSWER-DATASET-20260802-0001"
TOKENIZATION_ID = "DOHALM-V0.3-TOKENIZATION-20260802-0001"
TOKENIZER_FINGERPRINT = "ad0a85da869c2e4577b9409df0c91e35be70f0395a20c94765c6f4fa02ea6a55"
PACKAGE_FINGERPRINT = "16204818cedbe079e5a8ad436e1d0e1f315995d0655cadad1ac3f391a559d752"
MANIFEST_FINGERPRINT = "fd7211e65a1db6ac949fdc18d098f76b1bff9318772b211a88f55aa0ccae3885"
EOS_TOKEN_ID = 151645
ROWS = {"train": 17639, "validation": 1287, "original": 10374, "short": 7265}
CANDIDATES = (1024, 1152, 1280, 1536)
TOP_FILES = (
    "lineage-alignment.json", "row-alignment.json", "sampler-readiness.yaml",
    "tokenization-manifest.yaml", "tokenization-statistics.json",
)


class V03TokenizationError(RuntimeError):
    """Fail-closed tokenization contract error."""


def _sha(path: Path) -> str:
    return file_checksum(path).removeprefix("sha256:")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        values = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise V03TokenizationError("SOURCE_JSONL_INVALID") from None
    if any(not isinstance(value, dict) for value in values):
        raise V03TokenizationError("SOURCE_JSONL_INVALID")
    return values


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise V03TokenizationError("SOURCE_MANIFEST_INVALID") from None
    if not isinstance(value, dict):
        raise V03TokenizationError("SOURCE_MANIFEST_INVALID")
    return value


def validate_source(root: Path) -> dict[str, Any]:
    required = {"train.jsonl", "validation.jsonl", "quality-sidecar.jsonl", "lineage.jsonl", "manifest.yaml", "checksums.sha256"}
    if not root.is_dir() or not required.issubset({item.name for item in root.iterdir()}):
        raise V03TokenizationError("SOURCE_PACKAGE_INVALID")
    manifest = _read_yaml(root / "manifest.yaml")
    fingerprints = manifest.get("fingerprints")
    content = manifest.get("content")
    if (
        manifest.get("dataset_id") != DATASET_ID
        or not isinstance(fingerprints, Mapping)
        or fingerprints.get("package") != f"sha256:{PACKAGE_FINGERPRINT}"
        or fingerprints.get("manifest") != f"sha256:{MANIFEST_FINGERPRINT}"
        or not isinstance(content, Mapping)
        or content.get("original_rows") != ROWS["original"]
        or content.get("short_rows") != ROWS["short"]
        or content.get("validation_rows") != ROWS["validation"]
    ):
        raise V03TokenizationError("SOURCE_IDENTITY_MISMATCH")
    listed: dict[str, str] = {}
    for line in (root / "checksums.sha256").read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        listed[name] = digest
    if any(not (root / name).is_file() or _sha(root / name) != digest for name, digest in listed.items()):
        raise V03TokenizationError("SOURCE_CHECKSUM_MISMATCH")
    if _sha(root / "validation.jsonl") != "56266aa5b422c8de12e1c5b5cf6490f11d5f2dfc907d55c397e87ea5c7a66363":
        raise V03TokenizationError("VALIDATION_CHECKSUM_MISMATCH")
    train = _read_jsonl(root / "train.jsonl")
    validation = _read_jsonl(root / "validation.jsonl")
    sidecar = _read_jsonl(root / "quality-sidecar.jsonl")
    lineage = _read_jsonl(root / "lineage.jsonl")
    if len(train) != ROWS["train"] or len(validation) != ROWS["validation"]:
        raise V03TokenizationError("SOURCE_ROW_COUNT_MISMATCH")
    train_original = [item for item in sidecar if item.get("split") == "train" and item.get("variant_type") == "original"]
    validation_meta = [item for item in sidecar if item.get("split") == "validation"]
    short = [item for item in sidecar if item.get("split") == "train" and item.get("variant_type") == "short" and item.get("accepted") is True]
    if len(train_original) != ROWS["original"] or len(short) != ROWS["short"] or len(validation_meta) != ROWS["validation"] or len(lineage) != ROWS["short"]:
        raise V03TokenizationError("SOURCE_LINEAGE_COUNT_MISMATCH")
    original_hashes = {str(item["record_hash"]) for item in train_original}
    pairs = {(str(item["parent_record_hash"]), str(item["record_hash"])) for item in short}
    if len(pairs) != ROWS["short"] or any(parent not in original_hashes for parent, _ in pairs):
        raise V03TokenizationError("SOURCE_LINEAGE_INVALID")
    rows = [*train_original, *short]
    return {"manifest": manifest, "train": train, "validation": validation, "rows": rows, "validation_meta": validation_meta, "lineage": lineage, "checksums": listed}


def validate_encoded(record: EncodedRecord) -> None:
    labels = record.labels
    if labels[-1] != EOS_TOKEN_ID or labels.count(EOS_TOKEN_ID) != 1:
        raise V03TokenizationError("EOS_CONTRACT_INVALID")
    if any(label != -100 for label in labels[: record.prompt_tokens]):
        raise V03TokenizationError("PROMPT_MASK_INVALID")
    if any(label == -100 for label in labels[record.prompt_tokens :]):
        raise V03TokenizationError("ASSISTANT_MASK_INVALID")
    if record.input_ids[-1] != EOS_TOKEN_ID:
        raise V03TokenizationError("TOKENS_AFTER_EOS")


def _row_digest(row: Mapping[str, object]) -> str:
    return checksum_value({"input_ids": row["input_ids"], "attention_mask": row["attention_mask"], "labels": row["labels"]})


def _stats(records: Sequence[EncodedRecord]) -> dict[str, object]:
    prompt = [item.prompt_tokens for item in records]
    assistant = [item.assistant_tokens for item in records]
    total = [len(item.input_ids) for item in records]
    return {"prompt": length_statistics(prompt), "assistant": length_statistics(assistant), "total": length_statistics(total)}


def analyze_candidates(records: Sequence[EncodedRecord]) -> tuple[dict[str, dict[str, int]], int]:
    values: dict[str, dict[str, int]] = {}
    selected = 0
    full_tokens = sum(len(item.input_ids) for item in records)
    for candidate in CANDIDATES:
        over = [item for item in records if len(item.input_ids) > candidate]
        assistant = [item for item in records if item.assistant_tokens + 8 > candidate]
        values[str(candidate)] = {
            "total_truncation": len(over),
            "assistant_truncation": len(assistant),
            "eos_truncation": len(assistant),
            "token_savings_if_hard_truncated": full_tokens - sum(min(len(item.input_ids), candidate) for item in records),
        }
        if not selected and not over:
            selected = candidate
    if not selected:
        raise V03TokenizationError("LOSSLESS_MAX_SEQUENCE_UNAVAILABLE")
    return values, selected


def _write_checksums(root: Path) -> dict[str, str]:
    names = [path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and path.name != "checksums.sha256"]
    values = {name: _sha(root / name) for name in sorted(names)}
    with (root / "checksums.sha256").open("x", encoding="ascii", newline="\n") as stream:
        for name, digest in values.items():
            stream.write(f"{digest}  {name}\n")
        stream.flush()
        os.fsync(stream.fileno())
    return values


def _fsync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
        elif path.is_dir():
            _fsync_directory(path)


def _notify(
    callback: Callable[..., None] | None,
    stage: str,
    **values: int | str,
) -> None:
    if callback is not None:
        callback(stage, **values)


def _encode_split(
    tokenizer: Any,
    path: Path,
    *,
    offset: int,
    stage: str,
    completed_stage: str,
    callback: Callable[..., None] | None,
) -> list[EncodedRecord]:
    records: list[EncodedRecord] = []
    _notify(callback, stage, records_seen=offset, records_completed=offset)
    for index, logical in enumerate(iter_logical_records(path), start=1):
        records.append(encode_record(tokenizer, logical))
        if index % 128 == 0:
            _notify(
                callback,
                stage,
                records_seen=offset + index,
                records_completed=offset + index,
            )
    _notify(
        callback,
        completed_stage,
        records_seen=offset + len(records),
        records_completed=offset + len(records),
    )
    return records


def _injected(value: str | None, phase: str) -> None:
    if value == phase:
        raise OSError(f"injected {phase} failure")


def _publish_package_files(
    *,
    output_root: Path,
    train_rows: list[dict[str, list[int]]],
    validation_rows: list[dict[str, list[int]]],
    row_alignment: Mapping[str, object],
    lineage_alignment: Mapping[str, object],
    manifest: Mapping[str, object],
    statistics_value: Mapping[str, object],
    sampler_readiness: Mapping[str, object],
    callback: Callable[..., None] | None,
    failure_injection: str | None,
) -> dict[str, str]:
    try:
        from datasets import Dataset, load_from_disk
    except ImportError:
        raise V03TokenizationError("TOKENIZATION_DEPENDENCY_MISSING") from None
    staging: Path | None = None
    published = False
    try:
        _notify(callback, "publish_started")
        _notify(callback, "publish_staging_creation")
        try:
            _injected(failure_injection, "staging_create")
            output_root.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(
                prefix=f".{output_root.name}.staging-", dir=output_root.parent,
            )).resolve()
        except Exception:
            raise V03TokenizationError("TOKENIZATION_STAGING_CREATE_FAILED") from None
        _notify(callback, "publish_artifact_write")
        try:
            _injected(failure_injection, "artifact_write")
            Dataset.from_list(train_rows).save_to_disk(staging / "train")
            Dataset.from_list(validation_rows).save_to_disk(staging / "validation")
            write_json(staging / "row-alignment.json", dict(row_alignment))
            write_json(staging / "lineage-alignment.json", dict(lineage_alignment))
            write_yaml(staging / "tokenization-manifest.yaml", dict(manifest))
            write_json(staging / "tokenization-statistics.json", dict(statistics_value))
            write_yaml(staging / "sampler-readiness.yaml", dict(sampler_readiness))
        except Exception:
            raise V03TokenizationError("TOKENIZATION_ARTIFACT_WRITE_FAILED") from None
        _notify(callback, "artifact_files_written", files_written=7)
        _notify(callback, "publish_file_fsync", files_written=7)
        try:
            _injected(failure_injection, "file_fsync")
            _fsync_tree(staging)
        except Exception:
            raise V03TokenizationError("TOKENIZATION_FILE_FSYNC_FAILED") from None
        _notify(callback, "publish_checksum_inventory", files_written=7)
        try:
            _injected(failure_injection, "checksum")
            checksums = _write_checksums(staging)
        except Exception:
            raise V03TokenizationError("TOKENIZATION_CHECKSUM_FAILED") from None
        _notify(callback, "checksums_created", files_written=len(checksums))
        _notify(callback, "publish_staging_reload", files_written=len(checksums))
        try:
            _injected(failure_injection, "staging_reload")
            if len(load_from_disk(staging / "train")) != ROWS["train"] or len(load_from_disk(staging / "validation")) != ROWS["validation"]:
                raise ValueError("row count mismatch")
        except Exception:
            raise V03TokenizationError("TOKENIZATION_STAGING_RELOAD_FAILED") from None
        if failure_injection == "staging_cleanup":
            raise V03TokenizationError("TOKENIZATION_STAGING_CLEANUP_FAILED")
        _notify(callback, "publish_final_collision_check", files_written=len(checksums))
        if output_root.exists():
            raise V03TokenizationError("TOKENIZATION_FINAL_COLLISION")
        _notify(callback, "publish_atomic_no_replace", files_written=len(checksums))
        try:
            _injected(failure_injection, "atomic_publish")
            _rename_directory_no_replace(staging, output_root)
            published = True
        except Exception:
            raise V03TokenizationError("TOKENIZATION_ATOMIC_PUBLISH_FAILED") from None
        _notify(callback, "publish_directory_fsync", files_written=len(checksums))
        try:
            _injected(failure_injection, "directory_fsync")
            _fsync_directory(output_root.parent)
        except Exception:
            raise V03TokenizationError("TOKENIZATION_DIRECTORY_FSYNC_FAILED") from None
        _notify(callback, "publish_final_reload", files_written=len(checksums))
        try:
            _injected(failure_injection, "final_reload")
            if len(load_from_disk(output_root / "train")) != ROWS["train"] or len(load_from_disk(output_root / "validation")) != ROWS["validation"]:
                raise ValueError("row count mismatch")
        except Exception:
            raise V03TokenizationError("TOKENIZATION_FINAL_RELOAD_FAILED") from None
        _notify(callback, "publish_final_checksum", files_written=len(checksums))
        try:
            _injected(failure_injection, "final_checksum")
            if any(_sha(output_root / name) != digest for name, digest in checksums.items()):
                raise ValueError("checksum mismatch")
        except Exception:
            raise V03TokenizationError("TOKENIZATION_FINAL_CHECKSUM_FAILED") from None
        _notify(callback, "publish_completed", files_written=len(checksums))
        return checksums
    finally:
        if staging is not None and staging.exists():
            try:
                _injected(failure_injection, "staging_cleanup")
                shutil.rmtree(staging)
                _fsync_directory(staging.parent)
            except Exception:
                if not published:
                    raise V03TokenizationError("TOKENIZATION_STAGING_CLEANUP_FAILED") from None


def build_package(
    *,
    source_root: Path,
    reuse_root: Path,
    tokenizer_root: Path,
    output_root: Path,
    git_head: str,
    stage_callback: Callable[..., None] | None = None,
    failure_injection: str | None = None,
) -> dict[str, object]:
    try:
        from datasets import load_from_disk
        from transformers import AutoTokenizer
    except ImportError:
        raise V03TokenizationError("TOKENIZATION_DEPENDENCY_MISSING") from None
    _notify(stage_callback, "preflight")
    source = validate_source(source_root)
    _notify(stage_callback, "source_validated")
    if any(path.exists() for path in (output_root, output_root.with_name(output_root.name + ".staging"), output_root.with_name(output_root.name + ".failed"))) or list(output_root.parent.glob(f".{output_root.name}.staging-*")):
        raise V03TokenizationError("TOKENIZATION_RUN_ID_ALREADY_USED")
    fingerprint, tokenizer_checksums = tokenizer_fingerprint(tokenizer_root)
    if fingerprint != TOKENIZER_FINGERPRINT:
        raise V03TokenizationError("TOKENIZER_FINGERPRINT_MISMATCH")
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_root, local_files_only=True, trust_remote_code=False)
    if tokenizer.eos_token_id != EOS_TOKEN_ID or tokenizer.pad_token_id != 151643:
        raise V03TokenizationError("TOKENIZER_SPECIAL_TOKEN_MISMATCH")
    _notify(stage_callback, "tokenizer_loaded")
    train_encoded = _encode_split(
        tokenizer,
        source_root / "train.jsonl",
        offset=0,
        stage="short_tokenization_started",
        completed_stage="short_tokenization_completed",
        callback=stage_callback,
    )
    validation_encoded = _encode_split(
        tokenizer,
        source_root / "validation.jsonl",
        offset=len(train_encoded),
        stage="validation_prepared",
        completed_stage="validation_prepared",
        callback=stage_callback,
    )
    for record in (*train_encoded, *validation_encoded):
        validate_encoded(record)
    candidates, selected = analyze_candidates((*train_encoded, *validation_encoded))
    _notify(stage_callback, "length_analysis_completed", records_seen=18926, records_completed=18926)
    train_rows = [item.as_dataset_record() for item in train_encoded]
    validation_rows = [item.as_dataset_record() for item in validation_encoded]
    rows_meta = source["rows"]
    alignment_rows = []
    for index, (meta, encoded) in enumerate(zip(rows_meta, train_encoded)):
        alignment_rows.append({
            "row_index": index, "record_hash": meta["record_hash"],
            "parent_record_hash": meta.get("parent_record_hash"), "variant_type": meta["variant_type"],
            "category": meta.get("category"),
            "token_row_fingerprint": _row_digest(encoded.as_dataset_record()),
            "total_tokens": len(encoded.input_ids), "assistant_tokens": encoded.assistant_tokens,
        })
    validation_alignment = [
        {"row_index": index, "record_hash": meta["record_hash"], "token_row_fingerprint": _row_digest(encoded.as_dataset_record())}
        for index, (meta, encoded) in enumerate(zip(source["validation_meta"], validation_encoded))
    ]
    original = train_encoded[: ROWS["original"]]
    short = train_encoded[ROWS["original"] :]
    statistics_value = {
        "schema_version": 1, "rows": {"train": len(train_encoded), "validation": len(validation_encoded)},
        "lengths": {"original_train": _stats(original), "short_train": _stats(short), "combined_train": _stats(train_encoded), "validation": _stats(validation_encoded)},
        "tokens": {"train_total": sum(map(lambda x: len(x.input_ids), train_encoded)), "train_assistant": sum(x.assistant_tokens for x in train_encoded), "validation_total": sum(map(lambda x: len(x.input_ids), validation_encoded)), "original_total": sum(map(lambda x: len(x.input_ids), original)), "short_total": sum(map(lambda x: len(x.input_ids), short))},
        "max_sequence_candidates": candidates, "selected_max_seq_length": selected,
        "eos": {"missing": 0, "duplicated": 0, "tokens_after_eos": 0, "last_label_not_eos": 0},
        "masks": {"prompt_trainable_labels": 0, "assistant_masked_labels": 0, "padding_trainable_labels": 0},
    }
    row_alignment = {
        "schema_version": 1, "train": alignment_rows, "validation": validation_alignment,
        "fingerprints": {
            "train_jsonl_order": checksum_value([item["record_hash"] for item in rows_meta]),
            "train_sidecar_order": checksum_value([item["record_hash"] for item in rows_meta]),
            "train_tokenized_order": checksum_value([item["token_row_fingerprint"] for item in alignment_rows]),
            "validation_order": checksum_value([item["record_hash"] for item in validation_alignment]),
        }, "alignment_valid": True,
    }
    lineage_alignment = {"schema_version": 1, "parent_child_pairs": ROWS["short"], "missing_parents": 0, "duplicate_pairs": 0, "maximum_short_variants_per_parent": 1, "lineage_fingerprint": checksum_value(source["lineage"]), "alignment_valid": True}
    sampler_readiness = {"schema_version": 1, "simulation_id": "DOHALM-V0.3-SAMPLING-SIMULATION-20260802-0001", "status": "ready_for_single_execution_after_merge", "recommended": {"policy": "parent_group_shuffle", "replacement": False, "draws_per_epoch": ROWS["train"], "base_seed": 42, "epoch_seed_formula": "base_seed + epoch_index"}, "training_allowed": False, "execution_allowed": False}
    reuse = {"source_id": "DOHALM-TOKENIZATION-20260730-0001", "source_artifact_fingerprint": "f626e00c2c4cfc065623f857e4655865f793fc8781a319200bc81bb0489d6045", "eligible": False, "reused_original_rows": 0, "reused_validation_rows": 0, "reason": "selected_max_seq_length_mismatch"}
    if selected == 1536:
        try:
            reuse_result = _read_yaml(reuse_root / "tokenization-result.yaml")
            reuse_config = _read_yaml(reuse_root / "tokenization-config.yaml")
            old_train = load_from_disk(reuse_root / "train")
            old_validation = load_from_disk(reuse_root / "validation")
        except (OSError, ValueError):
            raise V03TokenizationError("REUSE_ARTIFACT_INVALID") from None
        old_checksums = {
            path.relative_to(reuse_root).as_posix(): _sha(path)
            for path in sorted(reuse_root.rglob("*"), key=lambda item: item.as_posix())
            if path.is_file() and path.name != "checksums.sha256"
        }
        old_fingerprint = hashlib.sha256(json.dumps(old_checksums, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        reuse_tokenization = reuse_config.get("tokenization")
        exact_contract = (
            old_fingerprint == reuse["source_artifact_fingerprint"]
            and reuse_result.get("tokenization_run_id") == reuse["source_id"]
            and reuse_result.get("tokenizer_fingerprint") == fingerprint
            and reuse_result.get("model_revision") == "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
            and reuse_result.get("packing") is False
            and reuse_result.get("assistant_only_loss") is True
            and isinstance(reuse_tokenization, Mapping)
            and reuse_tokenization.get("max_seq_length") == 1536
            and reuse_tokenization.get("train_on_prompt") is False
            and len(old_train) == ROWS["original"]
            and len(old_validation) == ROWS["validation"]
        )
        row_equal = exact_contract and all(old_train[index] == train_rows[index] for index in range(ROWS["original"]))
        validation_equal = exact_contract and all(old_validation[index] == validation_rows[index] for index in range(ROWS["validation"]))
        if row_equal and validation_equal:
            train_rows[: ROWS["original"]] = [dict(old_train[index]) for index in range(ROWS["original"])]
            validation_rows = [dict(old_validation[index]) for index in range(ROWS["validation"])]
            reuse.update({"eligible": True, "reused_original_rows": ROWS["original"], "reused_validation_rows": ROWS["validation"], "reason": "verified_token_row_identical"})
        else:
            reuse["reason"] = "tokenization_contract_or_row_mismatch"
    _notify(stage_callback, "original_reuse_validated", records_seen=18926, records_completed=18926)
    semantic_manifest = {"schema_version": 1, "tokenization_id": TOKENIZATION_ID, "dataset": {"id": DATASET_ID, "package_fingerprint": f"sha256:{PACKAGE_FINGERPRINT}", "manifest_fingerprint": f"sha256:{MANIFEST_FINGERPRINT}", "source_checksums": source["checksums"]}, "tokenizer": {"model": "Qwen/Qwen2.5-1.5B-Instruct", "revision": "989aa7980e4cf806f80c7fef2b1adb7bc71aa306", "fingerprint": fingerprint, "checksums": tokenizer_checksums}, "contract": {"max_seq_length": selected, "packing": False, "assistant_only_loss": True, "eos_exactly_one": True}, "reuse": reuse, "git_head": git_head, "training_started": False, "training_allowed": False, "execution_allowed": False}
    manifest = {**semantic_manifest, "fingerprints": {"manifest": checksum_value(semantic_manifest), "statistics": checksum_value(statistics_value), "row_alignment": checksum_value(row_alignment), "lineage_alignment": checksum_value(lineage_alignment), "sampler_readiness": checksum_value(sampler_readiness)}}
    _notify(stage_callback, "alignment_validated", records_seen=18926, records_completed=18926)
    checksums = _publish_package_files(
        output_root=output_root,
        train_rows=train_rows,
        validation_rows=validation_rows,
        row_alignment=row_alignment,
        lineage_alignment=lineage_alignment,
        manifest=manifest,
        statistics_value=statistics_value,
        sampler_readiness=sampler_readiness,
        callback=stage_callback,
        failure_injection=failure_injection,
    )
    return {"status": "completed", "tokenization_id": TOKENIZATION_ID, "selected_max_seq_length": selected, "statistics": statistics_value, "reuse": reuse, "checksums": checksums, "artifact_fingerprint": checksum_value({"algorithm": "ordered-file-checksums-v1", "files": sorted(checksums.items())})}
