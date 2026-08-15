"""Synthetic Trainer Foundation public API."""

from .checkpoint import (
    CheckpointInspection,
    CheckpointManager,
    capture_rng_state,
    restore_rng_state,
)
from .collator import CausalLMCollator
from .config import TrainingConfig
from .dataloader import create_dataloader
from .dataset_training_entry import (
    DatasetTrainingPermission,
    evaluate_dataset_training_entry,
    require_dataset_training_activation,
)
from .dataset import SyntheticTokenDataset
from .errors import TrainingError
from .execution_approval import (
    TrainingExecutionApproval,
    TrainingExecutionRequest,
    build_training_execution_request,
    consume_training_execution_approval,
    require_training_execution_request,
)
from .execution_issuer import issue_training_execution_approval
from .gate7_overfit import (
    Gate7OverfitConfig,
    clone_gate7_prepared,
    evaluate_gate7_checkpoint,
    evaluate_gate7_model,
    prepare_gate7_overfit,
    run_gate7_training,
)
from .metrics import JsonlMetricLogger, TrainingMetric
from .memory_probe import (
    CudaMemoryProbe,
    MemorySnapshot,
    module_gradient_bytes,
    module_parameter_bytes,
    optimizer_state_bytes,
)
from .optimizer import OptimizerStats, create_optimizer
from .pilot_config import PilotPretrainingConfig
from .pilot_execution import inspect_pilot_execution, require_pilot_execution_approval
from .pilot_pretraining import (
    build_pilot_trainer,
    evaluate_pilot_checkpoint,
    generate_from_pilot_checkpoint,
    run_pilot_pretraining,
)
from .production_host_foundation import (
    DurableTrainingOrchestrationJournal,
    ProductionTrainingHostIntent,
    ResolvedTrainingExecutionDecision,
    TrainingDecisionResolutionRequest,
    TrainingOrchestrationClaimRequest,
    TrainingOrchestrationClaimResult,
    TrainingOrchestrationClaimStatus,
    TrainingOrchestrationIdentity,
    TrainingOrchestrationPhase,
    TrainingOrchestrationRecord,
    TrainingOrchestrationTransition,
    TrustedDecisionProvenance,
    TrustedDecisionResolution,
    TrustedTrainingDecisionResolver,
)
from .production_full_pretraining_host import (
    ProductionFullPretrainingHost,
    ProductionTrainingHostResult,
)
from .sampler_state import SamplerState, StatefulBatchSampler
from .scheduler import (
    CosineWarmupDecayScheduler,
    LinearWarmupDecayScheduler,
    create_scheduler,
)
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
    "DatasetTrainingPermission",
    "DurableTrainingOrchestrationJournal",
    "DEFAULT_BATCH_CANDIDATES",
    "JsonlMetricLogger",
    "Gate7OverfitConfig",
    "LinearWarmupDecayScheduler",
    "MemorySnapshot",
    "OptimizerStats",
    "PilotPretrainingConfig",
    "ProductionTrainingHostIntent",
    "ProductionFullPretrainingHost",
    "ProductionTrainingHostResult",
    "ResolvedTrainingExecutionDecision",
    "inspect_pilot_execution",
    "require_pilot_execution_approval",
    "require_dataset_training_activation",
    "SamplerState",
    "StatefulBatchSampler",
    "SyntheticTokenDataset",
    "Trainer",
    "TrainingConfig",
    "TrainingDecisionResolutionRequest",
    "TrainingError",
    "TrainingExecutionApproval",
    "TrainingExecutionRequest",
    "TrainingOrchestrationClaimResult",
    "TrainingOrchestrationClaimRequest",
    "TrainingOrchestrationClaimStatus",
    "TrainingOrchestrationIdentity",
    "TrainingOrchestrationPhase",
    "TrainingOrchestrationRecord",
    "TrainingOrchestrationTransition",
    "TrainingMetric",
    "TrainingResult",
    "TrainingState",
    "TrustedDecisionProvenance",
    "TrustedDecisionResolution",
    "TrustedTrainingDecisionResolver",
    "ValidationResult",
    "ThroughputSummary",
    "capture_rng_state",
    "build_synthetic_stream",
    "build_training_execution_request",
    "build_pilot_trainer",
    "build_tiny_trainer",
    "clone_gate7_prepared",
    "create_dataloader",
    "create_optimizer",
    "create_scheduler",
    "consume_training_execution_approval",
    "evaluate_language_model",
    "evaluate_dataset_training_entry",
    "evaluate_gate7_checkpoint",
    "evaluate_gate7_model",
    "issue_training_execution_approval",
    "evaluate_pilot_checkpoint",
    "generate_from_pilot_checkpoint",
    "module_gradient_bytes",
    "module_parameter_bytes",
    "optimizer_state_bytes",
    "probe_batch_candidates",
    "prepare_gate7_overfit",
    "restore_rng_state",
    "seed_everything",
    "summarize_throughput",
    "run_tiny_validation",
    "run_gate7_training",
    "run_pilot_pretraining",
    "require_training_execution_request",
    "tiny_model_config",
]
