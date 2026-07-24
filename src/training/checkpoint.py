"""Atomic checkpoint publication, integrity validation, and resume."""

from __future__ import annotations

import base64
import json
import os
import random
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch import nn

from src.data.checksums import canonical_json_bytes, checksum_value, file_checksum
from src.model import ModelConfig

from .config import TrainingConfig
from .errors import TrainingError
from .scheduler import LinearWarmupDecayScheduler
from .state import TrainingState


CHECKPOINT_FORMAT_VERSION = "1.0"
CONTENT_FILES = (
    "model.pt",
    "optimizer.pt",
    "scheduler.pt",
    "scaler.pt",
    "training-state.json",
    "config.json",
    "manifest.json",
)
REQUIRED_FILES = (*CONTENT_FILES, "checksums.json")


def _write_json(path: Path, value: Any) -> None:
    with path.open("wb") as handle:
        handle.write(canonical_json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())


def _tensor_to_base64(value: torch.Tensor) -> str:
    return base64.b64encode(bytes(value.detach().cpu().to(torch.uint8).tolist())).decode("ascii")


def _tensor_from_base64(value: str) -> torch.Tensor:
    return torch.tensor(list(base64.b64decode(value.encode("ascii"))), dtype=torch.uint8)


def capture_rng_state() -> dict[str, Any]:
    python_state = random.getstate()
    return {
        "python": {
            "version": python_state[0],
            "state": list(python_state[1]),
            "gaussian": python_state[2],
        },
        "torch_cpu": _tensor_to_base64(torch.get_rng_state()),
        "torch_cuda": [_tensor_to_base64(item) for item in torch.cuda.get_rng_state_all()] if torch.cuda.is_available() else [],
    }


def restore_rng_state(value: dict[str, Any]) -> None:
    try:
        python_state = value["python"]
        random.setstate((python_state["version"], tuple(python_state["state"]), python_state["gaussian"]))
        torch.set_rng_state(_tensor_from_base64(value["torch_cpu"]))
        cuda_states = [_tensor_from_base64(item) for item in value.get("torch_cuda", [])]
        if cuda_states:
            if not torch.cuda.is_available() or len(cuda_states) != torch.cuda.device_count():
                raise TrainingError("RESUME_STATE_MISMATCH", "CUDA RNG device 수가 현재 환경과 일치하지 않습니다.")
            torch.cuda.set_rng_state_all(cuda_states)
    except (KeyError, TypeError, ValueError) as exc:
        raise TrainingError("RESUME_STATE_MISMATCH", "RNG state 형식이 유효하지 않습니다.") from exc


@dataclass(frozen=True)
class CheckpointInspection:
    path_name: str
    format_version: str
    global_step: int
    model_config_fingerprint: str
    training_config_fingerprint: str
    dataset_fingerprint: str
    tokenizer_fingerprint: str
    files: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_name": self.path_name,
            "format_version": self.format_version,
            "global_step": self.global_step,
            "model_config_fingerprint": self.model_config_fingerprint,
            "training_config_fingerprint": self.training_config_fingerprint,
            "dataset_fingerprint": self.dataset_fingerprint,
            "tokenizer_fingerprint": self.tokenizer_fingerprint,
            "files": list(self.files),
        }


