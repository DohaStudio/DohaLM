"""Fail-closed QLoRA smoke and training helpers for DohaLM v0.1."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import math
import os
import platform
import random
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from transformers import TrainerCallback

from src.training.sft_tokenization import (
    IGNORE_INDEX,
    load_config,
    validate_qlora_config,
)

RUN_ID = "DOHALM-V0.1-QLORA-20260730-0001"
ALLOCATION_SMOKE_RUN_ID = "DOHALM-V0.1-QLORA-ALLOCATION-SMOKE-20260731-0002"
BACKWARD_DIAGNOSTIC_RUN_ID = "DOHALM-V0.1-QLORA-BACKWARD-DIAG-20260731-0001"
TRAINING_SMOKE_RUN_ID = "DOHALM-V0.1-QLORA-TRAINING-SMOKE-20260731-0001"
RETIRED_WSL_RUN_ID = "DOHALM-V0.1-QLORA-20260731-0002"
RETIRED_WSL_ALLOCATION_SMOKE_RUN_IDS = (
    "DOHALM-V0.1-QLORA-ALLOCATION-SMOKE-WSL-20260731-0001",
    "DOHALM-V0.1-QLORA-ALLOCATION-SMOKE-WSL-20260731-0002",
    "DOHALM-V0.1-QLORA-ALLOCATION-SMOKE-WSL-20260731-0003",
)
RETIRED_WSL_BACKWARD_DIAGNOSTIC_RUN_IDS = (
    "DOHALM-V0.1-QLORA-BACKWARD-DIAG-WSL-20260731-0001",
    "DOHALM-V0.1-QLORA-BACKWARD-DIAG-WSL-20260731-0002",
    "DOHALM-V0.1-QLORA-BACKWARD-DIAG-WSL-20260731-0003",
)
RETIRED_WSL_TRAINING_SMOKE_RUN_IDS = (
    "DOHALM-V0.1-QLORA-TRAINING-SMOKE-WSL-20260731-0001",
    "DOHALM-V0.1-QLORA-TRAINING-SMOKE-STAGE1-WSL-20260731-0002",
    "DOHALM-V0.1-QLORA-TRAINING-SMOKE-STAGE2-WSL-20260731-0002",
    "DOHALM-V0.1-QLORA-TRAINING-SMOKE-STAGE1-WSL-20260731-0003",
    "DOHALM-V0.1-QLORA-TRAINING-SMOKE-STAGE2-WSL-20260731-0003",
)
RETIRED_WSL_ALLOCATION_SMOKE_RUN_ID = RETIRED_WSL_ALLOCATION_SMOKE_RUN_IDS[0]
RETIRED_WSL_BACKWARD_DIAGNOSTIC_RUN_ID = RETIRED_WSL_BACKWARD_DIAGNOSTIC_RUN_IDS[0]
RETIRED_WSL_TRAINING_SMOKE_RUN_ID = RETIRED_WSL_TRAINING_SMOKE_RUN_IDS[0]
WSL_ALLOCATION_SMOKE_RUN_ID = "DOHALM-V0.1-QLORA-ALLOCATION-SMOKE-WSL-20260731-0004"
WSL_BACKWARD_DIAGNOSTIC_RUN_ID = "DOHALM-V0.1-QLORA-BACKWARD-DIAG-WSL-20260731-0004"
WSL_TRAINING_SMOKE_STAGE1_RUN_ID = (
    "DOHALM-V0.1-QLORA-TRAINING-SMOKE-STAGE1-WSL-20260731-0004"
)
WSL_TRAINING_SMOKE_STAGE2_RUN_ID = (
    "DOHALM-V0.1-QLORA-TRAINING-SMOKE-STAGE2-WSL-20260731-0004"
)
RETIRED_WSL_STABILITY_RUN_ID = "DOHALM-V0.1-QLORA-STABILITY-WSL-20260731-0001"
RETIRED_WSL_STABILITY_RUN_ID_2 = "DOHALM-V0.1-QLORA-STABILITY-WSL-20260731-0002"
WSL_STABILITY_RUN_ID = "DOHALM-V0.1-QLORA-STABILITY-WSL-20260731-0003"
WSL_RUN_ID = "DOHALM-V0.1-QLORA-20260731-0003"
SOURCE_PROCESSING_RUN = "AIHUB-71748-SFT-PROCESSING-20260730-0015"
TOKENIZATION_RUN = "DOHALM-TOKENIZATION-20260730-0001"
MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"
MODEL_REVISION = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
DATASET_FINGERPRINT = "b6848e9413ecd0f63008cf18f505dda0b3197e562b5c6a9f955c1a7d41bc98a0"
TOKENIZER_FINGERPRINT = "ad0a85da869c2e4577b9409df0c91e35be70f0395a20c94765c6f4fa02ea6a55"
ARTIFACT_FINGERPRINT = "f626e00c2c4cfc065623f857e4655865f793fc8781a319200bc81bb0489d6045"
BASELINE_HEAD = "b9ad41bda5871075c18ee230724d736a6ff9f5fe"
EXPECTED_ROWS = {"train": 10_374, "validation": 1_287}
EXPECTED_TOKENS = {"train": 4_481_321, "validation": 568_893}
EXPECTED_EOS_ID = 151_645
EXPECTED_TOKENIZER_LENGTH = 151_665
TARGET_MODULES = (
    "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
)
BACKWARD_DIAGNOSTIC_LENGTHS = (128, 256, 512, 768, 1015)
STAGE_TIMEOUTS = {
    "model_loading": 900.0,
    "allocation_forward_median": 120.0,
    "allocation_forward_longest": 120.0,
    "backward_diagnostic": 600.0,
    "training_smoke": 1800.0,
    "training_smoke_reload": 600.0,
    "stability_micro_batch": 300.0,
    "stability_result_publish": 300.0,
    "full_training_micro_batch": 300.0,
}

STABILITY_REQUIRED_FILES = frozenset({
    "stability-result.yaml",
    "batch-metrics.jsonl",
    "environment.json",
    "stage-state.json",
    "checksums.sha256",
})
STABILITY_PAYLOAD_FILES = (
    "batch-metrics.jsonl",
    "environment.json",
    "stability-result.yaml",
    "stage-state.json",
)
STABILITY_METRIC_FIELDS = (
    "run_id", "runtime_head", "microbatch_index", "optimizer_step",
    "sequence_length", "padded_length", "valid_label_tokens",
    "forward_seconds", "backward_seconds", "total_seconds", "loss",
    "gradient_norm", "allocated_vram_bytes", "reserved_vram_bytes",
    "peak_vram_bytes", "gpu_utilization_percent", "gpu_temperature_c",
    "stage", "timestamp",
)
STABILITY_STATE_FIELDS = (
    "schema_version", "run_id", "runtime_head", "status", "current_stage",
    "microbatch_index", "optimizer_step", "last_progress_at", "worker_pid",
    "sequence_length", "allocated_vram_bytes", "reserved_vram_bytes",
    "elapsed_seconds", "failure_code",
    "dataset_index", "stable_record_hash", "padded_length",
    "valid_label_tokens", "input_ids_checksum", "labels_checksum",
    "attention_mask_checksum", "category_hash", "shuffle_seed",
    "sampler_order_fingerprint", "first_64_indices_hash",
)
STABILITY_FAILURE_REQUIRED_FILES = frozenset({
    "batch-metrics.jsonl",
    "stage-state.json",
    "environment.json",
    "failure-result.yaml",
    "checksums.sha256",
})
STABILITY_FAILURE_PAYLOAD_FILES = (
    "batch-metrics.jsonl",
    "environment.json",
    "failure-result.yaml",
    "stage-state.json",
)
STABILITY_FAILURE_STATE_FIELDS = (
    "schema_version", "run_id", "runtime_head", "status", "failure_code",
    "failed_stage", "failed_microbatch_index", "optimizer_step",
    "sequence_length", "last_progress_at", "failed_at", "worker_pid",
    "worker_exit_code", "watchdog_seconds", "allocated_vram_bytes",
    "reserved_vram_bytes", "elapsed_seconds",
    "dataset_index", "stable_record_hash", "padded_length",
    "valid_label_tokens", "input_ids_checksum", "labels_checksum",
    "attention_mask_checksum", "category_hash", "shuffle_seed",
    "sampler_order_fingerprint", "first_64_indices_hash",
)


class QLoRATrainingError(RuntimeError):
    """Stable fail-closed error raised before unsafe continuation."""


@dataclass(frozen=True)
class ArtifactPaths:
    final: Path
    staging: Path
    failed: Path


@dataclass(frozen=True)
class ModelStatistics:
    model_class: str
    total_parameters: int
    trainable_parameters: int
    trainable_ratio: float
    four_bit_modules: int
    lora_modules: int
    target_counts: dict[str, int]
    device_map: dict[str, str]
    unexpected_cpu_parameters: int
    input_embedding_size: int
    lm_head_size: int
    tokenizer_length: int
    model_dtype: str


class StageReporter:
    """Emit non-sensitive stage transitions and enforce post-stage deadlines."""

    def __init__(self, *, clock: Any = time.perf_counter, stream: Any = None) -> None:
        self.clock = clock
        self.stream = stream if stream is not None else sys.stderr
        self.events: list[dict[str, object]] = []

    def emit(self, stage: str, status: str, **metadata: object) -> None:
        cuda_memory: dict[str, object] = {}
        torch_module = sys.modules.get("torch")
        if torch_module is not None and torch_module.cuda.is_available():
            cuda_memory = {
                "allocated_bytes": torch_module.cuda.memory_allocated(),
                "reserved_bytes": torch_module.cuda.memory_reserved(),
                "peak_allocated_bytes": torch_module.cuda.max_memory_allocated(),
                "peak_reserved_bytes": torch_module.cuda.max_memory_reserved(),
            }
        event = {
            "stage": stage,
            "status": status,
            "captured_at": utc_now(),
            "pid": os.getpid(),
            **cuda_memory,
            **metadata,
        }
        self.events.append(event)
        print(json.dumps(event, sort_keys=True), file=self.stream, flush=True)

    @contextmanager
    def stage(
        self,
        name: str,
        *,
        timeout_seconds: float,
        **metadata: object,
    ) -> Any:
        started = self.clock()
        self.emit(name, "started", timeout_seconds=timeout_seconds, **metadata)
        try:
            yield
        except Exception:
            self.emit(name, "failed", elapsed_seconds=self.clock() - started, **metadata)
            raise
        elapsed = self.clock() - started
        if elapsed > timeout_seconds:
            self.emit(name, "timeout", elapsed_seconds=elapsed, **metadata)
            error_code = (
                "STABILITY_RESULT_PUBLISH_TIMEOUT"
                if name == "stability_result_publish"
                else f"STAGE_TIMEOUT_{name.upper()}"
            )
            raise QLoRATrainingError(error_code)
        self.emit(name, "passed", elapsed_seconds=elapsed, **metadata)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_fingerprint(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def artifact_paths(final: str | Path) -> ArtifactPaths:
    destination = Path(final)
    return ArtifactPaths(
        final=destination,
        staging=destination.with_name(destination.name + ".staging"),
        failed=destination.with_name(destination.name + ".failed"),
    )


def ensure_unused_output(final: str | Path) -> ArtifactPaths:
    paths = artifact_paths(final)
    if any(path.exists() for path in (paths.final, paths.staging, paths.failed)):
        raise QLoRATrainingError("OUTPUT_RUN_ID_ALREADY_USED")
    paths.staging.parent.mkdir(parents=True, exist_ok=True)
    return paths


def quarantine_staging(paths: ArtifactPaths) -> None:
    if paths.staging.exists() and not paths.failed.exists():
        os.replace(paths.staging, paths.failed)


def quarantine_stability_publication(paths: ArtifactPaths) -> None:
    """Ensure a failed or timed-out publish never remains canonical."""
    if paths.failed.exists():
        return
    if paths.staging.exists():
        os.replace(paths.staging, paths.failed)
    elif paths.final.exists():
        os.replace(paths.final, paths.failed)
    _fsync_directory(paths.failed.parent)


def _fsync_directory(path: Path) -> None:
    """Persist directory entries where the host exposes directory fsync."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_staging(
    paths: ArtifactPaths,
    *,
    before_directory_sync: Callable[[], None] | None = None,
) -> None:
    if not paths.staging.is_dir() or paths.final.exists():
        raise QLoRATrainingError("OUTPUT_ATOMIC_PUBLISH_INVALID")
    _rename_directory_no_replace(paths.staging, paths.final)
    if before_directory_sync is not None:
        before_directory_sync()
    _fsync_directory(paths.final.parent)


