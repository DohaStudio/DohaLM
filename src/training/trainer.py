"""Bounded deterministic trainer for synthetic causal-LM verification."""

from __future__ import annotations

import ctypes
import hashlib
import math
import os
import pickle
import random
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import torch
from torch import Tensor
from torch.utils.data import DataLoader

from src.data.checksums import checksum_value
from src.model import DohaLMTiny

from .checkpoint import CheckpointManager
from .config import TrainingConfig
from .errors import TrainingError
from .metrics import (
    AmpNumericalDiagnostic,
    AmpOverflowEvent,
    JsonlMetricLogger,
    TrainingMetric,
)
from .optimizer import OptimizerStats, create_optimizer
from .sampler_state import StatefulBatchSampler
from .scheduler import create_scheduler
from .state import TrainingState, utc_now


def _working_set_bytes() -> int | None:
    if os.name != "nt":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    if not psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        return None
    return int(counters.WorkingSetSize)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


@dataclass(frozen=True)
class TrainingResult:
    initial_loss: float
    final_loss: float
    metrics: tuple[TrainingMetric, ...]
    checkpoints: tuple[str, ...]
    state: TrainingState
    optimizer_stats: OptimizerStats

    def to_dict(self) -> dict[str, object]:
        return {
            "initial_loss": self.initial_loss,
            "final_loss": self.final_loss,
            "metrics": [metric.to_dict() for metric in self.metrics],
            "checkpoints": list(self.checkpoints),
            "state": self.state.to_dict(),
            "optimizer_stats": self.optimizer_stats.to_dict(),
        }


@dataclass(frozen=True)
class _GradientDiagnostics:
    total_parameter_count: int
    finite_parameter_count: int
    non_finite_parameter_count: int
    non_finite_element_count: int
    gradients_finite: bool
    first_offending_parameter_id: str | None
    first_offending_parameter_shape: tuple[int, ...] | None
    first_offending_parameter_dtype: str | None
    finite_max_abs: float
    finite_norm: float


