"""Bounded deterministic trainer for synthetic causal-LM verification."""

from __future__ import annotations

import ctypes
import math
import os
import random
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import torch
from torch import Tensor
from torch.utils.data import DataLoader

from src.data.checksums import checksum_value
from src.model import DohaLMTiny

from .checkpoint import CheckpointManager
from .config import TrainingConfig
from .errors import TrainingError
from .metrics import AmpOverflowEvent, JsonlMetricLogger, TrainingMetric
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

    def _train_without_amp_overflow_recovery(
        self,
        *,
        target_steps: int | None = None,
        metric_observer: Callable[[TrainingMetric], None] | None = None,
        amp_overflow_observer: Callable[[AmpOverflowEvent], None] | None = None,
        amp_overflow_limit: int = 3,
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
        amp_overflow_limit: int = 3,
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
        if amp_overflow_limit <= 0:
            raise TrainingError(
                "INVALID_TRAINING_CONFIG", "AMP overflow limit must be positive."
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
                        if amp_overflow_observer is not None:
                            amp_overflow_observer(event)
                        if amp_overflow_count >= amp_overflow_limit:
                            raise TrainingError(
                                "AMP_SKIP_LIMIT",
                                "AMP overflow limit reached before an optimizer update.",
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
