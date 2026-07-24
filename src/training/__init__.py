"""Synthetic Trainer Foundation public API."""

from .checkpoint import CheckpointInspection, CheckpointManager, capture_rng_state, restore_rng_state
from .collator import CausalLMCollator
from .config import TrainingConfig
from .dataloader import create_dataloader
from .dataset import SyntheticTokenDataset
from .errors import TrainingError
from .metrics import JsonlMetricLogger, TrainingMetric
from .optimizer import OptimizerStats, create_optimizer
from .scheduler import LinearWarmupDecayScheduler
from .state import TrainingState
from .trainer import Trainer, TrainingResult, seed_everything

__all__ = [
    "CausalLMCollator",
    "CheckpointInspection",
    "CheckpointManager",
    "JsonlMetricLogger",
    "LinearWarmupDecayScheduler",
    "OptimizerStats",
    "SyntheticTokenDataset",
    "Trainer",
    "TrainingConfig",
    "TrainingError",
    "TrainingMetric",
    "TrainingResult",
    "TrainingState",
    "capture_rng_state",
    "create_dataloader",
    "create_optimizer",
    "restore_rng_state",
    "seed_everything",
]