class Trainer:
    def __init__(
        self,
        *,
        model: DohaLMTiny,
        dataloader: DataLoader,
        config: TrainingConfig,
        dataset_fingerprint: str,
        tokenizer_fingerprint: str,
        output_root: Path,
        dataset_metadata: dict[str, object] | None = None,
        state: TrainingState | None = None,
        resume: bool = False,
        metric_filename: str = "metrics.jsonl",
    ):
        if len(dataloader) == 0:
            raise TrainingError(
                "EMPTY_DATASET", "DataLoader가 batch를 생성하지 않습니다."
            )
        if not dataset_fingerprint or not tokenizer_fingerprint:
            raise TrainingError(
                "INVALID_TRAINING_CONFIG",
                "dataset과 tokenizer fingerprint가 필요합니다.",
            )
        self.config = config
        self.device = torch.device(config.device)
        self.model = model.to(self.device)
        self.dataloader = dataloader
        self.dataset_fingerprint = dataset_fingerprint
        self.tokenizer_fingerprint = tokenizer_fingerprint
        self.dataset_metadata = dataset_metadata or {}
        self.output_root = output_root.resolve()
        self._session_started = time.perf_counter()
        if resume:
            if not self.output_root.is_dir():
                raise TrainingError(
                    "RESUME_STATE_MISMATCH", "resume output 경로가 존재하지 않습니다."
                )
        else:
            try:
                self.output_root.mkdir(parents=True, exist_ok=False)
            except FileExistsError as exc:
                raise TrainingError(
                    "CHECKPOINT_ALREADY_EXISTS",
                    "기존 training output을 덮어쓸 수 없습니다.",
                ) from exc
        self.optimizer, self.optimizer_stats = create_optimizer(model, config)
        self.scheduler = create_scheduler(
            self.optimizer,
            scheduler_type=config.scheduler_type,
            warmup_steps=config.warmup_steps,
            max_steps=config.max_steps,
            min_lr_ratio=config.min_lr_ratio,
        )
        self.amp_enabled = config.use_amp and self.device.type == "cuda"
        # Bounded smoke default; the production loss-scale policy remains undecided.
        self.scaler = torch.amp.GradScaler(
            "cuda", init_scale=1024.0, enabled=self.amp_enabled
        )
        model_fingerprint = checksum_value(model.config.to_dict())
        self.state = state or TrainingState(
            model_config_fingerprint=model_fingerprint,
            training_config_fingerprint=config.fingerprint(),
            dataset_fingerprint=dataset_fingerprint,
            tokenizer_fingerprint=tokenizer_fingerprint,
        )
        self.checkpoints = CheckpointManager(self.output_root)
        if Path(
            metric_filename
        ).name != metric_filename or not metric_filename.endswith(".jsonl"):
            raise TrainingError(
                "INVALID_TRAINING_CONFIG",
                "metric filename은 단순한 .jsonl 파일명이어야 합니다.",
            )
        self.metric_logger = JsonlMetricLogger(
            self.output_root / metric_filename, append=resume
        )
        self._iterator = None
        if self.state.sampler_state is not None:
            self._load_sampler_state(self.state.sampler_state)
        elif self.state.micro_step:
            self._fast_forward(self.state.micro_step)
        if self.device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(self.device)

    def _fast_forward(self, count: int) -> None:
        self._iterator = iter(self.dataloader)
        for _ in range(count):
            try:
                next(self._iterator)
            except StopIteration:
                self._iterator = iter(self.dataloader)
                next(self._iterator)

    def _next_batch(self) -> dict[str, Tensor]:
        if self._iterator is None:
            self._iterator = iter(self.dataloader)
        try:
            return next(self._iterator)
        except StopIteration:
            self.state.epoch += 1
            self._iterator = iter(self.dataloader)
            return next(self._iterator)

    def _stateful_sampler(self) -> StatefulBatchSampler | None:
        sampler = getattr(self.dataloader, "batch_sampler", None)
        return sampler if isinstance(sampler, StatefulBatchSampler) else None

    def _capture_sampler_state(self) -> None:
        sampler = self._stateful_sampler()
        if sampler is not None:
            self.state.sampler_state = sampler.state_dict()
            self.state.epoch = sampler.epoch

    def _load_sampler_state(self, value: dict[str, object]) -> None:
        sampler = self._stateful_sampler()
        if sampler is None:
            raise TrainingError(
                "RESUME_STATE_MISMATCH",
                "checkpoint sampler state를 복원할 sampler가 없습니다.",
            )
        sampler.load_state_dict(value)
        self._iterator = None

    def _move_batch(self, batch: dict[str, Tensor]) -> dict[str, Tensor]:
        return {
            name: tensor.to(self.device, non_blocking=self.config.pin_memory)
            for name, tensor in batch.items()
        }

    def _gradient_norm(self) -> float:
        squared = 0.0
        for parameter in self.model.parameters():
            if parameter.grad is not None:
                value = parameter.grad.detach().float().norm(2).item()
                squared += value * value
        return math.sqrt(squared)

    def _memory(self) -> tuple[int, int]:
        if self.device.type != "cuda":
            return 0, 0
        torch.cuda.synchronize(self.device)
        return torch.cuda.max_memory_allocated(
            self.device
        ), torch.cuda.max_memory_reserved(self.device)

    def _gradients_are_finite(self) -> bool:
        return all(
            bool(torch.isfinite(parameter.grad).all().item())
            for parameter in self.model.parameters()
            if parameter.grad is not None
        )

    def _model_parameters_are_finite(self) -> bool:
        return all(
            bool(torch.isfinite(parameter.detach()).all().item())
            for parameter in self.model.parameters()
        )

    def _optimizer_state_is_finite(self) -> bool:
        def value_is_finite(value: object) -> bool:
            if isinstance(value, Tensor):
                return bool(torch.isfinite(value.detach()).all().item())
            if isinstance(value, dict):
                return all(value_is_finite(item) for item in value.values())
            if isinstance(value, (list, tuple)):
                return all(value_is_finite(item) for item in value)
            return True

        return value_is_finite(self.optimizer.state)

    @staticmethod
    def _capture_attempt_rng() -> tuple[object, Tensor, list[Tensor]]:
        return (
            random.getstate(),
            torch.get_rng_state(),
            torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
        )

    @staticmethod
    def _restore_attempt_rng(value: tuple[object, Tensor, list[Tensor]]) -> None:
        python_state, cpu_state, cuda_states = value
        random.setstate(python_state)  # type: ignore[arg-type]
        torch.set_rng_state(cpu_state)
        if cuda_states:
            torch.cuda.set_rng_state_all(cuda_states)

    @staticmethod
    def _update_tensor_hash(hasher: Any, tensor: Tensor) -> None:
        detached = tensor.detach().cpu().contiguous()
        hasher.update(str(tuple(detached.shape)).encode("ascii"))
        hasher.update(str(detached.dtype).encode("ascii"))
        hasher.update(detached.reshape(-1).view(torch.uint8).numpy().tobytes())

    @staticmethod
    def _rng_checksums(
        value: tuple[object, Tensor, list[Tensor]],
    ) -> tuple[str, str, str]:
        python_state, cpu_state, cuda_states = value
        python_hash = (
            "sha256:"
            + hashlib.sha256(pickle.dumps(python_state, protocol=5)).hexdigest()
        )
        cpu_hasher = hashlib.sha256()
        Trainer._update_tensor_hash(cpu_hasher, cpu_state)
        cuda_hasher = hashlib.sha256()
        for index, state in enumerate(cuda_states):
            cuda_hasher.update(str(index).encode("ascii"))
            Trainer._update_tensor_hash(cuda_hasher, state)
        return (
            python_hash,
            "sha256:" + cpu_hasher.hexdigest(),
            "sha256:" + cuda_hasher.hexdigest(),
        )

    def _batch_identity(self, batches: list[dict[str, Tensor]]) -> str:
        hasher = hashlib.sha256()
        for batch_index, batch in enumerate(batches):
            hasher.update(str(batch_index).encode("ascii"))
            for name in sorted(batch):
                hasher.update(name.encode("utf-8"))
                self._update_tensor_hash(hasher, batch[name])
        return "sha256:" + hasher.hexdigest()

    def _model_state_fingerprint(self) -> str:
        hasher = hashlib.sha256()
        for name, value in self.model.state_dict().items():
            hasher.update(name.encode("utf-8"))
            self._update_tensor_hash(hasher, value)
        return "sha256:" + hasher.hexdigest()

    def _optimizer_state_fingerprint(self) -> str:
        hasher = hashlib.sha256()
        parameter_indexes: dict[int, int] = {}
        next_index = 0
        for group_index, group in enumerate(self.optimizer.param_groups):
            hasher.update(f"group:{group_index}".encode("ascii"))
            for name in sorted(key for key in group if key != "params"):
                hasher.update(name.encode("utf-8"))
                hasher.update(repr(group[name]).encode("utf-8"))
            for parameter in group["params"]:
                if id(parameter) not in parameter_indexes:
                    parameter_indexes[id(parameter)] = next_index
                    next_index += 1
        for parameter, state in sorted(
            self.optimizer.state.items(),
            key=lambda item: parameter_indexes[id(item[0])],
        ):
            hasher.update(str(parameter_indexes[id(parameter)]).encode("ascii"))
            for name in sorted(state):
                hasher.update(str(name).encode("utf-8"))
                value = state[name]
                if isinstance(value, Tensor):
                    self._update_tensor_hash(hasher, value)
                else:
                    hasher.update(repr(value).encode("utf-8"))
        return "sha256:" + hasher.hexdigest()

    def _gradient_diagnostics(self) -> _GradientDiagnostics:
        total = 0
        finite_parameters = 0
        non_finite_parameters = 0
        non_finite_elements = 0
        finite_squared_norm = 0.0
        finite_max_abs = 0.0
        first_identifier = None
        first_shape = None
        first_dtype = None
        for name, parameter in self.model.named_parameters():
            gradient = parameter.grad
            if gradient is None:
                continue
            total += 1
            detached = gradient.detach()
            finite_mask = torch.isfinite(detached)
            all_finite = bool(finite_mask.all().item())
            if all_finite:
                finite_parameters += 1
            else:
                non_finite_parameters += 1
                non_finite_elements += int((~finite_mask).sum().item())
                if first_identifier is None:
                    identity = f"{name}|{tuple(parameter.shape)}|{parameter.dtype}"
                    first_identifier = (
                        "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
                    )
                    first_shape = tuple(parameter.shape)
                    first_dtype = str(parameter.dtype)
            finite_values = detached[finite_mask].float()
            if finite_values.numel():
                finite_max_abs = max(
                    finite_max_abs, float(finite_values.abs().max().item())
                )
                norm = float(finite_values.norm(2).item())
                finite_squared_norm += norm * norm
        return _GradientDiagnostics(
            total_parameter_count=total,
            finite_parameter_count=finite_parameters,
            non_finite_parameter_count=non_finite_parameters,
            non_finite_element_count=non_finite_elements,
            gradients_finite=non_finite_parameters == 0,
            first_offending_parameter_id=first_identifier,
            first_offending_parameter_shape=first_shape,
            first_offending_parameter_dtype=first_dtype,
            finite_max_abs=finite_max_abs,
            finite_norm=math.sqrt(finite_squared_norm),
        )

    def _probe_amp_numerical_state(
        self,
        *,
        step_batches: list[dict[str, Tensor]],
        attempt_rng_state: tuple[object, Tensor, list[Tensor]],
        overflow_attempt: int,
        current_scale: float,
        scale_floor: float,
        pending_tokens: int,
        pending_records: int,
    ) -> tuple[AmpNumericalDiagnostic, ...]:
        if not 0 < scale_floor or not 0 < current_scale:
            raise TrainingError(
                "DIAGNOSTIC_EVIDENCE_FAILURE",
                "AMP diagnostic scales must be positive.",
            )
        scales = [current_scale]
        scale = current_scale
        while scale / 2.0 >= scale_floor:
            scale /= 2.0
            scales.append(scale)

        batch_identity = self._batch_identity(step_batches)
        python_rng, cpu_rng, cuda_rng = self._rng_checksums(attempt_rng_state)
        entry_rng_state = self._capture_attempt_rng()
        entry_rng_checksums = self._rng_checksums(entry_rng_state)
        model_fingerprint = self._model_state_fingerprint()
        optimizer_fingerprint = self._optimizer_state_fingerprint()
        scheduler_fingerprint = checksum_value(self.scheduler.state_dict())
        scaler_fingerprint = checksum_value(self.scaler.state_dict())
        sampler = self._stateful_sampler()
        sampler_state = sampler.state_dict() if sampler is not None else None
        sampler_fingerprint = (
            checksum_value(sampler_state) if sampler_state is not None else None
        )
        accounting_state = (
            self.state.global_step,
            self.state.optimizer_step,
            self.state.micro_step,
            self.state.tokens_seen,
            self.state.records_seen,
        )
        records = []
        try:
            for probe_scale in scales:
                self.optimizer.zero_grad(set_to_none=True)
                self._restore_attempt_rng(attempt_rng_state)
                loss_finite = True
                scaled_loss_finite = True
                for batch in step_batches:
                    with torch.amp.autocast(
                        device_type=self.device.type,
                        dtype=torch.float16,
                        enabled=True,
                    ):
                        output = self.model(
                            batch["input_ids"],
                            attention_mask=batch["attention_mask"],
                            labels=batch["labels"],
                        )
                        if output.loss is None:
                            loss_finite = False
                            scaled_loss_finite = False
                            break
                        loss_finite = loss_finite and bool(
                            torch.isfinite(output.loss).item()
                        )
                        normalized_loss = (
                            output.loss / self.config.gradient_accumulation_steps
                        )
                        diagnostic_scaled_loss = normalized_loss * probe_scale
                        scaled_loss_finite = scaled_loss_finite and bool(
                            torch.isfinite(diagnostic_scaled_loss).item()
                        )
                    if not loss_finite or not scaled_loss_finite:
                        break
                    diagnostic_scaled_loss.backward()

                scaled = self._gradient_diagnostics()
                with torch.no_grad():
                    for parameter in self.model.parameters():
                        if parameter.grad is not None:
                            parameter.grad.mul_(1.0 / probe_scale)
                unscaled = self._gradient_diagnostics()
                first = (
                    unscaled
                    if unscaled.first_offending_parameter_id is not None
                    else scaled
                )
                self.optimizer.zero_grad(set_to_none=True)
                self._restore_attempt_rng(entry_rng_state)
                rng_restored = (
                    self._rng_checksums(self._capture_attempt_rng())
                    == entry_rng_checksums
                )
                current_sampler_state = (
                    sampler.state_dict() if sampler is not None else None
                )
                records.append(
                    AmpNumericalDiagnostic(
                        run_id=self.output_root.name,
                        global_step=self.state.global_step,
                        next_optimizer_step=self.state.global_step + 1,
                        overflow_attempt=overflow_attempt,
                        probe_scale=probe_scale,
                        sampler_cursor=(
                            sampler.sample_offset if sampler is not None else None
                        ),
                        pending_records=pending_records,
                        pending_tokens=pending_tokens,
                        batch_identity_sha256=batch_identity,
                        python_rng_sha256=python_rng,
                        cpu_rng_sha256=cpu_rng,
                        cuda_rng_sha256=cuda_rng,
                        sampler_state_sha256=sampler_fingerprint,
                        model_state_sha256=model_fingerprint,
                        optimizer_state_sha256=optimizer_fingerprint,
                        total_gradient_parameter_count=scaled.total_parameter_count,
                        scaled_finite_gradient_parameter_count=(
                            scaled.finite_parameter_count
                        ),
                        scaled_non_finite_gradient_parameter_count=(
                            scaled.non_finite_parameter_count
                        ),
                        scaled_non_finite_element_count=(
                            scaled.non_finite_element_count
                        ),
                        scaled_gradients_finite=scaled.gradients_finite,
                        unscaled_finite_gradient_parameter_count=(
                            unscaled.finite_parameter_count
                        ),
                        unscaled_non_finite_gradient_parameter_count=(
                            unscaled.non_finite_parameter_count
                        ),
                        unscaled_non_finite_element_count=(
                            unscaled.non_finite_element_count
                        ),
                        unscaled_gradients_finite=unscaled.gradients_finite,
                        first_offending_parameter_id=(
                            first.first_offending_parameter_id
                        ),
                        first_offending_parameter_shape=(
                            first.first_offending_parameter_shape
                        ),
                        first_offending_parameter_dtype=(
                            first.first_offending_parameter_dtype
                        ),
                        finite_gradient_max_abs=unscaled.finite_max_abs,
                        finite_gradient_norm=unscaled.finite_norm,
                        loss_finite=loss_finite,
                        scaled_loss_finite=scaled_loss_finite,
                        grad_scaler_found_inf=not unscaled.gradients_finite,
                        model_parameters_finite=(self._model_parameters_are_finite()),
                        optimizer_state_finite=self._optimizer_state_is_finite(),
                        model_state_unchanged=(
                            self._model_state_fingerprint() == model_fingerprint
                        ),
                        optimizer_state_unchanged=(
                            self._optimizer_state_fingerprint() == optimizer_fingerprint
                        ),
                        scheduler_state_unchanged=(
                            checksum_value(self.scheduler.state_dict())
                            == scheduler_fingerprint
                        ),
                        scaler_state_unchanged=(
                            checksum_value(self.scaler.state_dict())
                            == scaler_fingerprint
                        ),
                        sampler_state_unchanged=(
                            current_sampler_state == sampler_state
                        ),
                        accounting_state_unchanged=(
                            (
                                self.state.global_step,
                                self.state.optimizer_step,
                                self.state.micro_step,
                                self.state.tokens_seen,
                                self.state.records_seen,
                            )
                            == accounting_state
                        ),
                        rng_state_restored=rng_restored,
                        optimizer_step_applied=False,
                        actual_text_values_stored=False,
                        token_ids_stored=False,
                        timestamp=utc_now(),
                    )
                )
        except Exception as exc:
            self.optimizer.zero_grad(set_to_none=True)
            self._restore_attempt_rng(entry_rng_state)
            if isinstance(exc, TrainingError) and exc.code == (
                "DIAGNOSTIC_EVIDENCE_FAILURE"
            ):
                raise
            raise TrainingError(
                "DIAGNOSTIC_EVIDENCE_FAILURE",
                "AMP numerical diagnostic probe failed closed.",
            ) from exc
        finally:
            self.optimizer.zero_grad(set_to_none=True)
            self._restore_attempt_rng(entry_rng_state)

        if not records or not all(
            record.model_state_unchanged
            and record.optimizer_state_unchanged
            and record.scheduler_state_unchanged
            and record.scaler_state_unchanged
            and record.sampler_state_unchanged
            and record.accounting_state_unchanged
            and record.rng_state_restored
            and not record.optimizer_step_applied
            for record in records
        ):
            raise TrainingError(
                "DIAGNOSTIC_EVIDENCE_FAILURE",
                "AMP diagnostic probe changed protected training state.",
            )
        return tuple(records)

    def _train_without_amp_overflow_recovery(
        self,
        *,
        target_steps: int | None = None,
        metric_observer: Callable[[TrainingMetric], None] | None = None,
        amp_overflow_observer: Callable[[AmpOverflowEvent], None] | None = None,
        before_optimizer_step: Callable[[int], None] | None = None,
    ) -> TrainingResult:
        target = self.config.max_steps if target_steps is None else target_steps
        if target <= self.state.global_step or target > self.config.max_steps:
            raise TrainingError(
                "INVALID_TRAINING_CONFIG",
                "target_steps는 현재 step보다 크고 max_steps 이하여야 합니다.",
            )
        self.model.train()
        collected: list[TrainingMetric] = []
        checkpoint_names: list[str] = []
        first_loss: float | None = None
        self.optimizer.zero_grad(set_to_none=True)
        while self.state.global_step < target:
            step_started = time.perf_counter()
            step_losses: list[float] = []
            step_tokens = 0
            step_records = 0
            start_micro = self.state.micro_step
            start_tokens = self.state.tokens_seen
            start_records = self.state.records_seen
            try:
                for _ in range(self.config.gradient_accumulation_steps):
                    batch = self._move_batch(self._next_batch())
                    with torch.amp.autocast(
                        device_type=self.device.type,
                        dtype=torch.float16,
                        enabled=self.amp_enabled,
                    ):
                        output = self.model(
                            batch["input_ids"],
                            attention_mask=batch["attention_mask"],
                            labels=batch["labels"],
                        )
                        if output.loss is None or not bool(
                            torch.isfinite(output.loss).item()
                        ):
                            raise TrainingError(
                                "NON_FINITE_LOSS", "loss가 NaN 또는 Inf입니다."
                            )
                        scaled_loss = (
                            output.loss / self.config.gradient_accumulation_steps
                        )
                    self.scaler.scale(scaled_loss).backward()
                    raw_loss = float(output.loss.detach().float().cpu().item())
                    step_losses.append(raw_loss)
                    step_tokens += int(batch["attention_mask"].sum().item())
                    step_records += int(batch["input_ids"].shape[0])

                self.scaler.unscale_(self.optimizer)
                try:
                    before_clip = float(
                        torch.nn.utils.clip_grad_norm_(
                            self.model.parameters(),
                            self.config.max_grad_norm,
                            error_if_nonfinite=True,
                        ).item()
                    )
                except RuntimeError as exc:
                    raise TrainingError(
                        "NON_FINITE_GRADIENT", "gradient norm이 NaN 또는 Inf입니다."
                    ) from exc
                after_clip = self._gradient_norm()
                if not math.isfinite(after_clip):
                    raise TrainingError(
                        "NON_FINITE_GRADIENT",
                        "clipping 후 gradient가 NaN 또는 Inf입니다.",
                    )
                if before_optimizer_step is not None:
                    before_optimizer_step(self.state.global_step + 1)
                scale_before = self.scaler.get_scale()
                self.scaler.step(self.optimizer)
                self.scaler.update()
                amp_step_skipped = (
                    self.amp_enabled and self.scaler.get_scale() < scale_before
                )
                self.scheduler.step()
                self.optimizer.zero_grad(set_to_none=True)
            except Exception:
                self.optimizer.zero_grad(set_to_none=True)
                self.state.micro_step = start_micro
                self.state.tokens_seen = start_tokens
                self.state.records_seen = start_records
                raise

            self.state.micro_step += self.config.gradient_accumulation_steps
            self.state.global_step += 1
            self.state.optimizer_step += 1
            self.state.tokens_seen += step_tokens
            self.state.records_seen += step_records
            self._capture_sampler_state()
            mean_loss = sum(step_losses) / len(step_losses)
            learning_rate = self.scheduler.get_last_lr()[0]
            elapsed = max(time.perf_counter() - step_started, 1e-12)
            allocated, reserved = self._memory()
            metric = TrainingMetric(
                global_step=self.state.global_step,
                loss=mean_loss,
                learning_rate=learning_rate,
                gradient_norm=after_clip,
                gradient_norm_before_clip=before_clip,
                tokens_seen=self.state.tokens_seen,
                records_seen=self.state.records_seen,
                step_time=elapsed,
                tokens_per_second=step_tokens / elapsed,
                peak_memory_allocated=allocated,
                peak_memory_reserved=reserved,
                amp_step_skipped=amp_step_skipped,
                micro_step=self.state.micro_step,
                amp_scale=float(self.scaler.get_scale()),
                sampler_cursor=(self.state.sampler_state or {}).get("sample_offset"),
                equivalent_epoch=self.state.records_seen
                / max(1, len(self.dataloader.dataset)),
                cpu_working_set_bytes=_working_set_bytes(),
                remaining_disk_bytes=shutil.disk_usage(self.output_root).free,
                run_output_bytes=sum(
                    path.stat().st_size
                    for path in self.output_root.rglob("*")
                    if path.is_file()
                ),
                elapsed_wall_clock=time.perf_counter() - self._session_started,
                timestamp=utc_now(),
            )
            self.state.last_loss = mean_loss
            self.state.last_learning_rate = learning_rate
            self.state.best_metric = (
                mean_loss
                if self.state.best_metric is None
                else min(self.state.best_metric, mean_loss)
            )
            self.state.updated_at = utc_now()
            if first_loss is None:
                first_loss = mean_loss
            collected.append(metric)
            if metric_observer is not None:
                metric_observer(metric)
            if self.state.global_step % self.config.log_every == 0:
                self.metric_logger.write(metric)
            if self.state.global_step % self.config.save_every == 0:
                checkpoint = self.checkpoints.save(
                    model=self.model,
                    model_config=self.model.config,
                    optimizer=self.optimizer,
                    scheduler=self.scheduler,
                    scaler=self.scaler,
                    training_config=self.config,
                    state=self.state,
                    dataset_metadata=self.dataset_metadata,
                )
                checkpoint_names.append(checkpoint.name)
        assert first_loss is not None
        return TrainingResult(
            initial_loss=first_loss,
            final_loss=collected[-1].loss,
            metrics=tuple(collected),
            checkpoints=tuple(checkpoint_names),
            state=self.state,
            optimizer_stats=self.optimizer_stats,
        )

    def train(
        self,
        *,
        target_steps: int | None = None,
        metric_observer: Callable[[TrainingMetric], None] | None = None,
        amp_overflow_observer: Callable[[AmpOverflowEvent], None] | None = None,
        amp_diagnostic_observer: (
            Callable[[AmpNumericalDiagnostic], None] | None
        ) = None,
        minimum_amp_scale: float = 1_024.0,
        amp_diagnostic_scale_floor: float | None = None,
        before_optimizer_step: Callable[[int], None] | None = None,
    ) -> TrainingResult:
        if not self.amp_enabled:
            return self._train_without_amp_overflow_recovery(
                target_steps=target_steps,
                metric_observer=metric_observer,
                before_optimizer_step=before_optimizer_step,
            )
        target = self.config.max_steps if target_steps is None else target_steps
        if target <= self.state.global_step or target > self.config.max_steps:
            raise TrainingError(
                "INVALID_TRAINING_CONFIG",
                "target_steps must be greater than the current step and within max_steps.",
            )
        if (
            not math.isfinite(minimum_amp_scale)
            or minimum_amp_scale <= 0
            or not float(minimum_amp_scale).is_integer()
            or int(minimum_amp_scale) & (int(minimum_amp_scale) - 1)
        ):
            raise TrainingError(
                "INVALID_TRAINING_CONFIG",
                "Minimum AMP scale must be a positive power of two.",
            )
        if (amp_diagnostic_observer is None) != (amp_diagnostic_scale_floor is None):
            raise TrainingError(
                "INVALID_TRAINING_CONFIG",
                "AMP diagnostic observer and scale floor must be configured together.",
            )

        self.model.train()
        collected: list[TrainingMetric] = []
        checkpoint_names: list[str] = []
        first_loss: float | None = None
        self.optimizer.zero_grad(set_to_none=True)
        while self.state.global_step < target:
            step_started = time.perf_counter()
            start_micro = self.state.micro_step
            start_tokens = self.state.tokens_seen
            start_records = self.state.records_seen
            amp_overflow_count = 0
            try:
                step_batches = [
                    self._move_batch(self._next_batch())
                    for _ in range(self.config.gradient_accumulation_steps)
                ]
                attempt_rng_state = self._capture_attempt_rng()
                while True:
                    if amp_overflow_count:
                        self._restore_attempt_rng(attempt_rng_state)
                    step_losses: list[float] = []
                    step_tokens = 0
                    step_records = 0
                    for batch in step_batches:
                        with torch.amp.autocast(
                            device_type=self.device.type,
                            dtype=torch.float16,
                            enabled=True,
                        ):
                            output = self.model(
                                batch["input_ids"],
                                attention_mask=batch["attention_mask"],
                                labels=batch["labels"],
                            )
                            if output.loss is None or not bool(
                                torch.isfinite(output.loss).item()
                            ):
                                raise TrainingError(
                                    "NON_FINITE_LOSS", "Loss is NaN or Inf."
                                )
                            scaled_loss = (
                                output.loss / self.config.gradient_accumulation_steps
                            )
                        self.scaler.scale(scaled_loss).backward()
                        step_losses.append(
                            float(output.loss.detach().float().cpu().item())
                        )
                        step_tokens += int(batch["attention_mask"].sum().item())
                        step_records += int(batch["input_ids"].shape[0])

                    self.scaler.unscale_(self.optimizer)
                    try:
                        before_clip = float(
                            torch.nn.utils.clip_grad_norm_(
                                self.model.parameters(),
                                self.config.max_grad_norm,
                                error_if_nonfinite=True,
                            ).item()
                        )
                    except RuntimeError as exc:
                        if self._gradients_are_finite():
                            raise TrainingError(
                                "NON_FINITE_GRADIENT",
                                "Gradient norm is non-finite despite finite tensors.",
                            ) from exc
                        model_finite = self._model_parameters_are_finite()
                        optimizer_finite = self._optimizer_state_is_finite()
                        if not model_finite or not optimizer_finite:
                            raise TrainingError(
                                "NON_FINITE_GRADIENT",
                                "Model or optimizer state is non-finite.",
                            ) from exc

                        scale_before = float(self.scaler.get_scale())
                        self.scaler.step(self.optimizer)
                        self.scaler.update()
                        scale_after = float(self.scaler.get_scale())
                        self.optimizer.zero_grad(set_to_none=True)
                        if not scale_after < scale_before:
                            raise TrainingError(
                                "NON_FINITE_GRADIENT",
                                "Non-finite gradient did not produce AMP scale backoff.",
                            ) from exc
                        amp_overflow_count += 1
                        sampler = self._stateful_sampler()
                        event = AmpOverflowEvent(
                            global_step=self.state.global_step,
                            next_optimizer_step=self.state.global_step + 1,
                            attempt=amp_overflow_count,
                            scale_before=scale_before,
                            scale_after=scale_after,
                            pending_tokens=step_tokens,
                            pending_records=step_records,
                            sampler_cursor=(
                                sampler.sample_offset if sampler is not None else None
                            ),
                            model_parameters_finite=model_finite,
                            optimizer_state_finite=optimizer_finite,
                            timestamp=utc_now(),
                        )
                        if (
                            amp_diagnostic_observer is not None
                            and amp_diagnostic_scale_floor is not None
                        ):
                            diagnostics = self._probe_amp_numerical_state(
                                step_batches=step_batches,
                                attempt_rng_state=attempt_rng_state,
                                overflow_attempt=amp_overflow_count,
                                current_scale=scale_before,
                                scale_floor=amp_diagnostic_scale_floor,
                                pending_tokens=step_tokens,
                                pending_records=step_records,
                            )
                            try:
                                for diagnostic in diagnostics:
                                    amp_diagnostic_observer(diagnostic)
                            except Exception as diagnostic_error:
                                raise TrainingError(
                                    "DIAGNOSTIC_EVIDENCE_FAILURE",
                                    "AMP numerical diagnostic evidence write failed.",
                                ) from diagnostic_error
                        if amp_overflow_observer is not None:
                            amp_overflow_observer(event)
                        if scale_after < minimum_amp_scale:
                            raise TrainingError(
                                "FULL_PRETRAINING_AMP_SCALE_FLOOR_EXHAUSTED",
                                "AMP overflow requires a scale below the configured floor.",
                            )
                        continue

                    after_clip = self._gradient_norm()
                    if not math.isfinite(after_clip):
                        raise TrainingError(
                            "NON_FINITE_GRADIENT",
                            "Gradient is non-finite after clipping.",
                        )
                    if before_optimizer_step is not None:
                        before_optimizer_step(self.state.global_step + 1)
                    scale_before = self.scaler.get_scale()
                    self.scaler.step(self.optimizer)
                    self.scaler.update()
                    if self.scaler.get_scale() < scale_before:
                        raise TrainingError(
                            "NON_FINITE_GRADIENT",
                            "AMP skipped an update after finite gradient validation.",
                        )
                    self.scheduler.step()
                    self.optimizer.zero_grad(set_to_none=True)
                    break
            except Exception:
                self.optimizer.zero_grad(set_to_none=True)
                self.state.micro_step = start_micro
                self.state.tokens_seen = start_tokens
                self.state.records_seen = start_records
                raise

            self.state.micro_step += self.config.gradient_accumulation_steps
            self.state.global_step += 1
            self.state.optimizer_step += 1
            self.state.tokens_seen += step_tokens
            self.state.records_seen += step_records
            self._capture_sampler_state()
            mean_loss = sum(step_losses) / len(step_losses)
            learning_rate = self.scheduler.get_last_lr()[0]
            elapsed = max(time.perf_counter() - step_started, 1e-12)
            allocated, reserved = self._memory()
            metric = TrainingMetric(
                global_step=self.state.global_step,
                loss=mean_loss,
                learning_rate=learning_rate,
                gradient_norm=after_clip,
                gradient_norm_before_clip=before_clip,
                tokens_seen=self.state.tokens_seen,
                records_seen=self.state.records_seen,
                step_time=elapsed,
                tokens_per_second=step_tokens / elapsed,
                peak_memory_allocated=allocated,
                peak_memory_reserved=reserved,
                amp_step_skipped=False,
                amp_overflow_count=amp_overflow_count,
                micro_step=self.state.micro_step,
                amp_scale=float(self.scaler.get_scale()),
                sampler_cursor=(self.state.sampler_state or {}).get("sample_offset"),
                equivalent_epoch=self.state.records_seen
                / max(1, len(self.dataloader.dataset)),
                cpu_working_set_bytes=_working_set_bytes(),
                remaining_disk_bytes=shutil.disk_usage(self.output_root).free,
                run_output_bytes=sum(
                    path.stat().st_size
                    for path in self.output_root.rglob("*")
                    if path.is_file()
                ),
                elapsed_wall_clock=time.perf_counter() - self._session_started,
                timestamp=utc_now(),
            )
            self.state.last_loss = mean_loss
            self.state.last_learning_rate = learning_rate
            self.state.best_metric = (
                mean_loss
                if self.state.best_metric is None
                else min(self.state.best_metric, mean_loss)
            )
            self.state.updated_at = utc_now()
            if first_loss is None:
                first_loss = mean_loss
            collected.append(metric)
            if metric_observer is not None:
                metric_observer(metric)
            if self.state.global_step % self.config.log_every == 0:
                self.metric_logger.write(metric)
            if self.state.global_step % self.config.save_every == 0:
                checkpoint = self.checkpoints.save(
                    model=self.model,
                    model_config=self.model.config,
                    optimizer=self.optimizer,
                    scheduler=self.scheduler,
                    scaler=self.scaler,
                    training_config=self.config,
                    state=self.state,
                    dataset_metadata=self.dataset_metadata,
                )
                checkpoint_names.append(checkpoint.name)

        assert first_loss is not None
        return TrainingResult(
            initial_loss=first_loss,
            final_loss=collected[-1].loss,
            metrics=tuple(collected),
            checkpoints=tuple(checkpoint_names),
            state=self.state,
            optimizer_stats=self.optimizer_stats,
        )

    def resume_from(
        self,
        checkpoint: Path,
        *,
        restore_rng: bool = True,
        allow_scheduler_horizon_extension: bool = False,
        expected_source_step: int | None = None,
    ) -> TrainingState:
        self.state = CheckpointManager.load(
            checkpoint,
            model=self.model,
            model_config=self.model.config,
            optimizer=self.optimizer,
            scheduler=self.scheduler,
            scaler=self.scaler,
            training_config=self.config,
            dataset_fingerprint=self.dataset_fingerprint,
            tokenizer_fingerprint=self.tokenizer_fingerprint,
            dataset_metadata=self.dataset_metadata,
            device=self.device,
            restore_rng=restore_rng,
            allow_scheduler_horizon_extension=allow_scheduler_horizon_extension,
            expected_source_step=expected_source_step,
        )
        if self.state.sampler_state is not None:
            self._load_sampler_state(self.state.sampler_state)
        else:
            self._fast_forward(self.state.micro_step)
        return self.state
