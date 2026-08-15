"""Keep C1/C2 PostgreSQL contract collection independent of optional Torch."""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace


def install() -> None:
    """Install only the unused heavyweight boundaries absent from the C1 lock."""

    force_minimal = os.environ.get("DOHALM_C1_FORCE_MINIMAL_IMPORTS") == "1"
    if not force_minimal and importlib.util.find_spec("torch") is not None:
        return

    source_root = Path(__file__).resolve().parents[1] / "src"
    training_root = source_root / "training"

    training_package = ModuleType("src.training")
    training_package.__path__ = [str(training_root)]
    training_package.__package__ = "src.training"
    sys.modules.setdefault("src.training", training_package)

    torch = ModuleType("torch")
    torch.cuda = SimpleNamespace(is_available=lambda: False)
    sys.modules.setdefault("torch", torch)

    @dataclass(frozen=True)
    class ModelConfig:
        """Minimum import-time shape; C2 tests never construct a model."""

        vocab_size: int = 16_000

    model = ModuleType("src.model")
    model.ModelConfig = ModelConfig
    sys.modules.setdefault("src.model", model)

    def unavailable_lineage(*_: object, **__: object) -> dict[str, object]:
        raise AssertionError("C1/C2 PostgreSQL contracts must not enter training")

    pilot = ModuleType("src.training.pilot_pretraining")
    pilot._lineage = unavailable_lineage
    sys.modules.setdefault("src.training.pilot_pretraining", pilot)


install()

_adapters = importlib.import_module("src.training.postgres_training_adapters")
_dataset_entry = importlib.import_module("src.training.dataset_training_entry")
_errors = importlib.import_module("src.training.errors")
_foundation = importlib.import_module("src.training.production_host_foundation")
_seams = importlib.import_module("src.training.production_orchestration_seams")

DatasetTrainingPermission = _dataset_entry.DatasetTrainingPermission
TrainingError = _errors.TrainingError
_CLAIM_JOURNAL_COLUMN_MAP = _adapters._CLAIM_JOURNAL_COLUMN_MAP
_PostgresTrainingConnectionFactory = _adapters._PostgresTrainingConnectionFactory
_PostgresTrainingConnectionSettings = _adapters._PostgresTrainingConnectionSettings
_PostgresTrainingDecisionResolver = _adapters._PostgresTrainingDecisionResolver
_PostgresTrainingExecutionJournal = _adapters._PostgresTrainingExecutionJournal
_PostgresTrainingPrerequisiteResolver = _adapters._PostgresTrainingPrerequisiteResolver
_map_journal_error = _adapters._map_journal_error
ProductionTrainingHostIntent = _foundation.ProductionTrainingHostIntent
TrainingDecisionResolutionRequest = _foundation.TrainingDecisionResolutionRequest
TrainingOrchestrationClaimRequest = _foundation.TrainingOrchestrationClaimRequest
TrainingOrchestrationIdentity = _foundation.TrainingOrchestrationIdentity
TrainingOrchestrationPhase = _foundation.TrainingOrchestrationPhase
TrainingOrchestrationTransition = _foundation.TrainingOrchestrationTransition
TrainingPrerequisiteResolutionRequest = _seams.TrainingPrerequisiteResolutionRequest
