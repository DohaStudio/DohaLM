"""Validated configuration for the synthetic Trainer Foundation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

import torch

from src.data.checksums import checksum_value

from .errors import TrainingError


_IGNORED_OUTPUT_ROOTS = {"artifacts", "checkpoints", "experiments", "logs"}


@dataclass(frozen=True)
class TrainingConfig:
    batch_size: int = 2
    micro_batch_size: int = 2
    gradient_accumulation_steps: int = 1
    max_steps: int = 10
    learning_rate: float = 1e-3
    weight_decay: float = 0.01
    betas: tuple[float, float] = (0.9, 0.95)
    epsilon: float = 1e-8
    warmup_steps: int = 0
    scheduler_type: str = "linear"
    min_lr_ratio: float = 0.0
    max_grad_norm: float = 1.0
    use_amp: bool = False
    amp_dtype: str = "float16"
    seed: int = 17
    log_every: int = 1
    save_every: int = 5
    output_dir: str = "tests/output/training-smoke"
    device: str = "cpu"
    num_workers: int = 0
    pin_memory: bool = False
    drop_last: bool = False

    def __post_init__(self) -> None:
        positive = {
            "batch_size": self.batch_size,
            "micro_batch_size": self.micro_batch_size,
            "gradient_accumulation_steps": self.gradient_accumulation_steps,
            "max_steps": self.max_steps,
            "log_every": self.log_every,
            "save_every": self.save_every,
        }
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in positive.values()):
            raise TrainingError("INVALID_TRAINING_CONFIG", "batch, step, log와 save 값은 양의 정수여야 합니다.")
        if self.batch_size != self.micro_batch_size * self.gradient_accumulation_steps:
            raise TrainingError(
                "INVALID_TRAINING_CONFIG",
                "batch_size는 micro_batch_size × gradient_accumulation_steps와 같아야 합니다.",
            )
        if not isinstance(self.learning_rate, (int, float)) or isinstance(self.learning_rate, bool) or self.learning_rate <= 0:
            raise TrainingError("INVALID_TRAINING_CONFIG", "learning_rate는 양수여야 합니다.")
        if not isinstance(self.weight_decay, (int, float)) or isinstance(self.weight_decay, bool) or self.weight_decay < 0:
            raise TrainingError("INVALID_TRAINING_CONFIG", "weight_decay는 0 이상이어야 합니다.")
        if (
            not isinstance(self.betas, tuple)
            or len(self.betas) != 2
            or any(not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value < 1 for value in self.betas)
        ):
            raise TrainingError("INVALID_TRAINING_CONFIG", "betas는 0 이상 1 미만의 두 값이어야 합니다.")
        if not isinstance(self.epsilon, (int, float)) or isinstance(self.epsilon, bool) or self.epsilon <= 0:
            raise TrainingError("INVALID_TRAINING_CONFIG", "epsilon은 양수여야 합니다.")
        if isinstance(self.warmup_steps, bool) or not isinstance(self.warmup_steps, int) or not 0 <= self.warmup_steps <= self.max_steps:
            raise TrainingError("INVALID_TRAINING_CONFIG", "warmup_steps는 0 이상 max_steps 이하여야 합니다.")
        if self.scheduler_type not in {"linear", "cosine"}:
            raise TrainingError("INVALID_TRAINING_CONFIG", "scheduler_type은 linear 또는 cosine이어야 합니다.")
        if (
            isinstance(self.min_lr_ratio, bool)
            or not isinstance(self.min_lr_ratio, (int, float))
            or not 0.0 <= self.min_lr_ratio <= 1.0
        ):
            raise TrainingError("INVALID_TRAINING_CONFIG", "min_lr_ratio는 0 이상 1 이하여야 합니다.")
        if self.scheduler_type == "linear" and self.min_lr_ratio != 0.0:
            raise TrainingError("INVALID_TRAINING_CONFIG", "linear scheduler의 min_lr_ratio는 0이어야 합니다.")
        if not isinstance(self.max_grad_norm, (int, float)) or isinstance(self.max_grad_norm, bool) or self.max_grad_norm <= 0:
            raise TrainingError("INVALID_TRAINING_CONFIG", "max_grad_norm은 양수여야 합니다.")
        if self.amp_dtype != "float16":
            raise TrainingError("INVALID_TRAINING_CONFIG", "Trainer Foundation AMP는 float16만 지원합니다.")
        if self.device not in {"cpu", "cuda"}:
            raise TrainingError("INVALID_TRAINING_CONFIG", "device는 cpu 또는 cuda여야 합니다.")
        if self.use_amp and (self.device != "cuda" or not torch.cuda.is_available()):
            raise TrainingError("AMP_NOT_AVAILABLE", "FP16 AMP는 사용 가능한 CUDA device에서만 지원합니다.")
        if self.device == "cuda" and not torch.cuda.is_available():
            raise TrainingError("INVALID_TRAINING_CONFIG", "CUDA를 사용할 수 없습니다.")
        if isinstance(self.num_workers, bool) or not isinstance(self.num_workers, int) or self.num_workers < 0:
            raise TrainingError("INVALID_TRAINING_CONFIG", "num_workers는 0 이상의 정수여야 합니다.")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise TrainingError("INVALID_TRAINING_CONFIG", "seed는 0 이상의 정수여야 합니다.")
        if not isinstance(self.pin_memory, bool) or not isinstance(self.drop_last, bool) or not isinstance(self.use_amp, bool):
            raise TrainingError("INVALID_TRAINING_CONFIG", "boolean 설정의 형식이 올바르지 않습니다.")
        self._validate_output_dir()

    def _validate_output_dir(self) -> None:
        raw = self.output_dir.replace("\\", "/")
        if not raw or PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute():
            raise TrainingError("INVALID_TRAINING_CONFIG", "output_dir은 저장소 상대경로여야 합니다.")
        parts = PurePosixPath(raw).parts
        if ".." in parts or not parts:
            raise TrainingError("INVALID_TRAINING_CONFIG", "output_dir은 저장소 밖으로 이동할 수 없습니다.")
        allowed = parts[0] in _IGNORED_OUTPUT_ROOTS or parts[:2] in {("tests", "output"), ("tests", "tmp")}
        if not allowed:
            raise TrainingError("INVALID_TRAINING_CONFIG", "output_dir은 Git 제외 산출물 경로여야 합니다.")

    @property
    def effective_batch_size(self) -> int:
        return self.micro_batch_size * self.gradient_accumulation_steps

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["betas"] = list(self.betas)
        value["effective_batch_size"] = self.effective_batch_size
        return value

    def fingerprint(self) -> str:
        return checksum_value(self.to_dict())

    def resume_fields(self) -> dict[str, Any]:
        ignored = {"log_every", "save_every", "output_dir", "num_workers", "pin_memory"}
        return {key: value for key, value in self.to_dict().items() if key not in ignored}

    def resume_fingerprint(self) -> str:
        return checksum_value(self.resume_fields())
