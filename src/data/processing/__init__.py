"""Synthetic-only SFT Dataset Processing backend contracts."""

from .processing_engine import ProcessingResult, process_synthetic_records
from .processing_manifest import (
    MANIFEST_VERSION,
    OUTPUT_SCHEMA_FIELDS,
    STATISTICS_FIELDS,
    InputDatasetIdentity,
    ProcessingApproval,
    ProcessingManifestSchema,
)
from .processing_rules import (
    CANONICAL_SELECTION,
    EXACT_DUPLICATE,
    LEAKAGE,
    NEAR_DUPLICATE,
    PII,
    PROCESSING_ORDER,
    SCHEMA_TRANSFORM,
    VALIDATION_EXCLUSION,
    ProcessingRule,
    default_processing_rules,
)
from .processing_statistics import ProcessingStatistics, RuleImpact
from .processing_validation import ProcessingValidationError

__all__ = [
    "CANONICAL_SELECTION",
    "EXACT_DUPLICATE",
    "InputDatasetIdentity",
    "LEAKAGE",
    "MANIFEST_VERSION",
    "NEAR_DUPLICATE",
    "OUTPUT_SCHEMA_FIELDS",
    "PII",
    "PROCESSING_ORDER",
    "ProcessingApproval",
    "ProcessingManifestSchema",
    "ProcessingResult",
    "ProcessingRule",
    "ProcessingStatistics",
    "ProcessingValidationError",
    "RuleImpact",
    "SCHEMA_TRANSFORM",
    "STATISTICS_FIELDS",
    "VALIDATION_EXCLUSION",
    "default_processing_rules",
    "process_synthetic_records",
]
