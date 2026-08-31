from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from src.training.full_pretraining import FullPretrainingConfig


ELIGIBILITY = Path(
    "docs/data/aihub-71748-candidate-a-internal-production-eligibility.manifest.yaml"
)
PRODUCTION_CONFIG = Path("configs/full-pretraining.production.yaml")
PILOT_MANIFEST = (
    "analysis/pilot-pretraining/AIHUB-71748/prepared/pilot-v2/dataset-manifest.json"
)


def _load(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_internal_production_eligibility_is_exact_and_noncommercial() -> None:
    value = _load(ELIGIBILITY)
    assert value["status"] == "approved"
    assert value["dataset_id"] == "AIHUB-71748"
    assert value["dataset_version"] == "pilot-v2"
    assert value["source_record_count"] == 107_226
    assert value["dataset_fingerprint"] == (
        "sha256:89c721902844d6242d2bbb4a5be4be80286bd7debd19c52b5382078f3110c77b"
    )
    assert value["usage_purpose"] == "internal_noncommercial_full_pretraining"
    assert value["execution_scope"] == "production_internal"
    assert value["internal_training_allowed"] is True
    assert value["commercial_usage_allowed"] is False
    assert value["dataset_redistribution_allowed"] is False
    assert value["model_publication_allowed"] is False
    assert value["historical_execution_approval_reusable"] is False


def test_pilot_manifest_is_not_rewritten_or_auto_upgraded() -> None:
    config = FullPretrainingConfig.from_yaml(PRODUCTION_CONFIG)
    assert config.corpus_manifest == PILOT_MANIFEST
    assert config.dataset_eligibility_manifest == ELIGIBILITY.as_posix()
    assert config.execution_scope == "production_internal"


def test_production_config_fingerprint_is_raw_byte_deterministic() -> None:
    first = PRODUCTION_CONFIG.read_bytes()
    second = PRODUCTION_CONFIG.read_bytes()
    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