def _rename_directory_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish one directory without replacing an existing entry."""
    if not source.is_dir() or destination.exists():
        raise QLoRATrainingError("OUTPUT_ATOMIC_PUBLISH_INVALID")
    if os.name == "nt":
        try:
            os.rename(source, destination)
        except FileExistsError:
            raise QLoRATrainingError("OUTPUT_ATOMIC_PUBLISH_COLLISION") from None
    elif sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise QLoRATrainingError("OUTPUT_ATOMIC_NOREPLACE_UNSUPPORTED")
        renameat2.argtypes = (
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,
            os.fsencode(source),
            -100,
            os.fsencode(destination),
            1,
        )
        if result != 0:
            error = ctypes.get_errno()
            if error in {errno.EEXIST, errno.ENOTEMPTY}:
                raise QLoRATrainingError("OUTPUT_ATOMIC_PUBLISH_COLLISION")
            if error in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP}:
                raise QLoRATrainingError("OUTPUT_ATOMIC_NOREPLACE_UNSUPPORTED")
            raise OSError(error, os.strerror(error), str(destination))
    else:
        raise QLoRATrainingError("OUTPUT_ATOMIC_NOREPLACE_UNSUPPORTED")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _exclusive_write(path: Path, payload: str, *, encoding: str = "utf-8") -> None:
    with path.open("x", encoding=encoding, newline="") as stream:
        written = stream.write(payload)
        if written != len(payload):
            raise QLoRATrainingError("STABILITY_ARTIFACT_SHORT_WRITE")
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_json_replace(
    path: Path,
    value: Mapping[str, object],
    *,
    expected_fields: Sequence[str] = STABILITY_STATE_FIELDS,
) -> None:
    if set(value) != set(expected_fields):
        raise QLoRATrainingError("STABILITY_STAGE_STATE_INVALID")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise QLoRATrainingError("STABILITY_TEMP_RESIDUE")
    try:
        _exclusive_write(temporary, _canonical_json(dict(value)) + "\n")
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


class StabilityMetricsWriter:
    """Append canonical, non-sensitive microbatch metrics durably."""

    def __init__(self, path: Path, *, fsync_every_records: int = 8) -> None:
        self.path = path
        self.fsync_every_records = fsync_every_records
        self.count = 0
        self._stream = path.open("x", encoding="utf-8", newline="")

    def append(self, record: Mapping[str, object]) -> None:
        if tuple(record) != STABILITY_METRIC_FIELDS:
            raise QLoRATrainingError("STABILITY_METRIC_FIELDS_INVALID")
        payload = _canonical_json(dict(record)) + "\n"
        written = self._stream.write(payload)
        if written != len(payload):
            raise QLoRATrainingError("STABILITY_METRIC_SHORT_WRITE")
        self.count += 1
        self._stream.flush()
        if self.count % self.fsync_every_records == 0:
            os.fsync(self._stream.fileno())

    def finalize(self) -> None:
        if self._stream.closed:
            return
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()

    def close(self) -> None:
        if not self._stream.closed:
            self._stream.close()


class StabilityStateWriter:
    """Atomically replace the current Stability lifecycle state."""

    def __init__(self, path: Path, *, run_id: str, runtime_head: str) -> None:
        self.path = path
        self.run_id = run_id
        self.runtime_head = runtime_head
        self.started = time.perf_counter()
        self.problem_batch: dict[str, object] = {
            "dataset_index": 0,
            "stable_record_hash": "",
            "padded_length": 0,
            "valid_label_tokens": 0,
            "input_ids_checksum": "",
            "labels_checksum": "",
            "attention_mask_checksum": "",
            "category_hash": "",
            "shuffle_seed": 0,
            "sampler_order_fingerprint": "",
            "first_64_indices_hash": "",
        }
        self.update(status="starting", current_stage="stability_started")

    def update(
        self,
        *,
        status: str,
        current_stage: str,
        microbatch_index: int = 0,
        optimizer_step: int = 0,
        sequence_length: int = 0,
        failure_code: str | None = None,
        problem_batch: Mapping[str, object] | None = None,
    ) -> None:
        if status not in {"starting", "running", "publishing", "completed", "failed"}:
            raise QLoRATrainingError("STABILITY_STAGE_STATUS_INVALID")
        allocated, reserved, _ = _cuda_memory()
        if problem_batch is not None:
            if set(problem_batch) != set(self.problem_batch):
                raise QLoRATrainingError("STABILITY_BATCH_IDENTITY_INVALID")
            self.problem_batch = dict(problem_batch)
        state = {
            "schema_version": 1,
            "run_id": self.run_id,
            "runtime_head": self.runtime_head,
            "status": status,
            "current_stage": current_stage,
            "microbatch_index": microbatch_index,
            "optimizer_step": optimizer_step,
            "last_progress_at": utc_now(),
            "worker_pid": os.getpid(),
            "sequence_length": sequence_length,
            "allocated_vram_bytes": allocated,
            "reserved_vram_bytes": reserved,
            "elapsed_seconds": time.perf_counter() - self.started,
            "failure_code": failure_code,
            **self.problem_batch,
        }
        _atomic_json_replace(self.path, state)


def _cuda_memory() -> tuple[int, int, int]:
    torch_module = sys.modules.get("torch")
    if torch_module is None or not torch_module.cuda.is_available():
        return 0, 0, 0
    return (
        int(torch_module.cuda.memory_allocated()),
        int(torch_module.cuda.memory_reserved()),
        int(torch_module.cuda.max_memory_allocated()),
    )


def _integer_sequence_checksum(values: Sequence[int]) -> str:
    return canonical_fingerprint([int(value) for value in values])


def stability_batch_identity(
    record: Mapping[str, object],
    *,
    dataset_index: int,
    padded_length: int,
    valid_label_tokens: int,
    shuffle_seed: int,
    sampler_order_fingerprint: str,
    first_64_indices_hash: str,
) -> dict[str, object]:
    """Build reproducibility metadata without exposing text or token sequences."""
    sequences: dict[str, Sequence[int]] = {}
    for name in ("input_ids", "labels", "attention_mask"):
        value = record.get(name)
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise QLoRATrainingError("STABILITY_BATCH_IDENTITY_INVALID")
        sequences[name] = value  # type: ignore[assignment]
    checksums = {
        f"{name}_checksum": _integer_sequence_checksum(values)
        for name, values in sequences.items()
    }
    category = record.get("category")
    category_hash = canonical_fingerprint(category) if category is not None else ""
    stable_record_hash = canonical_fingerprint({
        "dataset_index": dataset_index,
        "lengths": {name: len(values) for name, values in sequences.items()},
        **checksums,
        "category_hash": category_hash,
    })
    return {
        "dataset_index": dataset_index,
        "stable_record_hash": stable_record_hash,
        "padded_length": padded_length,
        "valid_label_tokens": valid_label_tokens,
        **checksums,
        "category_hash": category_hash,
        "shuffle_seed": shuffle_seed,
        "sampler_order_fingerprint": sampler_order_fingerprint,
        "first_64_indices_hash": first_64_indices_hash,
    }


def _gpu_health() -> tuple[float | None, float | None]:
    torch_module = sys.modules.get("torch")
    if torch_module is None or not torch_module.cuda.is_available():
        return None, None
    try:
        completed = subprocess.run(
            [
                "nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits", "--id=0",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
        utilization, temperature = completed.stdout.strip().split(",", maxsplit=1)
        return float(utilization.strip()), float(temperature.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, None


def _write_stability_checksums(root: Path) -> dict[str, str]:
    checksums = {name: sha256_file(root / name) for name in STABILITY_PAYLOAD_FILES}
    payload = "".join(f"{checksums[name]}  {name}\n" for name in STABILITY_PAYLOAD_FILES)
    _exclusive_write(root / "checksums.sha256", payload, encoding="ascii")
    return checksums


def _write_stability_failure_checksums(root: Path) -> dict[str, str]:
    checksums = {
        name: sha256_file(root / name) for name in STABILITY_FAILURE_PAYLOAD_FILES
    }
    payload = "".join(
        f"{checksums[name]}  {name}\n" for name in STABILITY_FAILURE_PAYLOAD_FILES
    )
    _exclusive_write(root / "checksums.sha256", payload, encoding="ascii")
    return checksums


def validate_stability_failure(
    root: str | Path,
    *,
    expected_head: str,
    expected_run_id: str,
) -> dict[str, object]:
    """Reload and verify a terminal Stability failure without reading payload text."""
    base = Path(root)
    if not base.is_dir() or {path.name for path in base.iterdir()} != (
        STABILITY_FAILURE_REQUIRED_FILES
    ):
        raise QLoRATrainingError("STABILITY_FAILURE_FILE_SET_INVALID")
    try:
        state = json.loads((base / "stage-state.json").read_text(encoding="utf-8"))
        environment = json.loads((base / "environment.json").read_text(encoding="utf-8"))
        failure = yaml.safe_load((base / "failure-result.yaml").read_text(encoding="utf-8"))
        metric_lines = (base / "batch-metrics.jsonl").read_text(
            encoding="utf-8",
        ).splitlines()
        metrics = [json.loads(line) for line in metric_lines]
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        raise QLoRATrainingError("STABILITY_FAILURE_INVALID") from None
    if (
        not isinstance(state, Mapping)
        or set(state) != set(STABILITY_FAILURE_STATE_FIELDS)
        or not isinstance(environment, Mapping)
        or not isinstance(failure, Mapping)
        or state.get("status") != "failed"
        or state.get("run_id") != expected_run_id
        or state.get("runtime_head") != expected_head
        or failure.get("status") != "failed"
        or failure.get("run_id") != expected_run_id
        or failure.get("runtime_head") != expected_head
        or failure.get("completed_micro_batches") != len(metrics)
        or any(set(metric) != set(STABILITY_METRIC_FIELDS) for metric in metrics)
        or any(metric.get("run_id") != expected_run_id for metric in metrics)
        or any(metric.get("runtime_head") != expected_head for metric in metrics)
    ):
        raise QLoRATrainingError("STABILITY_FAILURE_INVALID")
    expected_checksums = _parse_checksum_file(base)
    actual_checksums = {
        name: sha256_file(base / name) for name in STABILITY_FAILURE_PAYLOAD_FILES
    }
    if expected_checksums != actual_checksums:
        raise QLoRATrainingError("STABILITY_FAILURE_CHECKSUM_MISMATCH")
    return dict(failure)


def finalize_stability_failure(
    paths: ArtifactPaths,
    *,
    failure_code: str,
    failed_stage: str,
    worker_exit_code: int,
    watchdog_seconds: float,
    failed_microbatch_index: int | None = None,
    sequence_length: int | None = None,
    allocated_vram_bytes: int | None = None,
    reserved_vram_bytes: int | None = None,
    failed_at: str | None = None,
    before_directory_sync: Callable[[], None] | None = None,
    reload_validator: Callable[..., dict[str, object]] | None = None,
) -> dict[str, object]:
    """Convert interrupted Stability staging into a durable terminal failure."""
    if paths.final.exists() or paths.failed.exists() or not paths.staging.is_dir():
        raise QLoRATrainingError("STABILITY_FAILURE_PUBLISH_COLLISION")
    state_path = paths.staging / "stage-state.json"
    metrics_path = paths.staging / "batch-metrics.jsonl"
    environment_path = paths.staging / "environment.json"
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
        environment = json.loads(environment_path.read_text(encoding="utf-8"))
        metric_lines = metrics_path.read_text(encoding="utf-8").splitlines()
        metrics = [json.loads(line) for line in metric_lines]
    except (OSError, UnicodeError, ValueError):
        raise QLoRATrainingError("STABILITY_FAILURE_SOURCE_INVALID") from None
    if (
        not isinstance(previous, Mapping)
        or not isinstance(environment, Mapping)
        or set(previous) != set(STABILITY_STATE_FIELDS)
        or any(set(metric) != set(STABILITY_METRIC_FIELDS) for metric in metrics)
    ):
        raise QLoRATrainingError("STABILITY_FAILURE_SOURCE_INVALID")
    run_id = str(previous.get("run_id", ""))
    runtime_head = str(previous.get("runtime_head", ""))
    if not run_id or not runtime_head:
        raise QLoRATrainingError("STABILITY_FAILURE_SOURCE_INVALID")
    terminal_time = failed_at or utc_now()
    state = {
        "schema_version": 1,
        "run_id": run_id,
        "runtime_head": runtime_head,
        "status": "failed",
        "failure_code": failure_code,
        "failed_stage": failed_stage,
        "failed_microbatch_index": int(
            previous.get("microbatch_index", 0)
            if failed_microbatch_index is None else failed_microbatch_index
        ),
        "optimizer_step": int(previous.get("optimizer_step", 0)),
        "sequence_length": int(
            previous.get("sequence_length", 0)
            if sequence_length is None else sequence_length
        ),
        "last_progress_at": str(previous.get("last_progress_at", "")),
        "failed_at": terminal_time,
        "worker_pid": int(previous.get("worker_pid", 0)),
        "worker_exit_code": int(worker_exit_code),
        "watchdog_seconds": float(watchdog_seconds),
        "allocated_vram_bytes": int(
            previous.get("allocated_vram_bytes", 0)
            if allocated_vram_bytes is None else allocated_vram_bytes
        ),
        "reserved_vram_bytes": int(
            previous.get("reserved_vram_bytes", 0)
            if reserved_vram_bytes is None else reserved_vram_bytes
        ),
        "elapsed_seconds": float(previous.get("elapsed_seconds", 0.0)),
        "dataset_index": int(previous.get("dataset_index", 0)),
        "stable_record_hash": str(previous.get("stable_record_hash", "")),
        "padded_length": int(previous.get("padded_length", 0)),
        "valid_label_tokens": int(previous.get("valid_label_tokens", 0)),
        "input_ids_checksum": str(previous.get("input_ids_checksum", "")),
        "labels_checksum": str(previous.get("labels_checksum", "")),
        "attention_mask_checksum": str(previous.get("attention_mask_checksum", "")),
        "category_hash": str(previous.get("category_hash", "")),
        "shuffle_seed": int(previous.get("shuffle_seed", 0)),
        "sampler_order_fingerprint": str(
            previous.get("sampler_order_fingerprint", ""),
        ),
        "first_64_indices_hash": str(previous.get("first_64_indices_hash", "")),
    }
    _atomic_json_replace(
        state_path, state, expected_fields=STABILITY_FAILURE_STATE_FIELDS,
    )
    failure = {
        "schema_version": 1,
        "status": "failed",
        "run_id": run_id,
        "runtime_head": runtime_head,
        "failure_code": failure_code,
        "failed_stage": failed_stage,
        "failed_microbatch_index": state["failed_microbatch_index"],
        "completed_micro_batches": len(metrics),
        "optimizer_step": state["optimizer_step"],
        "sequence_length": state["sequence_length"],
        "worker_exit_code": worker_exit_code,
        "watchdog_seconds": watchdog_seconds,
        "failed_at": terminal_time,
        "problem_batch": {
            name: state[name]
            for name in (
                "dataset_index", "stable_record_hash", "sequence_length",
                "padded_length", "valid_label_tokens", "input_ids_checksum",
                "labels_checksum", "attention_mask_checksum", "category_hash",
                "shuffle_seed", "sampler_order_fingerprint", "first_64_indices_hash",
            )
        },
    }
    _exclusive_write(
        paths.staging / "failure-result.yaml",
        yaml.safe_dump(failure, allow_unicode=True, sort_keys=False),
    )
    _write_stability_failure_checksums(paths.staging)
    validator = reload_validator or validate_stability_failure
    validator(paths.staging, expected_head=runtime_head, expected_run_id=run_id)
    _rename_directory_no_replace(paths.staging, paths.failed)
    if before_directory_sync is not None:
        before_directory_sync()
    _fsync_directory(paths.failed.parent)
    result = validator(paths.failed, expected_head=runtime_head, expected_run_id=run_id)
    residue = list(paths.failed.parent.glob(f".{paths.final.name}*.tmp"))
    if paths.staging.exists() or residue:
        raise QLoRATrainingError("STABILITY_TEMP_RESIDUE")
    return result


def _stability_residue(paths: ArtifactPaths) -> list[Path]:
    candidates = [paths.staging, paths.failed]
    candidates.extend(paths.final.parent.glob(f".{paths.final.name}*.tmp"))
    candidates.extend(paths.final.parent.glob(f"{paths.final.name}*.lock"))
    return [candidate for candidate in candidates if candidate.exists()]


def require_execution_approval(*, expected_run_id: str, approved_run_id: str) -> None:
    if approved_run_id != expected_run_id:
        raise QLoRATrainingError("EXPLICIT_RUN_APPROVAL_REQUIRED")


def run_git(repository: str | Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def verify_git_identity(
    repository: str | Path,
    *,
    expected_head: str,
    expected_branch: str = "develop",
) -> dict[str, object]:
    try:
        head = run_git(repository, "rev-parse", "HEAD")
        branch = run_git(repository, "branch", "--show-current")
        status = run_git(repository, "status", "--porcelain=v1")
        remote = run_git(repository, "rev-parse", "origin/develop")
    except (OSError, subprocess.CalledProcessError):
        raise QLoRATrainingError("GIT_IDENTITY_UNAVAILABLE") from None
    if head != expected_head or remote != expected_head:
        raise QLoRATrainingError("GIT_HEAD_MISMATCH")
    if branch != expected_branch or status:
        raise QLoRATrainingError("GIT_WORKTREE_NOT_IMMUTABLE")
    return {
        "head": head,
        "branch": branch,
        "origin_develop": remote,
        "working_tree_clean": True,
    }


def environment_snapshot() -> dict[str, object]:
    import accelerate
    import bitsandbytes
    import datasets
    import peft
    import tokenizers
    import torch
    import transformers
    import trl
    from bitsandbytes.nn import Linear4bit
    from bitsandbytes.optim import PagedAdamW8bit

    if not torch.cuda.is_available():
        raise QLoRATrainingError("CUDA_REQUIRED")
    if not torch.cuda.is_bf16_supported():
        raise QLoRATrainingError("BF16_REQUIRED")
    properties = torch.cuda.get_device_properties(0)
    return {
        "captured_at": utc_now(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "cuda_runtime": str(torch.version.cuda),
        "cuda_driver": str(torch.cuda.driver_version()) if hasattr(torch.cuda, "driver_version") else None,
        "cuda_available": True,
        "bf16_supported": True,
        "gpu": torch.cuda.get_device_name(0),
        "total_vram_bytes": properties.total_memory,
        "free_vram_bytes": torch.cuda.mem_get_info(0)[0],
        "transformers": str(transformers.__version__),
        "trl": str(trl.__version__),
        "peft": str(peft.__version__),
        "accelerate": str(accelerate.__version__),
        "bitsandbytes": str(bitsandbytes.__version__),
        "bitsandbytes_4bit_available": bool(Linear4bit and PagedAdamW8bit),
        "datasets": str(datasets.__version__),
        "tokenizers": str(tokenizers.__version__),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }


def validate_environment(snapshot: Mapping[str, object]) -> None:
    gpu = str(snapshot.get("gpu", ""))
    total = int(snapshot.get("total_vram_bytes", 0))
    if (
        "RTX 3060 Ti" not in gpu
        or not bool(snapshot.get("cuda_available"))
        or not bool(snapshot.get("bf16_supported"))
        or not bool(snapshot.get("bitsandbytes_4bit_available"))
        or not 7 * 1024**3 <= total <= 9 * 1024**3
    ):
        raise QLoRATrainingError("GPU_ENVIRONMENT_INVALID")


def validate_runtime_config(config_path: str | Path) -> dict[str, object]:
    config = load_config(config_path)
    validate_qlora_config(config, bf16_supported=True)
    training = config.get("training")
    model = config.get("model")
    if not isinstance(training, Mapping) or not isinstance(model, Mapping):
        raise QLoRATrainingError("QLORA_CONFIG_INVALID")
    if (
        model.get("base_model") != MODEL_ID
        or model.get("revision") != MODEL_REVISION
        or training.get("data_seed") != 42
        or training.get("optimizer") != "paged_adamw_8bit"
        or training.get("max_grad_norm") != 1.0
        or training.get("load_best_model_at_end") is not False
    ):
        raise QLoRATrainingError("QLORA_CONFIG_INVALID")
    return config


def _parse_checksum_file(root: Path) -> dict[str, str]:
    try:
        lines = (root / "checksums.sha256").read_text(encoding="ascii").splitlines()
        values = {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in lines}
    except (OSError, IndexError, UnicodeError):
        raise QLoRATrainingError("TOKENIZED_CHECKSUM_FILE_INVALID") from None
    return values


def validate_tokenized_dataset(root: str | Path) -> dict[str, object]:
    from datasets import load_from_disk

    dataset_root = Path(root)
    expected_checksums = _parse_checksum_file(dataset_root)
    actual_checksums = {
        path.relative_to(dataset_root).as_posix(): sha256_file(path)
        for path in sorted(dataset_root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and path.name != "checksums.sha256"
    }
    if expected_checksums != actual_checksums:
        raise QLoRATrainingError("TOKENIZED_CHECKSUM_MISMATCH")
    try:
        result = yaml.safe_load(
            (dataset_root / "tokenization-result.yaml").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, yaml.YAMLError):
        raise QLoRATrainingError("TOKENIZATION_RESULT_INVALID") from None
    if not isinstance(result, Mapping):
        raise QLoRATrainingError("TOKENIZATION_RESULT_INVALID")
    artifact_fingerprint = canonical_fingerprint(actual_checksums)
    if (
        result.get("dataset_fingerprint") != DATASET_FINGERPRINT
        or result.get("tokenizer_fingerprint") != TOKENIZER_FINGERPRINT
        or artifact_fingerprint != ARTIFACT_FINGERPRINT
    ):
        raise QLoRATrainingError("TOKENIZED_FINGERPRINT_MISMATCH")

    totals: dict[str, int] = {}
    errors = {
        "invalid_sequences": 0,
        "empty_labels": 0,
        "token_range_errors": 0,
        "prompt_mask_errors": 0,
        "eos_errors": 0,
    }
    for split in ("train", "validation"):
        dataset = load_from_disk(dataset_root / split)
        if len(dataset) != EXPECTED_ROWS[split]:
            raise QLoRATrainingError("TOKENIZED_ROW_COUNT_MISMATCH")
        token_total = 0
        for row in dataset:
            ids = row["input_ids"]
            attention = row["attention_mask"]
            labels = row["labels"]
            token_total += len(ids)
            errors["invalid_sequences"] += int(
                not ids
                or len(ids) != len(attention)
                or len(ids) != len(labels)
                or len(ids) > 1536
                or any(value != 1 for value in attention)
            )
            errors["empty_labels"] += int(not any(value != IGNORE_INDEX for value in labels))
            errors["token_range_errors"] += int(
                any(value < 0 or value >= EXPECTED_TOKENIZER_LENGTH for value in ids)
                or any(
                    value != IGNORE_INDEX
                    and (value < 0 or value >= EXPECTED_TOKENIZER_LENGTH)
                    for value in labels
                )
            )
            first_label = next(
                (index for index, value in enumerate(labels) if value != IGNORE_INDEX),
                len(labels),
            )
            errors["prompt_mask_errors"] += int(
                any(value != IGNORE_INDEX for value in labels[:first_label])
                or labels[first_label:] != ids[first_label:]
            )
            errors["eos_errors"] += int(
                ids[-1] != EXPECTED_EOS_ID or labels[-1] != EXPECTED_EOS_ID
            )
        if token_total != EXPECTED_TOKENS[split]:
            raise QLoRATrainingError("TOKENIZED_TOKEN_COUNT_MISMATCH")
        totals[split] = token_total
    if any(errors.values()):
        raise QLoRATrainingError("TOKENIZED_SEQUENCE_VALIDATION_FAILED")
    return {
        "rows": dict(EXPECTED_ROWS),
        "tokens": totals,
        "dataset_fingerprint": DATASET_FINGERPRINT,
        "tokenizer_fingerprint": TOKENIZER_FINGERPRINT,
        "artifact_fingerprint": ARTIFACT_FINGERPRINT,
        "checksums": actual_checksums,
        **errors,
    }


def set_reproducible_seeds(seed: int = 42) -> None:
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


class DynamicSFTCollator:
    def __init__(self, *, pad_token_id: int, pad_to_multiple_of: int = 8) -> None:
        self.pad_token_id = pad_token_id
        self.pad_to_multiple_of = pad_to_multiple_of

    def __call__(self, features: Sequence[Mapping[str, Sequence[int]]]) -> dict[str, Any]:
        import torch

        if not features:
            raise QLoRATrainingError("EMPTY_BATCH")
        longest = max(len(feature["input_ids"]) for feature in features)
        padded = int(math.ceil(longest / self.pad_to_multiple_of) * self.pad_to_multiple_of)
        result = {"input_ids": [], "attention_mask": [], "labels": []}
        for feature in features:
            size = len(feature["input_ids"])
            if (
                not size
                or len(feature["attention_mask"]) != size
                or len(feature["labels"]) != size
                or padded > 1536
            ):
                raise QLoRATrainingError("BATCH_SEQUENCE_INVALID")
            padding = padded - size
            result["input_ids"].append([*feature["input_ids"], *([self.pad_token_id] * padding)])
            result["attention_mask"].append([*feature["attention_mask"], *([0] * padding)])
            result["labels"].append([*feature["labels"], *([IGNORE_INDEX] * padding)])
        return {name: torch.tensor(value, dtype=torch.long) for name, value in result.items()}


def _quantization_config(config: Mapping[str, object]) -> Any:
    import torch
    from transformers import BitsAndBytesConfig

    quantization = config["quantization"]
    assert isinstance(quantization, Mapping)
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type=str(quantization["quant_type"]),
        bnb_4bit_use_double_quant=bool(quantization["use_double_quant"]),
        bnb_4bit_compute_dtype=torch.bfloat16,
    )


def load_tokenizer_and_model(
    config: Mapping[str, object],
    *,
    cache_dir: str | Path,
) -> tuple[Any, Any]:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_config = config["model"]
    assert isinstance(model_config, Mapping)
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        cache_dir=cache_dir,
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        cache_dir=cache_dir,
        local_files_only=True,
        trust_remote_code=False,
        quantization_config=_quantization_config(config),
        device_map={"": 0},
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    if len(tokenizer) != EXPECTED_TOKENIZER_LENGTH:
        raise QLoRATrainingError("TOKENIZER_LENGTH_MISMATCH")
    return tokenizer, model


def attach_lora(model: Any, config: Mapping[str, object]) -> Any:
    from peft import (
        LoraConfig,
        TaskType,
        get_peft_model,
        prepare_model_for_kbit_training,
    )

    lora = config["lora"]
    assert isinstance(lora, Mapping)
    target_counts = {
        target: sum(1 for name, _ in model.named_modules() if name.endswith(target))
        for target in TARGET_MODULES
    }
    if any(value == 0 for value in target_counts.values()):
        raise QLoRATrainingError("LORA_TARGET_MODULE_MISSING")
    if len(set(target_counts.values())) != 1:
        raise QLoRATrainingError("LORA_TARGET_MODULE_COUNT_MISMATCH")
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=False,
    )
    model = get_peft_model(
        model,
        LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            inference_mode=False,
            r=int(lora["r"]),
            lora_alpha=int(lora["alpha"]),
            lora_dropout=float(lora["dropout"]),
            target_modules=list(TARGET_MODULES),
            bias="none",
        ),
    )
    invalid = [name for name, parameter in model.named_parameters() if parameter.requires_grad and "lora_" not in name]
    if invalid:
        raise QLoRATrainingError("BASE_MODEL_PARAMETER_TRAINABLE")
    enable_gradient_checkpointing_once(model)
    return model


def enable_gradient_checkpointing_once(model: Any) -> None:
    if bool(getattr(model, "is_gradient_checkpointing", False)):
        raise QLoRATrainingError("GRADIENT_CHECKPOINTING_ALREADY_ENABLED")
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
    model.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )
    if not bool(getattr(model, "is_gradient_checkpointing", False)):
        raise QLoRATrainingError("GRADIENT_CHECKPOINTING_ENABLE_FAILED")


def model_statistics(model: Any, tokenizer: Any) -> ModelStatistics:
    from bitsandbytes.nn import Linear4bit

    total = sum(parameter.numel() for parameter in model.parameters())
    trainable = sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
    target_counts = {
        target: sum(1 for name, _ in model.named_modules() if name.endswith(target))
        for target in TARGET_MODULES
    }
    device_map = {
        str(name): str(device) for name, device in getattr(model, "hf_device_map", {}).items()
    }
    if any(device in {"cpu", "disk"} for device in device_map.values()):
        raise QLoRATrainingError("UNEXPECTED_MODEL_OFFLOAD")
    unexpected_cpu = sum(
        1
        for name, parameter in model.named_parameters()
        if parameter.device.type == "cpu" and "lora_" not in name
    )
    input_embeddings = model.get_input_embeddings().weight.shape[0]
    output_embeddings = model.get_output_embeddings().weight.shape[0]
    if input_embeddings < len(tokenizer) or output_embeddings < len(tokenizer):
        raise QLoRATrainingError("MODEL_TOKENIZER_EMBEDDING_MISMATCH")
    if unexpected_cpu:
        raise QLoRATrainingError("UNEXPECTED_CPU_PARAMETERS")
    four_bit_modules = sum(1 for module in model.modules() if isinstance(module, Linear4bit))
    if not four_bit_modules:
        raise QLoRATrainingError("MODEL_NOT_QUANTIZED_4BIT")
    first_parameter = next(model.parameters())
    return ModelStatistics(
        model_class=type(model).__name__,
        total_parameters=total,
        trainable_parameters=trainable,
        trainable_ratio=trainable / total,
        four_bit_modules=four_bit_modules,
        lora_modules=sum(1 for name, _ in model.named_modules() if "lora_A" in name),
        target_counts=target_counts,
        device_map=device_map,
        unexpected_cpu_parameters=unexpected_cpu,
        input_embedding_size=input_embeddings,
        lm_head_size=output_embeddings,
        tokenizer_length=len(tokenizer),
        model_dtype=str(first_parameter.dtype),
    )


def move_batch(batch: Mapping[str, Any], device: str = "cuda:0") -> dict[str, Any]:
    return {name: value.to(device, non_blocking=True) for name, value in batch.items()}


def finite_gradients(model: Any) -> tuple[bool, float]:
    import torch

    norms = []
    for parameter in model.parameters():
        if parameter.requires_grad and parameter.grad is not None:
            if not torch.isfinite(parameter.grad).all():
                return False, math.nan
            norms.append(parameter.grad.detach().float().norm())
    if not norms:
        return False, math.nan
    return True, float(torch.stack(norms).norm().item())


def create_optimizer(model: Any, *, learning_rate: float, weight_decay: float) -> Any:
    from bitsandbytes.optim import PagedAdamW8bit

    return PagedAdamW8bit(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=learning_rate,
        weight_decay=weight_decay,
    )


def longest_record(dataset: Any) -> Mapping[str, Sequence[int]]:
    index = max(range(len(dataset)), key=lambda value: len(dataset[value]["input_ids"]))
    return dataset[index]


def nearest_record(
    datasets: Mapping[str, Any],
    target_length: int,
) -> tuple[str, int, Mapping[str, Sequence[int]]]:
    candidates = (
        (abs(len(dataset[index]["input_ids"]) - target_length), split, index)
        for split, dataset in datasets.items()
        for index in range(len(dataset))
    )
    _, split, index = min(candidates)
    return split, index, datasets[split][index]


def median_record(dataset: Any) -> tuple[int, Mapping[str, Sequence[int]]]:
    indices = sorted(range(len(dataset)), key=lambda index: len(dataset[index]["input_ids"]))
    index = indices[len(indices) // 2]
    return index, dataset[index]


def longest_record_across(
    datasets: Mapping[str, Any],
) -> tuple[str, int, Mapping[str, Sequence[int]]]:
    values = (
        (len(dataset[index]["input_ids"]), split, index)
        for split, dataset in datasets.items()
        for index in range(len(dataset))
    )
    _, split, index = max(values)
    return split, index, datasets[split][index]


def batch_statistics(batch: Mapping[str, Any]) -> dict[str, int]:
    return {
        "actual_sequence_length": int(batch["attention_mask"].sum().item()),
        "padded_length": int(batch["input_ids"].shape[1]),
        "padding_tokens": int((batch["attention_mask"] == 0).sum().item()),
        "label_tokens": int((batch["labels"] != IGNORE_INDEX).sum().item()),
    }


def run_allocation_smoke(
    *,
    model: Any,
    tokenizer: Any,
    train_dataset: Any,
    validation_dataset: Any,
    reporter: StageReporter | None = None,
    device: str = "cuda:0",
    autocast_enabled: bool = True,
    run_id: str = ALLOCATION_SMOKE_RUN_ID,
) -> dict[str, object]:
    import torch

    tracker = reporter or StageReporter()
    with tracker.stage("collator_validation", timeout_seconds=120):
        collator = DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
        median_index, median = median_record(train_dataset)
        longest_split, longest_index, longest = longest_record_across({
            "train": train_dataset,
            "validation": validation_dataset,
        })
    started = time.perf_counter()
    selected = (
        ("allocation_forward_median", "train", median_index, median),
        ("allocation_forward_longest", longest_split, longest_index, longest),
    )
    batches = []
    model.train()
    for stage_name, split, index, record in selected:
        batch = move_batch(collator([record]), device=device)
        statistics = batch_statistics(batch)
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        with tracker.stage(
            stage_name,
            timeout_seconds=STAGE_TIMEOUTS[stage_name],
            sequence_length=statistics["actual_sequence_length"],
        ):
            forward_started = time.perf_counter()
            with torch.autocast(
                device_type=device.split(":", maxsplit=1)[0],
                dtype=torch.bfloat16,
                enabled=autocast_enabled,
            ):
                outputs = model(**batch)
            torch.cuda.synchronize()
            forward_seconds = time.perf_counter() - forward_started
        loss = outputs.loss
        if loss is None or not torch.isfinite(loss) or not loss.requires_grad:
            raise QLoRATrainingError("ALLOCATION_FORWARD_GRAPH_INVALID")
        batches.append({
            "role": "median" if stage_name.endswith("median") else "longest",
            "split": split,
            "index": index,
            **statistics,
            "loss": float(loss.detach().item()),
            "loss_finite": True,
            "forward_graph_created": True,
            "forward_seconds": forward_seconds,
            "allocated_bytes": torch.cuda.memory_allocated(),
            "reserved_bytes": torch.cuda.memory_reserved(),
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        })
        del outputs, loss, batch
        torch.cuda.empty_cache()
    result = {
        "status": "passed",
        "run_id": run_id,
        "model_loaded": True,
        "quantized_modules_valid": True,
        "lora_attached": True,
        "base_weights_frozen": True,
        "device_placement_valid": True,
        "cpu_offload": False,
        "cuda_oom": False,
        "batches": batches,
        "duration_seconds": time.perf_counter() - started,
        "backward_calls": 0,
        "optimizer_creations": 0,
        "optimizer_steps": 0,
        "stage_events": list(tracker.events),
    }
    return result


def run_backward_diagnostic(
    *,
    model: Any,
    tokenizer: Any,
    train_dataset: Any,
    validation_dataset: Any,
    target_length: int,
    reporter: StageReporter | None = None,
    device: str = "cuda:0",
    autocast_enabled: bool = True,
    run_id: str = BACKWARD_DIAGNOSTIC_RUN_ID,
    timeout_seconds: float = STAGE_TIMEOUTS["backward_diagnostic"],
) -> dict[str, object]:
    import torch

    if target_length not in BACKWARD_DIAGNOSTIC_LENGTHS:
        raise QLoRATrainingError("BACKWARD_DIAGNOSTIC_LENGTH_INVALID")
    tracker = reporter or StageReporter()
    split, index, record = nearest_record(
        {"train": train_dataset, "validation": validation_dataset}, target_length,
    )
    collator = DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
    batch = move_batch(collator([record]), device=device)
    statistics = batch_statistics(batch)
    model.train()
    model.zero_grad(set_to_none=True)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    with tracker.stage(
        "backward_diagnostic",
        timeout_seconds=timeout_seconds,
        sequence_length=statistics["actual_sequence_length"],
    ):
        forward_started = time.perf_counter()
        with torch.autocast(
            device_type=device.split(":", maxsplit=1)[0],
            dtype=torch.bfloat16,
            enabled=autocast_enabled,
        ):
            outputs = model(**batch)
            loss = outputs.loss
        torch.cuda.synchronize()
        forward_seconds = time.perf_counter() - forward_started
        if loss is None or not torch.isfinite(loss):
            raise QLoRATrainingError("BACKWARD_DIAGNOSTIC_LOSS_NONFINITE")
        backward_started = time.perf_counter()
        loss.backward()
        torch.cuda.synchronize()
        backward_seconds = time.perf_counter() - backward_started
    gradients_finite, gradient_norm = finite_gradients(model)
    lora_gradients = sum(
        1 for name, parameter in model.named_parameters()
        if "lora_" in name and parameter.grad is not None
    )
    base_gradients = sum(
        1 for name, parameter in model.named_parameters()
        if "lora_" not in name and parameter.grad is not None
    )
    if not gradients_finite or not lora_gradients or base_gradients:
        raise QLoRATrainingError("BACKWARD_DIAGNOSTIC_GRADIENT_INVALID")
    total_seconds = time.perf_counter() - started
    if backward_seconds <= 120:
        classification = "BACKWARD_PRACTICAL"
    elif backward_seconds <= timeout_seconds:
        classification = "BACKWARD_SLOW_BUT_BOUNDED"
    else:
        classification = "BACKWARD_TIMEOUT"
    result = {
        "status": "passed",
        "run_id": run_id,
        "target_length": target_length,
        "split": split,
        "index": index,
        **statistics,
        "forward_seconds": forward_seconds,
        "backward_seconds": backward_seconds,
        "total_seconds": total_seconds,
        "loss": float(loss.detach().item()),
        "loss_finite": True,
        "gradient_finite": True,
        "gradient_norm": gradient_norm,
        "lora_gradient_tensors": lora_gradients,
        "base_gradient_tensors": base_gradients,
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
        "optimizer_creations": 0,
        "optimizer_steps": 0,
        "classification": classification,
        "stage_events": list(tracker.events),
    }
    model.zero_grad(set_to_none=True)
    del outputs, loss, batch
    torch.cuda.empty_cache()
    return result


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_yaml(path: Path, value: object) -> None:
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )


def file_checksums(root: str | Path, *, exclude: Sequence[str] = ("checksums.sha256",)) -> dict[str, str]:
    base = Path(root)
    return {
        path.relative_to(base).as_posix(): sha256_file(path)
        for path in sorted(base.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and path.name not in exclude
    }


def write_checksums(root: str | Path) -> dict[str, str]:
    base = Path(root)
    checksums = file_checksums(base)
    (base / "checksums.sha256").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in checksums.items()),
        encoding="ascii",
    )
    return checksums


def publish_result_artifact(
    paths: ArtifactPaths,
    *,
    filename: str,
    result: Mapping[str, object],
    environment: Mapping[str, object],
) -> None:
    paths.staging.mkdir(parents=True)
    try:
        _write_yaml(paths.staging / filename, dict(result))
        _write_json(paths.staging / "environment.json", dict(environment))
        write_checksums(paths.staging)
        publish_staging(paths)
    except Exception:
        quarantine_staging(paths)
        raise


def validate_result_artifact(
    root: str | Path,
    *,
    filename: str,
    expected_run_id: str,
) -> dict[str, object]:
    base = Path(root)
    try:
        result = yaml.safe_load((base / filename).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise QLoRATrainingError("RESULT_ARTIFACT_REQUIRED") from None
    if not isinstance(result, Mapping):
        raise QLoRATrainingError("RESULT_ARTIFACT_REQUIRED")
    if _parse_checksum_file(base) != file_checksums(base):
        raise QLoRATrainingError("RESULT_ARTIFACT_CHECKSUM_MISMATCH")
    if result.get("status") != "passed" or result.get("run_id") != expected_run_id:
        raise QLoRATrainingError("RESULT_ARTIFACT_INVALID")
    return dict(result)


def release_cuda(*objects: Any) -> None:
    import gc

    import torch

    del objects
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.synchronize()


def run_training_smoke(
    *,
    paths: ArtifactPaths,
    config: Mapping[str, object],
    cache_dir: str | Path,
    tokenized_root: str | Path,
    environment: Mapping[str, object],
    git_identity: Mapping[str, object],
    allocation_result: Mapping[str, object],
    model_statistics_value: Mapping[str, object],
    micro_batches: int,
    validation_batches: int,
    stage_number: int,
    reporter: StageReporter | None = None,
    run_id: str = TRAINING_SMOKE_RUN_ID,
    micro_batch_timeout_seconds: float = STAGE_TIMEOUTS["training_smoke"],
) -> dict[str, object]:
    import torch
    from datasets import load_from_disk
    from peft import PeftModel
    from transformers import get_cosine_schedule_with_warmup

    if (stage_number, micro_batches, validation_batches) not in {(1, 2, 1), (2, 16, 2)}:
        raise QLoRATrainingError("TRAINING_SMOKE_STAGE_INVALID")
    tracker = reporter or StageReporter()
    paths.staging.mkdir(parents=True)
    checkpoint = paths.staging / "checkpoint-1"
    try:
        with tracker.stage("model_loading", timeout_seconds=STAGE_TIMEOUTS["model_loading"]):
            tokenizer, base_model = load_tokenizer_and_model(config, cache_dir=cache_dir)
        with tracker.stage("lora_injection", timeout_seconds=120):
            model = attach_lora(base_model, config)
        train = load_from_disk(Path(tokenized_root) / "train")
        validation = load_from_disk(Path(tokenized_root) / "validation")
        generator = random.Random(42)
        train_indices = generator.sample(range(len(train)), micro_batches)
        validation_indices = list(range(validation_batches))
        collator = DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
        training = config["training"]
        assert isinstance(training, Mapping)
        with tracker.stage("training_smoke_optimizer_init", timeout_seconds=120):
            optimizer = create_optimizer(
                model,
                learning_rate=float(training["learning_rate"]),
                weight_decay=float(training["weight_decay"]),
            )
            scheduler = get_cosine_schedule_with_warmup(
                optimizer, num_warmup_steps=0, num_training_steps=1,
            )
        base_parameter_versions = {
            name: parameter._version
            for name, parameter in model.named_parameters()
            if "lora_" not in name
        }
        if any(
            parameter.requires_grad
            for name, parameter in model.named_parameters()
            if "lora_" not in name
        ):
            raise QLoRATrainingError("BASE_MODEL_PARAMETER_TRAINABLE")
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        losses = []
        micro_batch_seconds = []
        optimizer.zero_grad(set_to_none=True)
        for batch_number, index in enumerate(train_indices, start=1):
            batch_started = time.perf_counter()
            batch = move_batch(collator([train[index]]))
            with tracker.stage(
                "training_smoke_forward",
                timeout_seconds=micro_batch_timeout_seconds,
                batch_number=batch_number,
            ):
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    outputs = model(**batch)
                    loss = outputs.loss
                if loss is None or not torch.isfinite(loss):
                    raise QLoRATrainingError("TRAINING_SMOKE_LOSS_NONFINITE")
                losses.append(float(loss.detach().item()))
            with tracker.stage(
                "training_smoke_backward",
                timeout_seconds=micro_batch_timeout_seconds,
                batch_number=batch_number,
            ):
                (loss / micro_batches).backward()
                torch.cuda.synchronize()
            micro_batch_seconds.append(time.perf_counter() - batch_started)
            del outputs, loss, batch
        gradients_finite, gradient_norm = finite_gradients(model)
        if not gradients_finite:
            raise QLoRATrainingError("TRAINING_SMOKE_GRADIENT_NONFINITE")
        torch.nn.utils.clip_grad_norm_(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            float(training["max_grad_norm"]),
        )
        trainable_before = {
            name: parameter.detach().clone()
            for name, parameter in model.named_parameters()
            if parameter.requires_grad
        }
        optimizer_started = time.perf_counter()
        with tracker.stage(
            "training_smoke_optimizer_step",
            timeout_seconds=STAGE_TIMEOUTS["training_smoke"],
        ):
            optimizer.step()
            scheduler.step()
            torch.cuda.synchronize()
        optimizer_seconds = time.perf_counter() - optimizer_started
        lora_weights_changed = any(
            not torch.equal(trainable_before[name], parameter.detach())
            for name, parameter in model.named_parameters()
            if parameter.requires_grad
        )
        if not lora_weights_changed:
            raise QLoRATrainingError("TRAINING_SMOKE_LORA_NOT_UPDATED")
        base_weights_changed = any(
            base_parameter_versions[name] != parameter._version
            for name, parameter in model.named_parameters()
            if "lora_" not in name
        )
        if base_weights_changed:
            raise QLoRATrainingError("TRAINING_SMOKE_BASE_WEIGHT_CHANGED")
        optimizer.zero_grad(set_to_none=True)
        checkpoint_started = time.perf_counter()
        with tracker.stage(
            "training_smoke_checkpoint",
            timeout_seconds=STAGE_TIMEOUTS["training_smoke"],
        ):
            model.save_pretrained(checkpoint, safe_serialization=True)
        checkpoint_seconds = time.perf_counter() - checkpoint_started
        trainer_state = {
            "global_step": 1,
            "micro_batches": micro_batches,
            "gradient_accumulation_steps": micro_batches,
            "scheduler_steps": 1,
            "gradient_norm": gradient_norm,
        }
        _write_json(checkpoint / "trainer_state.json", trainer_state)
        checkpoint_result = validate_checkpoint(checkpoint)
        reloaded_trainer_state = json.loads(
            (checkpoint / "trainer_state.json").read_text(encoding="utf-8"),
        )
        if reloaded_trainer_state != trainer_state:
            raise QLoRATrainingError("TRAINING_SMOKE_TRAINER_STATE_RELOAD_FAILED")
        checkpoint_result["path"] = "checkpoint-1"
        model.eval()
        eval_losses = []
        eval_started = time.perf_counter()
        with tracker.stage(
            "training_smoke_evaluation",
            timeout_seconds=STAGE_TIMEOUTS["training_smoke"],
            validation_batches=validation_batches,
        ):
            with torch.no_grad():
                for index in validation_indices:
                    batch = move_batch(collator([validation[index]]))
                    with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                        loss = model(**batch).loss
                    if loss is None or not torch.isfinite(loss):
                        raise QLoRATrainingError("TRAINING_SMOKE_EVAL_NONFINITE")
                    eval_losses.append(float(loss.item()))
                    del loss, batch
            torch.cuda.synchronize()
        evaluation_seconds = time.perf_counter() - eval_started
        peak = torch.cuda.max_memory_allocated()
        del optimizer, scheduler, model, base_model
        release_cuda()
        with tracker.stage(
            "training_smoke_reload",
            timeout_seconds=STAGE_TIMEOUTS["training_smoke_reload"],
        ):
            _, reload_base = load_tokenizer_and_model(config, cache_dir=cache_dir)
            reload_model = PeftModel.from_pretrained(reload_base, checkpoint, is_trainable=False)
            reload_model.eval()
            with torch.no_grad():
                batch = move_batch(collator([validation[0]]))
                reload_loss = reload_model(**batch).loss
                reload_valid = reload_loss is not None and bool(torch.isfinite(reload_loss).item())
        if not reload_valid:
            raise QLoRATrainingError("TRAINING_SMOKE_CHECKPOINT_RELOAD_FAILED")
        result = {
            "status": "passed",
            "run_id": run_id,
            "stage_number": stage_number,
            "created_at": utc_now(),
            "allocation_smoke": dict(allocation_result),
            "micro_batches": micro_batches,
            "gradient_accumulation_steps": micro_batches,
            "optimizer_steps": 1,
            "scheduler_steps": 1,
            "train_loss_mean": sum(losses) / len(losses),
            "train_loss_final": losses[-1],
            "eval_batches": validation_batches,
            "eval_loss": sum(eval_losses) / len(eval_losses),
            "micro_batch_seconds": micro_batch_seconds,
            "average_micro_batch_seconds": sum(micro_batch_seconds) / len(micro_batch_seconds),
            "optimizer_step_seconds": optimizer_seconds,
            "evaluation_seconds": evaluation_seconds,
            "checkpoint_seconds": checkpoint_seconds,
            "gradient_norm": gradient_norm,
            "peak_allocated_bytes": peak,
            "duration_seconds": time.perf_counter() - started,
            "checkpoint": "checkpoint-1",
            "checkpoint_validation": checkpoint_result,
            "checkpoint_reload": True,
            "lora_weights_changed": True,
            "base_weights_changed": base_weights_changed,
            "trainer_state_reload": True,
            "model_statistics": dict(model_statistics_value),
            "git": dict(git_identity),
            "dataset_fingerprint": DATASET_FINGERPRINT,
            "tokenizer_fingerprint": TOKENIZER_FINGERPRINT,
            "source_processing_run": SOURCE_PROCESSING_RUN,
            "tokenization_run": TOKENIZATION_RUN,
            "stage_events": list(tracker.events),
        }
        if stage_number == 2:
            result["runtime_estimate"] = estimate_full_runtime(result)
        result["artifact_fingerprint"] = canonical_fingerprint(
            checkpoint_result["checksums"],
        )
        _write_yaml(paths.staging / "smoke-result.yaml", result)
        _write_json(paths.staging / "environment.json", dict(environment))
        write_checksums(paths.staging)
        del reload_model, reload_base, reload_loss, batch
        release_cuda()
        publish_staging(paths)
        return result
    except Exception:
        quarantine_staging(paths)
        raise


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def run_stability_smoke(
    *,
    paths: ArtifactPaths,
    model: Any,
    tokenizer: Any,
    train_dataset: Any,
    config: Mapping[str, object],
    environment: Mapping[str, object],
    git_identity: Mapping[str, object],
    dataset_identity: Mapping[str, object],
    model_statistics_value: Mapping[str, object],
    training_smoke_result: Mapping[str, object],
    reporter: StageReporter | None = None,
    run_id: str = WSL_STABILITY_RUN_ID,
    device: str = "cuda:0",
    autocast_enabled: bool = True,
    micro_batches: int = 128,
    gradient_accumulation_steps: int = 16,
    publish_phase_hook: Callable[[str], None] | None = None,
    supervisor_managed_failure: bool = False,
) -> dict[str, object]:
    import torch
    from transformers import get_cosine_schedule_with_warmup

    tracker = reporter or StageReporter()
    phase_hook = publish_phase_hook or (lambda _phase: None)
    expected_optimizer_steps = micro_batches // gradient_accumulation_steps
    if (
        micro_batches <= 0
        or gradient_accumulation_steps <= 0
        or micro_batches % gradient_accumulation_steps
    ):
        raise QLoRATrainingError("STABILITY_BUDGET_INVALID")
    paths.staging.mkdir(parents=True)
    runtime_head = str(git_identity.get("head", ""))
    state = StabilityStateWriter(
        paths.staging / "stage-state.json", run_id=run_id, runtime_head=runtime_head,
    )
    metrics = StabilityMetricsWriter(paths.staging / "batch-metrics.jsonl")
    _exclusive_write(
        paths.staging / "environment.json",
        json.dumps(dict(environment), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )
    try:
        training = config["training"]
        assert isinstance(training, Mapping)
        indices = list(range(len(train_dataset)))
        shuffle_seed = int(training["seed"])
        random.Random(shuffle_seed).shuffle(indices)
        sampler_order_fingerprint = canonical_fingerprint(indices)
        first_64_indices_hash = canonical_fingerprint(indices[:64])
        indices = indices[:micro_batches]
        if len(indices) != micro_batches:
            raise QLoRATrainingError("STABILITY_DATASET_TOO_SMALL")
        collator = DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
        optimizer = create_optimizer(
            model,
            learning_rate=float(training["learning_rate"]),
            weight_decay=float(training["weight_decay"]),
        )
        scheduler = get_cosine_schedule_with_warmup(
            optimizer, num_warmup_steps=0, num_training_steps=expected_optimizer_steps,
        )
        base_versions = {
            name: parameter._version
            for name, parameter in model.named_parameters()
            if "lora_" not in name
        }
        trainable_before = {
            name: parameter.detach().clone()
            for name, parameter in model.named_parameters()
            if parameter.requires_grad
        }
        model.train()
        optimizer.zero_grad(set_to_none=True)
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        records: list[dict[str, object]] = []
        optimizer_steps = 0
        optimizer_times: list[float] = []
        for micro_batch, index in enumerate(indices, start=1):
            source_record = train_dataset[index]
            batch = move_batch(collator([source_record]), device=device)
            statistics = batch_statistics(batch)
            sequence_length = statistics["actual_sequence_length"]
            problem_batch = stability_batch_identity(
                source_record,
                dataset_index=index,
                padded_length=statistics["padded_length"],
                valid_label_tokens=statistics["label_tokens"],
                shuffle_seed=shuffle_seed,
                sampler_order_fingerprint=sampler_order_fingerprint,
                first_64_indices_hash=first_64_indices_hash,
            )
            state.update(
                status="running", current_stage="batch_loaded",
                microbatch_index=micro_batch, optimizer_step=optimizer_steps,
                sequence_length=sequence_length,
                problem_batch=problem_batch,
            )
            forward_started = time.perf_counter()
            state.update(
                status="running", current_stage="forward_started",
                microbatch_index=micro_batch, optimizer_step=optimizer_steps,
                sequence_length=sequence_length,
            )
            with tracker.stage(
                "stability_forward",
                timeout_seconds=STAGE_TIMEOUTS["stability_micro_batch"],
                micro_batch=micro_batch,
                sequence_length=statistics["actual_sequence_length"],
            ):
                with torch.autocast(
                    device_type=device.split(":", maxsplit=1)[0],
                    dtype=torch.bfloat16,
                    enabled=autocast_enabled,
                ):
                    outputs = model(**batch)
                    loss = outputs.loss
                torch.cuda.synchronize()
            forward_seconds = time.perf_counter() - forward_started
            state.update(
                status="running", current_stage="forward_completed",
                microbatch_index=micro_batch, optimizer_step=optimizer_steps,
                sequence_length=sequence_length,
            )
            if loss is None or not torch.isfinite(loss):
                raise QLoRATrainingError("STABILITY_LOSS_NONFINITE")
            backward_started = time.perf_counter()
            state.update(
                status="running", current_stage="backward_started",
                microbatch_index=micro_batch, optimizer_step=optimizer_steps,
                sequence_length=sequence_length,
            )
            with tracker.stage(
                "stability_backward",
                timeout_seconds=STAGE_TIMEOUTS["stability_micro_batch"],
                micro_batch=micro_batch,
                sequence_length=statistics["actual_sequence_length"],
            ):
                (loss / gradient_accumulation_steps).backward()
                torch.cuda.synchronize()
            backward_seconds = time.perf_counter() - backward_started
            state.update(
                status="running", current_stage="backward_completed",
                microbatch_index=micro_batch, optimizer_step=optimizer_steps,
                sequence_length=sequence_length,
            )
            gradients_finite, gradient_norm = finite_gradients(model)
            if not gradients_finite:
                raise QLoRATrainingError("STABILITY_GRADIENT_NONFINITE")
            if micro_batch % gradient_accumulation_steps == 0:
                state.update(
                    status="running", current_stage="optimizer_step_started",
                    microbatch_index=micro_batch, optimizer_step=optimizer_steps,
                    sequence_length=sequence_length,
                )
                torch.nn.utils.clip_grad_norm_(
                    [parameter for parameter in model.parameters() if parameter.requires_grad],
                    float(training["max_grad_norm"]),
                )
                optimizer_started = time.perf_counter()
                optimizer.step()
                scheduler.step()
                torch.cuda.synchronize()
                optimizer_times.append(time.perf_counter() - optimizer_started)
                optimizer.zero_grad(set_to_none=True)
                optimizer_steps += 1
                state.update(
                    status="running", current_stage="optimizer_step_completed",
                    microbatch_index=micro_batch, optimizer_step=optimizer_steps,
                    sequence_length=sequence_length,
                )
            allocated, reserved, peak = _cuda_memory()
            utilization, temperature = _gpu_health()
            loss_value = float(loss.detach().item())
            record = {
                "run_id": run_id,
                "runtime_head": runtime_head,
                "microbatch_index": micro_batch,
                "optimizer_step": optimizer_steps,
                "sequence_length": sequence_length,
                "padded_length": statistics["padded_length"],
                "valid_label_tokens": statistics["label_tokens"],
                "forward_seconds": forward_seconds,
                "backward_seconds": backward_seconds,
                "total_seconds": forward_seconds + backward_seconds,
                "loss": loss_value,
                "gradient_norm": gradient_norm,
                "allocated_vram_bytes": allocated,
                "reserved_vram_bytes": reserved,
                "peak_vram_bytes": peak,
                "gpu_utilization_percent": utilization,
                "gpu_temperature_c": temperature,
                "stage": "microbatch_completed",
                "timestamp": utc_now(),
            }
            metrics.append(record)
            records.append(record)
            del outputs, loss, batch
            # WSL2 can retain variable-length activation blocks until the CUDA
            # pool reaches physical VRAM and starts paging. Release only cached
            # blocks after the completed backward; gradients and optimizer state
            # remain live and the training contract is unchanged.
            torch.cuda.empty_cache()
        if optimizer_steps != expected_optimizer_steps:
            raise QLoRATrainingError("STABILITY_OPTIMIZER_STEP_MISMATCH")
        lora_changed = any(
            not torch.equal(trainable_before[name], parameter.detach())
            for name, parameter in model.named_parameters()
            if parameter.requires_grad
        )
        base_changed = any(
            base_versions[name] != parameter._version
            for name, parameter in model.named_parameters()
            if "lora_" not in name
        )
        if not lora_changed or base_changed:
            raise QLoRATrainingError("STABILITY_WEIGHT_CONTRACT_FAILED")
        durations = [float(record["total_seconds"]) for record in records]
        training_seconds = (sum(durations) / len(durations)) * EXPECTED_ROWS["train"] * 3
        optimizer_seconds = (sum(optimizer_times) / len(optimizer_times)) * 1947
        evaluation_per_batch = float(training_smoke_result["evaluation_seconds"]) / int(
            training_smoke_result["eval_batches"],
        )
        evaluation_seconds = evaluation_per_batch * EXPECTED_ROWS["validation"] * 20
        checkpoint_seconds = float(training_smoke_result["checkpoint_seconds"]) * 7
        total_estimate = (
            training_seconds + optimizer_seconds + evaluation_seconds + checkpoint_seconds
        )
        result: dict[str, object] = {
            "status": "passed",
            "run_id": run_id,
            "created_at": utc_now(),
            "micro_batches": len(records),
            "optimizer_steps": optimizer_steps,
            "stalled_batches": 0,
            "nonfinite_losses": 0,
            "mean_batch_seconds": sum(durations) / len(durations),
            "p50_batch_seconds": _percentile(durations, 0.50),
            "p90_batch_seconds": _percentile(durations, 0.90),
            "p95_batch_seconds": _percentile(durations, 0.95),
            "p99_batch_seconds": _percentile(durations, 0.99),
            "max_batch_seconds": max(durations),
            "mean_optimizer_seconds": sum(optimizer_times) / len(optimizer_times),
            "duration_seconds": time.perf_counter() - started,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
            "lora_weights_changed": True,
            "base_weights_changed": False,
            "git": dict(git_identity),
            "dataset": dict(dataset_identity),
            "model_statistics": dict(model_statistics_value),
            "runtime_estimate": {
                "training_seconds": training_seconds,
                "optimizer_seconds": optimizer_seconds,
                "evaluation_seconds": evaluation_seconds,
                "checkpoint_seconds": checkpoint_seconds,
                "epoch_seconds": total_estimate / 3,
                "total_seconds": total_estimate,
                "total_hours": total_estimate / 3600,
                "acceptable": total_estimate <= 72 * 3600,
                "acceptance_limit_hours": 72,
            },
        }
        with tracker.stage(
            "stability_result_publish",
            timeout_seconds=STAGE_TIMEOUTS["stability_result_publish"],
        ):
            phase_hook("metrics_finalization")
            state.update(
                status="publishing", current_stage="metrics_finalizing",
                microbatch_index=micro_batches, optimizer_step=optimizer_steps,
            )
            metrics.finalize()
            state.update(
                status="publishing", current_stage="result_publishing",
                microbatch_index=micro_batches, optimizer_step=optimizer_steps,
            )
            _exclusive_write(
                paths.staging / "stability-result.yaml",
                yaml.safe_dump(result, allow_unicode=True, sort_keys=False),
            )
            state.update(
                status="completed", current_stage="completed",
                microbatch_index=micro_batches, optimizer_step=optimizer_steps,
            )
            phase_hook("checksum_creation")
            _write_stability_checksums(paths.staging)
            validate_stability_result(
                paths.staging,
                expected_head=runtime_head,
                expected_run_id=run_id,
                expected_micro_batches=micro_batches,
                expected_optimizer_steps=expected_optimizer_steps,
                expected_config_fingerprint=str(environment.get("config_fingerprint", "")),
            )
            phase_hook("atomic_publish")
            publish_staging(
                paths,
                before_directory_sync=lambda: phase_hook("directory_sync"),
            )
            phase_hook("reload_validation")
            validate_stability_result(
                paths.final,
                expected_head=runtime_head,
                expected_run_id=run_id,
                expected_micro_batches=micro_batches,
                expected_optimizer_steps=expected_optimizer_steps,
                expected_config_fingerprint=str(environment.get("config_fingerprint", "")),
            )
            if _stability_residue(paths):
                raise QLoRATrainingError("STABILITY_TEMP_RESIDUE")
        return result
    except Exception as error:
        metrics.finalize()
        if paths.staging.exists() and not supervisor_managed_failure:
            try:
                previous = json.loads(
                    (paths.staging / "stage-state.json").read_text(encoding="utf-8"),
                )
                finalize_stability_failure(
                    paths,
                    failure_code=(
                        str(error) if isinstance(error, QLoRATrainingError)
                        else type(error).__name__
                    ),
                    failed_stage=str(previous.get("current_stage", "unknown")),
                    worker_exit_code=1,
                    watchdog_seconds=STAGE_TIMEOUTS["stability_micro_batch"],
                )
            except (OSError, QLoRATrainingError, ValueError) as state_error:
                tracker.emit(
                    "stability_failure_publish", "failed",
                    error_code=str(state_error),
                )
        elif paths.final.exists():
            quarantine_stability_publication(paths)
        raise


def validate_stability_result(
    root: str | Path,
    *,
    expected_head: str,
    expected_run_id: str = WSL_STABILITY_RUN_ID,
    expected_micro_batches: int = 128,
    expected_optimizer_steps: int = 8,
    expected_config_fingerprint: str | None = None,
) -> dict[str, object]:
    base = Path(root)
    if {path.name for path in base.iterdir()} != STABILITY_REQUIRED_FILES:
        raise QLoRATrainingError("STABILITY_FILE_SET_INVALID")
    try:
        result = yaml.safe_load((base / "stability-result.yaml").read_text(encoding="utf-8"))
        environment = json.loads((base / "environment.json").read_text(encoding="utf-8"))
        state = json.loads((base / "stage-state.json").read_text(encoding="utf-8"))
        metric_lines = (base / "batch-metrics.jsonl").read_text(encoding="utf-8").splitlines()
        metrics = [json.loads(line) for line in metric_lines]
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        raise QLoRATrainingError("STABILITY_RESULT_INVALID") from None
    if not isinstance(result, Mapping) or not isinstance(environment, Mapping):
        raise QLoRATrainingError("STABILITY_RESULT_INVALID")
    expected_checksums = _parse_checksum_file(base)
    actual_checksums = {name: sha256_file(base / name) for name in STABILITY_PAYLOAD_FILES}
    if expected_checksums != actual_checksums:
        raise QLoRATrainingError("STABILITY_CHECKSUM_MISMATCH")
    git = result.get("git")
    dataset = result.get("dataset")
    model = result.get("model_statistics")
    synthetic = environment.get("platform") == "synthetic"
    expected_dataset_fingerprint = "synthetic" if synthetic else DATASET_FINGERPRINT
    accumulation = expected_micro_batches // expected_optimizer_steps
    if (
        result.get("status") != "passed"
        or result.get("run_id") != expected_run_id
        or result.get("micro_batches") != expected_micro_batches
        or result.get("optimizer_steps") != expected_optimizer_steps
        or result.get("stalled_batches") != 0
        or result.get("nonfinite_losses") != 0
        or result.get("lora_weights_changed") is not True
        or result.get("base_weights_changed") is not False
        or float(result.get("max_batch_seconds", 301)) >= 300
        or not isinstance(git, Mapping)
        or git.get("head") != expected_head
        or not isinstance(dataset, Mapping)
        or dataset.get("dataset_fingerprint") != expected_dataset_fingerprint
        or not isinstance(model, Mapping)
        or state.get("status") != "completed"
        or state.get("current_stage") != "completed"
        or state.get("run_id") != expected_run_id
        or state.get("runtime_head") != expected_head
        or len(metrics) != expected_micro_batches
        or any(set(metric) != set(STABILITY_METRIC_FIELDS) for metric in metrics)
        or [metric.get("microbatch_index") for metric in metrics]
        != list(range(1, expected_micro_batches + 1))
        or [metric.get("optimizer_step") for metric in metrics]
        != [index // accumulation for index in range(1, expected_micro_batches + 1)]
        or any(metric.get("run_id") != expected_run_id for metric in metrics)
        or any(metric.get("runtime_head") != expected_head for metric in metrics)
        or (
            expected_config_fingerprint is not None
            and environment.get("config_fingerprint") != expected_config_fingerprint
        )
        or environment.get("model_revision") != MODEL_REVISION
    ):
        raise QLoRATrainingError("STABILITY_RESULT_INVALID")
    return dict(result)


def validate_training_smoke_stage(
    smoke_root: str | Path,
    *,
    stage_number: int,
    expected_head: str,
    expected_run_id: str = TRAINING_SMOKE_RUN_ID,
) -> dict[str, object]:
    result = validate_result_artifact(
        smoke_root,
        filename="smoke-result.yaml",
        expected_run_id=expected_run_id,
    )
    allocation = result.get("allocation_smoke")
    git = result.get("git")
    if (
        result.get("stage_number") != stage_number
        or result.get("optimizer_steps") != 1
        or result.get("checkpoint_reload") is not True
        or result.get("lora_weights_changed") is not True
        or result.get("base_weights_changed") is not False
        or not isinstance(allocation, Mapping)
        or allocation.get("status") != "passed"
        or allocation.get("backward_calls") != 0
        or allocation.get("optimizer_creations") != 0
        or int(result.get("peak_allocated_bytes", 9 * 1024**3)) >= 8 * 1024**3
        or not isinstance(git, Mapping)
        or git.get("head") != expected_head
    ):
        raise QLoRATrainingError("SMOKE_READINESS_FAILED")
    return dict(result)


def smoke_is_valid(
    smoke_root: str | Path,
    *,
    expected_head: str,
    expected_run_id: str = TRAINING_SMOKE_RUN_ID,
) -> dict[str, object]:
    return validate_training_smoke_stage(
        smoke_root,
        stage_number=2,
        expected_head=expected_head,
        expected_run_id=expected_run_id,
    )


def validate_backward_diagnostic(
    root: str | Path,
    *,
    target_length: int,
    expected_head: str | None = None,
    expected_run_id: str = BACKWARD_DIAGNOSTIC_RUN_ID,
) -> dict[str, object]:
    result = validate_result_artifact(
        root,
        filename="backward-result.yaml",
        expected_run_id=expected_run_id,
    )
    git = result.get("git")
    if (
        result.get("target_length") != target_length
        or result.get("gradient_finite") is not True
        or int(result.get("lora_gradient_tensors", 0)) <= 0
        or result.get("base_gradient_tensors") != 0
        or result.get("optimizer_steps") != 0
        or (
            expected_head is not None
            and (not isinstance(git, Mapping) or git.get("head") != expected_head)
        )
    ):
        raise QLoRATrainingError("BACKWARD_DIAGNOSTIC_RESULT_INVALID")
    return result


def validate_backward_diagnostics(
    root: str | Path,
    *,
    expected_head: str | None = None,
    expected_run_id: str = BACKWARD_DIAGNOSTIC_RUN_ID,
) -> list[dict[str, object]]:
    base = Path(root)
    results = []
    for length in BACKWARD_DIAGNOSTIC_LENGTHS:
        result = validate_backward_diagnostic(
            base / f"length-{length}",
            target_length=length,
            expected_head=expected_head,
            expected_run_id=expected_run_id,
        )
        results.append(result)
    return results


def estimate_full_runtime(stage_two_result: Mapping[str, object]) -> dict[str, object]:
    average_micro_batch = float(stage_two_result["average_micro_batch_seconds"])
    evaluation_per_batch = float(stage_two_result["evaluation_seconds"]) / int(
        stage_two_result["eval_batches"],
    )
    train_micro_batches = EXPECTED_ROWS["train"] * 3
    evaluation_events = 19
    evaluation_batches = EXPECTED_ROWS["validation"] * (evaluation_events + 1)
    training_seconds = average_micro_batch * train_micro_batches
    evaluation_seconds = evaluation_per_batch * evaluation_batches
    optimizer_seconds = float(stage_two_result["optimizer_step_seconds"]) * 1947
    checkpoint_seconds = float(stage_two_result["checkpoint_seconds"]) * 7
    total_seconds = training_seconds + optimizer_seconds + evaluation_seconds + checkpoint_seconds
    epoch_seconds = total_seconds / 3
    return {
        "train_micro_batches": train_micro_batches,
        "optimizer_steps": 1947,
        "evaluation_batches": evaluation_batches,
        "average_micro_batch_seconds": average_micro_batch,
        "evaluation_batch_seconds": evaluation_per_batch,
        "training_seconds": training_seconds,
        "optimizer_seconds": optimizer_seconds,
        "evaluation_seconds": evaluation_seconds,
        "checkpoint_seconds": checkpoint_seconds,
        "epoch_seconds": epoch_seconds,
        "total_seconds": total_seconds,
        "total_hours": total_seconds / 3600,
        "acceptable": total_seconds <= 72 * 3600,
        "acceptance_limit_hours": 72,
    }


class RuntimeMonitorCallback(TrainerCallback):
    def __init__(
        self,
        *,
        repository: Path,
        expected_head: str,
        dataset_root: Path,
        metrics_path: Path,
        minimum_free_bytes: int = 10 * 1024**3,
    ) -> None:
        super().__init__()
        self.repository = repository
        self.expected_head = expected_head
        self.dataset_root = dataset_root
        self.metrics_path = metrics_path
        self.minimum_free_bytes = minimum_free_bytes
        self._zero_loss_streak = 0
        self._started = time.perf_counter()
        self._stats = {
            path.relative_to(dataset_root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in dataset_root.rglob("*")
            if path.is_file()
        }

    def _check(self, step: int) -> None:
        import torch

        if step % 10:
            return
        verify_git_identity(self.repository, expected_head=self.expected_head)
        if shutil.disk_usage(self.metrics_path.parent).free < self.minimum_free_bytes:
            raise QLoRATrainingError("TRAINING_DISK_SPACE_LOW")
        current = {
            path.relative_to(self.dataset_root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in self.dataset_root.rglob("*")
            if path.is_file()
        }
        if current != self._stats:
            raise QLoRATrainingError("TOKENIZED_DATASET_CHANGED")
        if not torch.cuda.is_available():
            raise QLoRATrainingError("GPU_DEVICE_LOST")

    def on_step_end(self, args: Any, state: Any, control: Any, **kwargs: Any) -> Any:
        del args, kwargs
        self._check(int(state.global_step))
        return control

    def on_log(self, args: Any, state: Any, control: Any, logs: Any = None, **kwargs: Any) -> Any:
        import torch

        del args, kwargs
        values = dict(logs or {})
        for key in ("loss", "eval_loss", "grad_norm"):
            if key in values and not math.isfinite(float(values[key])):
                raise QLoRATrainingError("TRAINING_METRIC_NONFINITE")
        if "loss" in values:
            self._zero_loss_streak = self._zero_loss_streak + 1 if float(values["loss"]) == 0.0 else 0
            if self._zero_loss_streak >= 3:
                raise QLoRATrainingError("TRAINING_REPEATED_ZERO_LOSS")
        values.update({
            "captured_at": utc_now(),
            "global_step": int(state.global_step),
            "gpu_allocated_bytes": torch.cuda.memory_allocated(),
            "gpu_reserved_bytes": torch.cuda.memory_reserved(),
            "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "gpu_temperature_c": gpu_temperature_celsius(),
            "elapsed_seconds": time.perf_counter() - self._started,
        })
        if int(getattr(state, "global_step", 0)) > 0 and int(getattr(state, "max_steps", 0)) > 0:
            elapsed = float(values["elapsed_seconds"])
            values["estimated_remaining_seconds"] = (
                elapsed / int(state.global_step) * (int(state.max_steps) - int(state.global_step))
            )
        with self.metrics_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(values, sort_keys=True) + "\n")
        return control


def gpu_temperature_celsius() -> int | None:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi", "--query-gpu=temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        return int(completed.stdout.strip().splitlines()[0])
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def training_arguments(
    *,
    output_dir: Path,
    config: Mapping[str, object],
    run_name: str,
) -> Any:
    from transformers import TrainingArguments

    training = config["training"]
    assert isinstance(training, Mapping)
    return TrainingArguments(
        output_dir=str(output_dir),
        overwrite_output_dir=False,
        do_train=True,
        do_eval=True,
        num_train_epochs=float(training["epochs"]),
        per_device_train_batch_size=int(training["per_device_train_batch_size"]),
        per_device_eval_batch_size=int(training["per_device_eval_batch_size"]),
        gradient_accumulation_steps=int(training["gradient_accumulation_steps"]),
        learning_rate=float(training["learning_rate"]),
        warmup_ratio=float(training["warmup_ratio"]),
        weight_decay=float(training["weight_decay"]),
        lr_scheduler_type=str(training["lr_scheduler_type"]),
        max_grad_norm=float(training["max_grad_norm"]),
        bf16=True,
        fp16=False,
        gradient_checkpointing=False,
        logging_strategy="steps",
        logging_steps=int(training["logging_steps"]),
        logging_first_step=True,
        eval_strategy=str(training["eval_strategy"]),
        eval_steps=int(training["eval_steps"]),
        save_strategy=str(training["save_strategy"]),
        save_steps=int(training["save_steps"]),
        save_total_limit=int(training["save_total_limit"]),
        save_safetensors=True,
        load_best_model_at_end=bool(training["load_best_model_at_end"]),
        seed=int(training["seed"]),
        data_seed=int(training["data_seed"]),
        optim=str(training["optimizer"]),
        remove_unused_columns=False,
        label_names=["labels"],
        prediction_loss_only=True,
        report_to=[],
        push_to_hub=False,
        run_name=run_name,
        include_tokens_per_second=True,
        include_num_input_tokens_seen=True,
        dataloader_num_workers=0,
        dataloader_pin_memory=True,
    )


def validate_checkpoint(path: str | Path) -> dict[str, object]:
    root = Path(path)
    required = ("adapter_model.safetensors", "adapter_config.json", "trainer_state.json")
    missing = [name for name in required if not (root / name).is_file()]
    forbidden = [
        item.name for item in root.iterdir()
        if item.is_file() and item.name in {"model.safetensors", "pytorch_model.bin"}
    ] if root.is_dir() else []
    if missing or forbidden:
        raise QLoRATrainingError("ADAPTER_CHECKPOINT_INVALID")
    checksums = {name: sha256_file(root / name) for name in required}
    return {
        "path": str(root),
        "checksums": checksums,
        "total_bytes": sum((root / name).stat().st_size for name in required),
        "base_model_weights_present": False,
    }


def run_inference_validation(
    *,
    config: Mapping[str, object],
    cache_dir: str | Path,
    adapter_root: str | Path,
    validation_dataset: Any,
) -> dict[str, object]:
    import torch
    from peft import PeftModel

    tokenizer, base = load_tokenizer_and_model(config, cache_dir=cache_dir)
    model = PeftModel.from_pretrained(base, adapter_root, is_trainable=False)
    model.eval()
    collator = DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
    with torch.no_grad():
        validation_loss = model(**move_batch(collator([validation_dataset[0]]))).loss
    if validation_loss is None or not torch.isfinite(validation_loss):
        raise QLoRATrainingError("FINAL_ADAPTER_RELOAD_FAILED")
    prompts = (
        "한국의 사계절을 간단히 설명해 주세요.",
        "안전한 비밀번호를 만드는 원칙을 알려 주세요.",
        "서울과 부산의 일반적인 교통수단을 비교해 주세요.",
        "초보자를 위한 파이썬 학습 순서를 제안해 주세요.",
        "재활용이 환경에 도움이 되는 이유를 설명해 주세요.",
    )
    non_empty = 0
    korean = 0
    special_errors = 0
    repetition_failures = 0
    prompt_echo_failures = 0
    eos_terminated = 0
    for prompt in prompts:
        messages = [{"role": "user", "content": prompt}]
        ids = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_tensors="pt",
        ).to("cuda:0")
        with torch.no_grad():
            generated = model.generate(
                ids,
                do_sample=False,
                max_new_tokens=256,
                repetition_penalty=1.05,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        new_ids = generated[0, ids.shape[1]:].tolist()
        decoded = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
        raw_decoded = tokenizer.decode(new_ids, skip_special_tokens=False)
        non_empty += int(bool(decoded))
        korean += int(any("가" <= char <= "힣" for char in decoded))
        raw_body = raw_decoded.removesuffix(tokenizer.eos_token or "")
        special_errors += int(
            any(token in raw_body for token in tokenizer.additional_special_tokens)
        )
        repetition_failures += int(len(new_ids) >= 32 and len(set(new_ids[-32:])) <= 2)
        prompt_echo_failures += int(prompt in decoded)
        eos_terminated += int(bool(new_ids) and new_ids[-1] == tokenizer.eos_token_id)
    result = {
        "samples": len(prompts),
        "non_empty_outputs": non_empty,
        "korean_decode_pass": korean,
        "special_token_errors": special_errors,
        "repetition_failures": repetition_failures,
        "prompt_echo_failures": prompt_echo_failures,
        "eos_terminated": eos_terminated,
        "validation_loss": float(validation_loss.item()),
        "raw_text_logged": False,
    }
    if (
        non_empty != len(prompts)
        or korean != len(prompts)
        or special_errors
        or repetition_failures
        or prompt_echo_failures
    ):
        raise QLoRATrainingError("INFERENCE_SMOKE_FAILED")
    del model, base, validation_loss
    release_cuda()
    return result


def validate_adapter_reload(
    *,
    config: Mapping[str, object],
    cache_dir: str | Path,
    adapter_root: str | Path,
    validation_record: Mapping[str, Sequence[int]],
) -> dict[str, object]:
    import torch
    from peft import PeftModel

    tokenizer, base = load_tokenizer_and_model(config, cache_dir=cache_dir)
    model = PeftModel.from_pretrained(base, adapter_root, is_trainable=False)
    model.eval()
    collator = DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
    with torch.no_grad():
        batch = move_batch(collator([validation_record]))
        loss = model(**batch).loss
    if loss is None or not torch.isfinite(loss):
        raise QLoRATrainingError("ADAPTER_CHECKPOINT_RELOAD_FAILED")
    result = {"reload_validated": True, "validation_loss": float(loss.item())}
    del model, base, loss, batch
    release_cuda()
    return result


def run_full_training(
    *,
    paths: ArtifactPaths,
    config: Mapping[str, object],
    config_path: str | Path,
    cache_dir: str | Path,
    tokenized_root: str | Path,
    repository: str | Path,
    expected_head: str,
    environment: Mapping[str, object],
    git_identity: Mapping[str, object],
    run_id: str = RUN_ID,
    reporter: StageReporter | None = None,
) -> dict[str, object]:
    import torch
    from datasets import load_from_disk
    from transformers import Trainer

    tracker = reporter or StageReporter()

    class HeartbeatTrainer(Trainer):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.micro_batch_index = 0

        def training_step(
            self,
            model: Any,
            inputs: dict[str, Any],
            num_items_in_batch: Any = None,
        ) -> Any:
            self.micro_batch_index += 1
            attention_mask = inputs.get("attention_mask")
            sequence_length = int(attention_mask.sum().item()) if attention_mask is not None else -1
            with tracker.stage(
                "full_training_micro_batch",
                timeout_seconds=STAGE_TIMEOUTS["full_training_micro_batch"],
                global_step=int(self.state.global_step),
                micro_batch=self.micro_batch_index,
                sequence_length=sequence_length,
            ):
                loss = super().training_step(model, inputs, num_items_in_batch)
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                return loss

    paths.staging.mkdir(parents=True)
    started = time.perf_counter()
    started_at = utc_now()
    try:
        tokenizer, base_model = load_tokenizer_and_model(config, cache_dir=cache_dir)
        model = attach_lora(base_model, config)
        statistics_value = model_statistics(model, tokenizer)
        train = load_from_disk(Path(tokenized_root) / "train")
        validation = load_from_disk(Path(tokenized_root) / "validation")
        arguments = training_arguments(
            output_dir=paths.staging,
            config=config,
            run_name=run_id,
        )
        collator = DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
        metrics_path = paths.staging / "metrics.jsonl"
        monitor = RuntimeMonitorCallback(
            repository=Path(repository),
            expected_head=expected_head,
            dataset_root=Path(tokenized_root),
            metrics_path=metrics_path,
        )
        trainer = HeartbeatTrainer(
            model=model,
            args=arguments,
            train_dataset=train,
            eval_dataset=validation,
            data_collator=collator,
            callbacks=[monitor],
        )
        expected_steps = math.ceil(len(train) / 16) * 3
        if expected_steps != 1947:
            raise QLoRATrainingError("OPTIMIZER_STEP_BUDGET_MISMATCH")
        torch.cuda.reset_peak_memory_stats()
        train_output = trainer.train(resume_from_checkpoint=None)
        if int(trainer.state.global_step) != expected_steps:
            raise QLoRATrainingError("OPTIMIZER_STEP_COUNT_MISMATCH")
        eval_metrics = trainer.evaluate()
        eval_losses = [
            float(entry["eval_loss"])
            for entry in trainer.state.log_history
            if isinstance(entry.get("eval_loss"), (int, float))
        ]
        train_losses = [
            float(entry["loss"])
            for entry in trainer.state.log_history
            if isinstance(entry.get("loss"), (int, float))
        ]
        best_checkpoint = trainer.state.best_model_checkpoint
        final_adapter = paths.staging / "final-adapter"
        model.save_pretrained(final_adapter, safe_serialization=True)
        trainer.state.save_to_json(str(final_adapter / "trainer_state.json"))
        shutil.copy2(config_path, final_adapter / "training-config.yaml")
        _write_json(final_adapter / "environment.json", dict(environment))
        _write_json(
            final_adapter / "tokenizer-reference.json",
            {"model_id": MODEL_ID, "revision": MODEL_REVISION, "fingerprint": TOKENIZER_FINGERPRINT},
        )
        checkpoint_roots = sorted(
            (path for path in paths.staging.glob("checkpoint-*") if path.is_dir()),
            key=lambda path: int(path.name.split("-")[-1]),
        )
        checkpoint_results = [validate_checkpoint(path) for path in checkpoint_roots]
        for checkpoint_result, checkpoint_root in zip(
            checkpoint_results, checkpoint_roots, strict=True,
        ):
            checkpoint_result["path"] = checkpoint_root.name
        final_checkpoint = validate_checkpoint(final_adapter)
        final_checkpoint["path"] = "final-adapter"
        peak = torch.cuda.max_memory_allocated()
        runtime = time.perf_counter() - started
        del trainer, model, base_model
        release_cuda()
        for checkpoint_result, checkpoint_root in zip(
            checkpoint_results, checkpoint_roots, strict=True,
        ):
            checkpoint_result.update(validate_adapter_reload(
                config=config,
                cache_dir=cache_dir,
                adapter_root=checkpoint_root,
                validation_record=validation[0],
            ))
        inference = run_inference_validation(
            config=config,
            cache_dir=cache_dir,
            adapter_root=final_adapter,
            validation_dataset=validation,
        )
        final_checkpoint.update({
            "reload_validated": True,
            "validation_loss": inference["validation_loss"],
        })
        adapter_identity = {
            "adapter_model.safetensors": sha256_file(final_adapter / "adapter_model.safetensors"),
            "adapter_config.json": sha256_file(final_adapter / "adapter_config.json"),
        }
        adapter_fingerprint = canonical_fingerprint(adapter_identity)
        result: dict[str, object] = {
            "status": "completed",
            "run_id": run_id,
            "started_at": started_at,
            "ended_at": utc_now(),
            "git": dict(git_identity),
            "base_model": MODEL_ID,
            "base_revision": MODEL_REVISION,
            "dataset_fingerprint": DATASET_FINGERPRINT,
            "tokenizer_fingerprint": TOKENIZER_FINGERPRINT,
            "source_processing_run": SOURCE_PROCESSING_RUN,
            "tokenization_run": TOKENIZATION_RUN,
            "training_config_fingerprint": sha256_file(config_path),
            "model_statistics": statistics_value.__dict__,
            "train_rows": len(train),
            "validation_rows": len(validation),
            "total_tokens": sum(EXPECTED_TOKENS.values()),
            "train_tokens": EXPECTED_TOKENS["train"],
            "validation_tokens": EXPECTED_TOKENS["validation"],
            "scheduled_training_tokens": EXPECTED_TOKENS["train"] * 3,
            "epochs_completed": float(trainer_state_epoch(train_output.metrics, default=3.0)),
            "optimizer_steps": expected_steps,
            "train_runtime_seconds": runtime,
            "train_metrics": dict(train_output.metrics),
            "eval_metrics": dict(eval_metrics),
            "final_train_loss": train_losses[-1] if train_losses else None,
            "best_eval_loss": min(eval_losses) if eval_losses else None,
            "best_checkpoint": best_checkpoint,
            "peak_allocated_bytes": peak,
            "checkpoints": checkpoint_results,
            "retained_checkpoints": len(checkpoint_results),
            "final_adapter": final_checkpoint,
            "adapter_fingerprint": adapter_fingerprint,
            "adapter_merged": False,
            "inference_smoke": inference,
            "source_dataset_modified": False,
            "tokenization_modified": False,
        }
        _write_yaml(final_adapter / "training-result.yaml", result)
        final_checksums = write_checksums(final_adapter)
        result["final_checksums"] = final_checksums
        result["final_checksums_sha256"] = sha256_file(final_adapter / "checksums.sha256")
        _write_yaml(paths.staging / "training-result.yaml", result)
        _write_json(paths.staging / "environment.json", dict(environment))
        write_checksums(paths.staging)
        publish_staging(paths)
        return result
    except Exception:
        quarantine_staging(paths)
        raise


def trainer_state_epoch(metrics: Mapping[str, object], *, default: float) -> float:
    value = metrics.get("epoch", default)
    return float(value) if isinstance(value, (int, float)) else default
