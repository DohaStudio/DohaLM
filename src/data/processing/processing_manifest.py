"""In-memory schema for an SFT processing manifest; no file writer is provided."""

from __future__ import annotations

from dataclasses import dataclass

from .processing_rules import ProcessingRule


MANIFEST_VERSION = "sft-processing-manifest-v1"
OUTPUT_SCHEMA_FIELDS = ("instruction", "input", "output", "system", "metadata")
STATISTICS_FIELDS = (
    "input_count",
    "processed_count",
    "retained_count",
    "excluded_count",
    "rule_impacts",
    "validation_status",
)


@dataclass(frozen=True)
class InputDatasetIdentity:
    dataset_id: str
    dataset_version: str
    component: str
    synthetic: bool


@dataclass(frozen=True)
class ProcessingApproval:
    approval_id: str
    synthetic_validation_allowed: bool
    processing_allowed: bool = False
    training_allowed: bool = False
    execution_allowed: bool = False


@dataclass(frozen=True)
class ProcessingManifestSchema:
    """A manifest schema instance used only as synthetic validation input."""

    input_dataset: InputDatasetIdentity
    dataset_version: str
    rule_set: tuple[ProcessingRule, ...]
    processing_order: tuple[str, ...]
    statistics: tuple[str, ...]
    output_schema: tuple[str, ...]
    approval: ProcessingApproval | None
    manifest_version: str = MANIFEST_VERSION
