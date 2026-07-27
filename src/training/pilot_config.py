"""Validated configuration for bounded local pilot pretraining."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml

from src.model import ModelConfig

from .config import TrainingConfig
from .errors import TrainingError


@dataclass(frozen=True)
class PilotPretrainingConfig:
    train_dataset: str
    validation_dataset: str
    tokenizer_model: str
    corpus_manifest: str
    split_manifest: str
    path_root: str = "repository"
    local_dataset_config: str = "configs/local-datasets.yaml"
    output_dir: str = "experiments/pilot-pretraining"
    micro_batch_size: int = 2
    gradient_accumulation_steps: int = 4
    max_steps: int = 100
    log_every: int = 1
    validation_every: int = 10
    save_every: int = 25
    learning_rate: float = 3e-4
    weight_decay: float = 0.1
    warmup_steps: int = 10
    min_lr_ratio: float = 0.1
    scheduler_type: str = "cosine"
    max_grad_norm: float = 1.0
    seed: int = 17
    device: str = "cuda"
    use_amp: bool = True
    num_workers: int = 0
    pin_memory: bool = True
    local_experiment_only: bool = True
    publish_allowed: bool = False
    redistribution_allowed: bool = False
    model_release_allowed: bool = False
    prompt: str = "한국어"
    max_new_tokens: int = 16
    validation_max_batches: int | None = None
    resume_checkpoint: str | None = None
    pilot_readiness: dict[str, Any] = field(default_factory=dict)
    model: ModelConfig = field(default_factory=ModelConfig)

    def __post_init__(self) -> None:
        for name in ("train_dataset", "validation_dataset", "tokenizer_model", "corpus_manifest", "split_manifest", "local_dataset_config", "output_dir"):
            self._validate_relative_path(name, getattr(self, name))
        if self.path_root not in ("repository", "configured_external"):
            raise TrainingError("INVALID_PILOT_CONFIG", "path_root는 repository 또는 configured_external이어야 합니다.")
        if self.resume_checkpoint is not None:
            self._validate_relative_path("resume_checkpoint", self.resume_checkpoint)
        if not self.local_experiment_only or self.publish_allowed or self.redistribution_allowed or self.model_release_allowed:
            raise TrainingError("PILOT_LOCAL_ONLY_VIOLATION", "pilot은 local-only이며 공개·재배포·모델 배포를 허용하지 않습니다.")
        integer_fields = ("micro_batch_size", "gradient_accumulation_steps", "max_steps", "log_every", "validation_every", "save_every", "max_new_tokens")
        if any(isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), int) or getattr(self, name) <= 0 for name in integer_fields):
            raise TrainingError("INVALID_PILOT_CONFIG", "batch·step·generation 값은 양의 정수여야 합니다.")
        if self.max_steps > 100:
            raise TrainingError("PILOT_STEP_LIMIT", "pilot max_steps는 100을 초과할 수 없습니다.")
        if self.validation_every > self.max_steps or self.save_every > self.max_steps:
            raise TrainingError("INVALID_PILOT_CONFIG", "validation/save 주기는 max_steps 이하여야 합니다.")
        if not self.prompt.strip():
            raise TrainingError("INVALID_PILOT_CONFIG", "generation prompt가 비어 있습니다.")
        if self.scheduler_type != "cosine":
            raise TrainingError("INVALID_PILOT_CONFIG", "현재 pilot scheduler 후보는 cosine만 지원합니다.")
        if not isinstance(self.pilot_readiness, dict):
            raise TrainingError("INVALID_PILOT_CONFIG", "pilot_readiness는 mapping이어야 합니다.")
        if self.validation_max_batches is not None and (isinstance(self.validation_max_batches, bool) or self.validation_max_batches <= 0):
            raise TrainingError("INVALID_PILOT_CONFIG", "validation_max_batches는 양의 정수여야 합니다.")

    @staticmethod
    def _validate_relative_path(name: str, value: str) -> None:
        raw = value.replace("\\", "/")
        if not raw or PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute() or ".." in PurePosixPath(raw).parts:
            raise TrainingError("INVALID_PILOT_CONFIG", f"{name}은 저장소 내부 상대경로여야 합니다.")

    @property
    def effective_batch_size(self) -> int:
        return self.micro_batch_size * self.gradient_accumulation_steps

    def to_training_config(self) -> TrainingConfig:
        training_output = self.output_dir if self.path_root == "repository" else "artifacts/pilot-pretraining-external"
        return TrainingConfig(
            batch_size=self.effective_batch_size,
            micro_batch_size=self.micro_batch_size,
            gradient_accumulation_steps=self.gradient_accumulation_steps,
            max_steps=self.max_steps,
            learning_rate=self.learning_rate,
            weight_decay=self.weight_decay,
            warmup_steps=self.warmup_steps,
            scheduler_type=self.scheduler_type,
            min_lr_ratio=self.min_lr_ratio,
            max_grad_norm=self.max_grad_norm,
            use_amp=self.use_amp,
            seed=self.seed,
            log_every=self.log_every,
            save_every=self.save_every,
            output_dir=training_output,
            device=self.device,
            num_workers=self.num_workers,
            pin_memory=self.pin_memory,
        )

    def smoke(self) -> "PilotPretrainingConfig":
        steps = min(5, self.max_steps)
        return replace(self, max_steps=steps, validation_every=min(self.validation_every, steps), save_every=min(self.save_every, steps))

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["effective_batch_size"] = self.effective_batch_size
        return value

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PilotPretrainingConfig":
        try:
            value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise TrainingError("INVALID_PILOT_CONFIG", "pilot config를 읽을 수 없습니다.") from exc
        if not isinstance(value, dict):
            raise TrainingError("INVALID_PILOT_CONFIG", "pilot config root는 mapping이어야 합니다.")
        allowed = set(cls.__dataclass_fields__)
        unknown = set(value) - allowed
        if unknown:
            raise TrainingError("INVALID_PILOT_CONFIG", f"알 수 없는 pilot config field: {sorted(unknown)}")
        model_value = value.get("model", {})
        if not isinstance(model_value, dict):
            raise TrainingError("INVALID_PILOT_CONFIG", "model config는 mapping이어야 합니다.")
        value["model"] = ModelConfig(**model_value)
        return cls(**value)
