"""Synthetic Trainer Foundation public API."""

from .checkpoint import CheckpointInspection, CheckpointManager, capture_rng_state, restore_rng_state
from .collator import CausalLMCollator
from .config import TrainingConfig
from .dataloader import create_dataloader
from .dataset import SyntheticTokenDataset
from .errors import TrainingError
from .metrics import JsonlMetricLogger, TrainingMetric
from .memory_probe import CudaMemoryProbe, MemorySnapshot, module_gradient_bytes, module_parameter_bytes, optimizer_state_bytes
from .optimizer import OptimizerStats, create_optimizer
from .pilot_config import PilotPretrainingConfig
from .pilot_pretraining import build_pilot_trainer, evaluate_pilot_checkpoint, generate_from_pilot_checkpoint, run_pilot_pretraining
from .sampler_state import SamplerState, StatefulBatchSampler
from .scheduler import CosineWarmupDecayScheduler, LinearWarmupDecayScheduler, create_scheduler
from .state import TrainingState
from .throughput import ThroughputSummary, summarize_throughput
from .tiny_validation import (
    DEFAULT_BATCH_CANDIDATES,
    BatchCandidate,
    build_synthetic_stream,
    build_tiny_trainer,
    probe_batch_candidates,
    run_tiny_validation,
    tiny_model_config,
)
from .trainer import Trainer, TrainingResult, seed_everything
from .validation import ValidationResult, evaluate_language_model

__all__ = [
    "CausalLMCollator",
    "BatchCandidate",
    "CheckpointInspection",
    "CheckpointManager",
    "CosineWarmupDecayScheduler",
    "CudaMemoryProbe",
    "DEFAULT_BATCH_CANDIDATES",
    "JsonlMetricLogger",
    "LinearWarmupDecayScheduler",
    "MemorySnapshot",
    "OptimizerStats",
    "PilotPretrainingConfig",
    "SamplerState",
    "StatefulBatchSampler",
    "SyntheticTokenDataset",
    "Trainer",
    "TrainingConfig",
    "TrainingError",
    "TrainingMetric",
    "TrainingResult",
    "TrainingState",
    "ValidationResult",
    "ThroughputSummary",
    "capture_rng_state",
    "build_synthetic_stream",
    "build_pilot_trainer",
    "build_tiny_trainer",
    "create_dataloader",
    "create_optimizer",
    "create_scheduler",
    "evaluate_language_model",
    "evaluate_pilot_checkpoint",
    "generate_from_pilot_checkpoint",
    "module_gradient_bytes",
    "module_parameter_bytes",
    "optimizer_state_bytes",
    "probe_batch_candidates",
    "restore_rng_state",
    "seed_everything",
    "summarize_throughput",
    "run_tiny_validation",
    "run_pilot_pretraining",
    "tiny_model_config",
]
