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
    "SamplerState",
    "StatefulBatchSampler",
    "SyntheticTokenDataset",
    "Trainer",
    "TrainingConfig",
    "TrainingError",
    "TrainingMetric",
    "TrainingResult",
    "TrainingState",
    "ThroughputSummary",
    "capture_rng_state",
    "build_synthetic_stream",
    "build_tiny_trainer",
    "create_dataloader",
    "create_optimizer",
    "create_scheduler",
    "module_gradient_bytes",
    "module_parameter_bytes",
    "optimizer_state_bytes",
    "probe_batch_candidates",
    "restore_rng_state",
    "seed_everything",
    "summarize_throughput",
    "run_tiny_validation",
    "tiny_model_config",
]
