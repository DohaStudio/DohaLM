"""Offline-only loader for the fixed Base Qwen deployment candidate."""

from __future__ import annotations

import gc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASE_QWEN_MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"
BASE_QWEN_REVISION = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
BASE_QWEN_EOS_TOKEN_ID = 151645
BASE_QWEN_PAD_TOKEN_ID = 151643
_REQUIRED_SNAPSHOT_FILES = (
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
)


class ModelLoadError(RuntimeError):
    """A sanitized, fail-closed model loading failure."""


@dataclass(frozen=True)
class BaseQwenConfig:
    model_id: str = BASE_QWEN_MODEL_ID
    revision: str = BASE_QWEN_REVISION
    snapshot: Path | None = None
    quantization: str = "nf4"
    device: str = "cuda:0"
    max_concurrent_generations: int = 1
    load_timeout_seconds: float = 300
    generation_timeout_seconds: float = 120
    unload_on_shutdown: bool = True
    minimum_free_vram_mib: int = 5500

    def __post_init__(self) -> None:
        if self.model_id != BASE_QWEN_MODEL_ID:
            raise ValueError("BASE_MODEL_ID_NOT_APPROVED")
        if self.revision != BASE_QWEN_REVISION:
            raise ValueError("BASE_MODEL_REVISION_NOT_APPROVED")
        if self.quantization.lower() not in {"nf4", "bf16"}:
            raise ValueError("BASE_MODEL_QUANTIZATION_INVALID")
        if self.device != "cuda:0":
            raise ValueError("BASE_MODEL_DEVICE_NOT_APPROVED")
        if self.max_concurrent_generations < 1:
            raise ValueError("BASE_MODEL_CONCURRENCY_INVALID")
        if self.load_timeout_seconds <= 0 or self.generation_timeout_seconds <= 0:
            raise ValueError("BASE_MODEL_TIMEOUT_INVALID")
        if self.minimum_free_vram_mib < 1:
            raise ValueError("BASE_MODEL_VRAM_FLOOR_INVALID")


@dataclass
class LoadedBaseQwen:
    tokenizer: Any
    model: Any
    torch: Any
    allocated_vram_bytes: int


def _resolve_snapshot(config: BaseQwenConfig) -> Path:
    if config.snapshot is not None:
        snapshot = config.snapshot.expanduser().resolve(strict=False)
    else:
        try:
            from huggingface_hub import snapshot_download

            snapshot = Path(
                snapshot_download(
                    repo_id=config.model_id,
                    revision=config.revision,
                    local_files_only=True,
                )
            )
        except Exception as exc:
            raise ModelLoadError("LOCAL_SNAPSHOT_NOT_AVAILABLE") from exc
    if snapshot.name != config.revision:
        raise ModelLoadError("SNAPSHOT_REVISION_MISMATCH")
    if not snapshot.is_dir() or any(
        not (snapshot / name).is_file() for name in _REQUIRED_SNAPSHOT_FILES
    ):
        raise ModelLoadError("LOCAL_SNAPSHOT_INCOMPLETE")
    return snapshot


def load_base_qwen(config: BaseQwenConfig) -> LoadedBaseQwen:
    """Load one immutable local snapshot without remote-code or network fallback."""
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    except Exception as exc:
        raise ModelLoadError("INFERENCE_DEPENDENCY_UNAVAILABLE") from exc

    if (
        not torch.cuda.is_available()
        or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3060 Ti"
    ):
        raise ModelLoadError("APPROVED_GPU_NOT_AVAILABLE")
    free_bytes, _ = torch.cuda.mem_get_info(0)
    if free_bytes < config.minimum_free_vram_mib * 1024 * 1024:
        raise ModelLoadError("INSUFFICIENT_FREE_VRAM")
    snapshot = _resolve_snapshot(config)
    common: dict[str, Any] = {
        "local_files_only": True,
        "trust_remote_code": False,
        "revision": config.revision,
    }
    tokenizer = AutoTokenizer.from_pretrained(snapshot, use_fast=True, **common)
    if (
        tokenizer.eos_token_id != BASE_QWEN_EOS_TOKEN_ID
        or tokenizer.pad_token_id != BASE_QWEN_PAD_TOKEN_ID
    ):
        raise ModelLoadError("TOKENIZER_SPECIAL_TOKEN_MISMATCH")

    model_options: dict[str, Any] = {
        **common,
        "device_map": {"": 0},
        "dtype": torch.bfloat16,
        "low_cpu_mem_usage": True,
    }
    if config.quantization.lower() == "nf4":
        model_options["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
    torch.cuda.reset_peak_memory_stats(0)
    try:
        model = AutoModelForCausalLM.from_pretrained(snapshot, **model_options)
    except Exception as exc:
        raise ModelLoadError("LOCAL_MODEL_LOAD_FAILED") from exc
    model.eval()
    model.config.use_cache = True
    model.generation_config.do_sample = False
    model.generation_config.temperature = None
    model.generation_config.top_p = None
    model.generation_config.top_k = None

    device_values = {
        str(value) for value in getattr(model, "hf_device_map", {}).values()
    }
    parameter_devices = {parameter.device.type for parameter in model.parameters()}
    if "cpu" in parameter_devices or "meta" in parameter_devices:
        raise ModelLoadError("UNEXPECTED_MODEL_OFFLOAD")
    if any(value in {"cpu", "disk"} for value in device_values):
        raise ModelLoadError("UNEXPECTED_MODEL_OFFLOAD")
    return LoadedBaseQwen(
        tokenizer=tokenizer,
        model=model,
        torch=torch,
        allocated_vram_bytes=int(torch.cuda.memory_allocated(0)),
    )


def unload_base_qwen(loaded: LoadedBaseQwen) -> None:
    loaded.model = None
    loaded.tokenizer = None
    gc.collect()
    release_cuda_cache(loaded)


def release_cuda_cache(loaded: LoadedBaseQwen) -> None:
    """Release the process cache from the caller's CUDA thread."""
    if loaded.torch.cuda.is_available():
        synchronize = getattr(loaded.torch.cuda, "synchronize", None)
        if synchronize is not None:
            synchronize(0)
        clear_cublas = getattr(
            getattr(loaded.torch, "_C", None), "_cuda_clearCublasWorkspaces", None
        )
        if clear_cublas is not None:
            clear_cublas()
        gc.collect()
        loaded.torch.cuda.empty_cache()
        loaded.torch.cuda.ipc_collect()
        if synchronize is not None:
            synchronize(0)
        gc.collect()
        loaded.torch.cuda.empty_cache()