class CheckpointManager:
    def __init__(self, output_root: Path):
        self.output_root = output_root.resolve()

    def checkpoint_path(self, step: int) -> Path:
        return self.output_root / f"checkpoint-{step}"

    def save(
        self,
        *,
        model: nn.Module,
        model_config: ModelConfig,
        optimizer: torch.optim.Optimizer,
        scheduler: LinearWarmupDecayScheduler,
        scaler: torch.amp.GradScaler,
        training_config: TrainingConfig,
        state: TrainingState,
        dataset_metadata: dict[str, Any] | None = None,
    ) -> Path:
        final_path = self.checkpoint_path(state.global_step)
        if final_path.exists():
            raise TrainingError("CHECKPOINT_ALREADY_EXISTS", f"checkpoint-{state.global_step}가 이미 존재합니다.")
        self.output_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".checkpoint-{state.global_step}.staging-", dir=self.output_root)).resolve()
        if staging.parent != self.output_root:
            raise TrainingError("RESUME_STATE_MISMATCH", "안전하지 않은 checkpoint staging 경로입니다.")
        model_config_value = model_config.to_dict()
        model_fingerprint = checksum_value(model_config_value)
        try:
            torch.save(model.state_dict(), staging / "model.pt")
            torch.save(optimizer.state_dict(), staging / "optimizer.pt")
            torch.save(scheduler.state_dict(), staging / "scheduler.pt")
            torch.save(scaler.state_dict(), staging / "scaler.pt")
            state_value = state.to_dict()
            state_value["model_config_fingerprint"] = model_fingerprint
            state_value["training_config_fingerprint"] = training_config.fingerprint()
            _write_json(staging / "training-state.json", {"state": state_value, "rng_state": capture_rng_state()})
            config_value = {
                "model": model_config_value,
                "training": training_config.to_dict(),
                "model_config_fingerprint": model_fingerprint,
                "training_config_fingerprint": training_config.fingerprint(),
                "training_resume_fingerprint": training_config.resume_fingerprint(),
                "optimizer_type": "AdamW",
                "scheduler_type": "linear_warmup_linear_decay",
                "synthetic_dataset": dataset_metadata or {},
            }
            _write_json(staging / "config.json", config_value)
            manifest = {
                "format_version": CHECKPOINT_FORMAT_VERSION,
                "global_step": state.global_step,
                "model_config_fingerprint": model_fingerprint,
                "training_config_fingerprint": training_config.fingerprint(),
                "dataset_fingerprint": state.dataset_fingerprint,
                "tokenizer_fingerprint": state.tokenizer_fingerprint,
                "files": list(REQUIRED_FILES),
            }
            _write_json(staging / "manifest.json", manifest)
            checksums = {name: file_checksum(staging / name) for name in CONTENT_FILES}
            _write_json(staging / "checksums.json", {"algorithm": "sha256", "files": checksums})
            if {path.name for path in staging.iterdir()} != set(REQUIRED_FILES):
                raise TrainingError("RESUME_STATE_MISMATCH", "checkpoint 파일 집합이 계약과 다릅니다.")
            os.replace(staging, final_path)
        except TrainingError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise TrainingError("RESUME_STATE_MISMATCH", "checkpoint를 저장하지 못했습니다.") from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return final_path

    @staticmethod
    def _read_and_verify(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        resolved = path.resolve()
        if not resolved.is_dir() or {item.name for item in resolved.iterdir()} != set(REQUIRED_FILES):
            raise TrainingError("RESUME_STATE_MISMATCH", "checkpoint 필수 파일이 누락되었거나 알 수 없는 파일이 있습니다.")
        try:
            checksums = json.loads((resolved / "checksums.json").read_text(encoding="utf-8"))
            for name in CONTENT_FILES:
                if checksums.get("files", {}).get(name) != file_checksum(resolved / name):
                    raise TrainingError("CHECKPOINT_CHECKSUM_MISMATCH", f"{name} checksum이 일치하지 않습니다.")
            manifest = json.loads((resolved / "manifest.json").read_text(encoding="utf-8"))
            config = json.loads((resolved / "config.json").read_text(encoding="utf-8"))
            state = json.loads((resolved / "training-state.json").read_text(encoding="utf-8"))
        except TrainingError:
            raise
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise TrainingError("RESUME_STATE_MISMATCH", "checkpoint metadata를 읽을 수 없습니다.") from exc
        if manifest.get("format_version") != CHECKPOINT_FORMAT_VERSION:
            raise TrainingError("RESUME_STATE_MISMATCH", "지원하지 않는 checkpoint format입니다.")
        return manifest, config, state

    @classmethod
    def inspect(cls, path: Path) -> CheckpointInspection:
        manifest, _, state_document = cls._read_and_verify(path)
        state = state_document.get("state", {})
        return CheckpointInspection(
            path_name=path.name,
            format_version=manifest["format_version"],
            global_step=state["global_step"],
            model_config_fingerprint=manifest["model_config_fingerprint"],
            training_config_fingerprint=manifest["training_config_fingerprint"],
            dataset_fingerprint=manifest["dataset_fingerprint"],
            tokenizer_fingerprint=manifest["tokenizer_fingerprint"],
            files=tuple(manifest["files"]),
        )

    @classmethod
    def metadata(cls, path: Path) -> dict[str, Any]:
        _, config, _ = cls._read_and_verify(path)
        return config

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        model: nn.Module,
        model_config: ModelConfig,
        optimizer: torch.optim.Optimizer,
        scheduler: LinearWarmupDecayScheduler,
        scaler: torch.amp.GradScaler,
        training_config: TrainingConfig,
        dataset_fingerprint: str,
        tokenizer_fingerprint: str,
        device: torch.device,
        restore_rng: bool = True,
    ) -> TrainingState:
        manifest, config, state_document = cls._read_and_verify(path)
        model_value = model_config.to_dict()
        if config.get("model") != model_value or config.get("model_config_fingerprint") != checksum_value(model_value):
            raise TrainingError("CHECKPOINT_CONFIG_MISMATCH", "model config가 checkpoint와 일치하지 않습니다.")
        if config.get("training_resume_fingerprint") != training_config.resume_fingerprint():
            raise TrainingError("CHECKPOINT_CONFIG_MISMATCH", "핵심 training config가 checkpoint와 일치하지 않습니다.")
        if config.get("optimizer_type") != "AdamW":
            raise TrainingError("CHECKPOINT_CONFIG_MISMATCH", "optimizer type이 checkpoint 계약과 일치하지 않습니다.")
        if manifest.get("tokenizer_fingerprint") != tokenizer_fingerprint:
            raise TrainingError("CHECKPOINT_TOKENIZER_MISMATCH", "tokenizer fingerprint가 일치하지 않습니다.")
        if manifest.get("dataset_fingerprint") != dataset_fingerprint:
            raise TrainingError("CHECKPOINT_DATASET_MISMATCH", "dataset fingerprint가 일치하지 않습니다.")
        try:
            model.load_state_dict(torch.load(path / "model.pt", map_location=device, weights_only=True), strict=True)
            optimizer.load_state_dict(torch.load(path / "optimizer.pt", map_location=device, weights_only=True))
            scheduler.load_state_dict(torch.load(path / "scheduler.pt", map_location="cpu", weights_only=True))
            scaler.load_state_dict(torch.load(path / "scaler.pt", map_location="cpu", weights_only=True))
        except TrainingError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise TrainingError("RESUME_STATE_MISMATCH", "checkpoint state를 복원하지 못했습니다.") from exc
        raw_state = state_document.get("state")
        if not isinstance(raw_state, dict):
            raise TrainingError("RESUME_STATE_MISMATCH", "training state가 유효하지 않습니다.")
        state = TrainingState.from_dict(raw_state)
        if (
            state.global_step != manifest.get("global_step")
            or state.model_config_fingerprint != manifest.get("model_config_fingerprint")
            or state.training_config_fingerprint != manifest.get("training_config_fingerprint")
            or state.dataset_fingerprint != manifest.get("dataset_fingerprint")
            or state.tokenizer_fingerprint != manifest.get("tokenizer_fingerprint")
        ):
            raise TrainingError("RESUME_STATE_MISMATCH", "training state와 manifest fingerprint가 일치하지 않습니다.")
        if state.global_step != scheduler.current_step or state.optimizer_step != state.global_step:
            raise TrainingError("RESUME_STATE_MISMATCH", "optimizer·scheduler·global step이 연속적이지 않습니다.")
        token_embedding = getattr(model, "token_embedding", None)
        lm_head = getattr(model, "lm_head", None)
        if token_embedding is not None and lm_head is not None and token_embedding.weight is not lm_head.weight:
            raise TrainingError("RESUME_STATE_MISMATCH", "checkpoint load 후 weight tying이 유지되지 않았습니다.")
        if restore_rng:
            restore_rng_state(state_document.get("rng_state", {}))
        return state
