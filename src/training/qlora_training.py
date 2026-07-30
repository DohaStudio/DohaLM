"""Fail-closed QLoRA smoke and training helpers for DohaLM v0.1."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import random
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
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
SMOKE_RUN_ID = "DOHALM-V0.1-QLORA-SMOKE-20260730-0001"
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


def publish_staging(paths: ArtifactPaths) -> None:
    if not paths.staging.is_dir() or paths.final.exists():
        raise QLoRATrainingError("OUTPUT_ATOMIC_PUBLISH_INVALID")
    os.replace(paths.staging, paths.final)


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
        use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
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
    return model


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


def run_allocation_smoke(
    *,
    model: Any,
    tokenizer: Any,
    train_dataset: Any,
    config: Mapping[str, object],
) -> dict[str, object]:
    import torch

    training = config["training"]
    assert isinstance(training, Mapping)
    collator = DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
    batch = move_batch(collator([longest_record(train_dataset)]))
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    forward_started = time.perf_counter()
    outputs = model(**batch)
    forward_seconds = time.perf_counter() - forward_started
    loss = outputs.loss
    if loss is None or not torch.isfinite(loss):
        raise QLoRATrainingError("ALLOCATION_LOSS_NONFINITE")
    backward_started = time.perf_counter()
    loss.backward()
    backward_seconds = time.perf_counter() - backward_started
    gradients_finite, gradient_norm = finite_gradients(model)
    if not gradients_finite:
        raise QLoRATrainingError("ALLOCATION_GRADIENT_NONFINITE")
    optimizer = create_optimizer(
        model,
        learning_rate=float(training["learning_rate"]),
        weight_decay=float(training["weight_decay"]),
    )
    result = {
        "status": "passed",
        "sequence_length": int(batch["input_ids"].shape[1]),
        "loss": float(loss.detach().item()),
        "gradient_norm": gradient_norm,
        "forward_seconds": forward_seconds,
        "backward_seconds": backward_seconds,
        "duration_seconds": time.perf_counter() - started,
        "allocated_bytes": torch.cuda.memory_allocated(),
        "reserved_bytes": torch.cuda.memory_reserved(),
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        "optimizer_created": type(optimizer).__name__,
        "optimizer_steps": 0,
    }
    optimizer.zero_grad(set_to_none=True)
    del optimizer, outputs, loss, batch
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
) -> dict[str, object]:
    import torch
    from datasets import load_from_disk
    from peft import PeftModel
    from transformers import get_cosine_schedule_with_warmup

    paths.staging.mkdir(parents=True)
    checkpoint = paths.staging / "checkpoint-1"
    try:
        tokenizer, base_model = load_tokenizer_and_model(config, cache_dir=cache_dir)
        model = attach_lora(base_model, config)
        train = load_from_disk(Path(tokenized_root) / "train")
        validation = load_from_disk(Path(tokenized_root) / "validation")
        generator = random.Random(42)
        train_indices = generator.sample(range(len(train)), 16)
        validation_indices = list(range(4))
        collator = DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
        training = config["training"]
        assert isinstance(training, Mapping)
        optimizer = create_optimizer(
            model,
            learning_rate=float(training["learning_rate"]),
            weight_decay=float(training["weight_decay"]),
        )
        scheduler = get_cosine_schedule_with_warmup(
            optimizer, num_warmup_steps=0, num_training_steps=1,
        )
        torch.cuda.reset_peak_memory_stats()
        started = time.perf_counter()
        losses = []
        optimizer.zero_grad(set_to_none=True)
        for index in train_indices:
            batch = move_batch(collator([train[index]]))
            outputs = model(**batch)
            loss = outputs.loss
            if loss is None or not torch.isfinite(loss):
                raise QLoRATrainingError("TRAINING_SMOKE_LOSS_NONFINITE")
            losses.append(float(loss.detach().item()))
            (loss / 16).backward()
            del outputs, loss, batch
        gradients_finite, gradient_norm = finite_gradients(model)
        if not gradients_finite:
            raise QLoRATrainingError("TRAINING_SMOKE_GRADIENT_NONFINITE")
        torch.nn.utils.clip_grad_norm_(
            [parameter for parameter in model.parameters() if parameter.requires_grad],
            float(training["max_grad_norm"]),
        )
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad(set_to_none=True)
        model.save_pretrained(checkpoint, safe_serialization=True)
        trainer_state = {
            "global_step": 1,
            "micro_batches": 16,
            "gradient_accumulation_steps": 16,
            "scheduler_steps": 1,
            "gradient_norm": gradient_norm,
        }
        _write_json(checkpoint / "trainer_state.json", trainer_state)
        checkpoint_result = validate_checkpoint(checkpoint)
        checkpoint_result["path"] = "checkpoint-1"
        model.eval()
        eval_losses = []
        with torch.no_grad():
            for index in validation_indices:
                batch = move_batch(collator([validation[index]]))
                loss = model(**batch).loss
                if loss is None or not torch.isfinite(loss):
                    raise QLoRATrainingError("TRAINING_SMOKE_EVAL_NONFINITE")
                eval_losses.append(float(loss.item()))
                del loss, batch
        peak = torch.cuda.max_memory_allocated()
        del optimizer, scheduler, model, base_model
        release_cuda()
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
            "run_id": SMOKE_RUN_ID,
            "created_at": utc_now(),
            "allocation_smoke": dict(allocation_result),
            "micro_batches": 16,
            "optimizer_steps": 1,
            "scheduler_steps": 1,
            "train_loss_mean": sum(losses) / len(losses),
            "train_loss_final": losses[-1],
            "eval_batches": 4,
            "eval_loss": sum(eval_losses) / len(eval_losses),
            "gradient_norm": gradient_norm,
            "peak_allocated_bytes": peak,
            "duration_seconds": time.perf_counter() - started,
            "checkpoint": "checkpoint-1",
            "checkpoint_validation": checkpoint_result,
            "checkpoint_reload": True,
            "model_statistics": dict(model_statistics_value),
            "git": dict(git_identity),
            "dataset_fingerprint": DATASET_FINGERPRINT,
            "tokenizer_fingerprint": TOKENIZER_FINGERPRINT,
            "source_processing_run": SOURCE_PROCESSING_RUN,
            "tokenization_run": TOKENIZATION_RUN,
        }
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


def smoke_is_valid(smoke_root: str | Path, *, expected_head: str) -> dict[str, object]:
    root = Path(smoke_root)
    try:
        result = yaml.safe_load((root / "smoke-result.yaml").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise QLoRATrainingError("SMOKE_RESULT_REQUIRED") from None
    if not isinstance(result, Mapping):
        raise QLoRATrainingError("SMOKE_RESULT_REQUIRED")
    expected = _parse_checksum_file(root)
    actual = file_checksums(root)
    if expected != actual:
        raise QLoRATrainingError("SMOKE_CHECKSUM_MISMATCH")
    allocation = result.get("allocation_smoke")
    git = result.get("git")
    if (
        result.get("status") != "passed"
        or result.get("optimizer_steps") != 1
        or result.get("checkpoint_reload") is not True
        or not isinstance(allocation, Mapping)
        or allocation.get("status") != "passed"
        or int(allocation.get("peak_allocated_bytes", 9 * 1024**3)) >= 8 * 1024**3
        or int(result.get("peak_allocated_bytes", 9 * 1024**3)) >= 8 * 1024**3
        or not isinstance(git, Mapping)
        or git.get("head") != expected_head
    ):
        raise QLoRATrainingError("SMOKE_READINESS_FAILED")
    return dict(result)


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
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
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
) -> dict[str, object]:
    import torch
    from datasets import load_from_disk
    from transformers import Trainer

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
            run_name=RUN_ID,
        )
        collator = DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
        metrics_path = paths.staging / "metrics.jsonl"
        monitor = RuntimeMonitorCallback(
            repository=Path(repository),
            expected_head=expected_head,
            dataset_root=Path(tokenized_root),
            metrics_path=metrics_path,
        )
        trainer = Trainer(
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
            "run_id": RUN_ID,
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
