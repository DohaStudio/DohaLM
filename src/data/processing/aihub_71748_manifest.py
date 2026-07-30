"""Fail-closed validation for the non-executable AIHUB-71748 SFT manifest."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from pathlib import PurePosixPath, PureWindowsPath


MANIFEST_TYPE = "sft_dataset_processing"
MANIFEST_VERSION = 1
DATASET_ID = "AIHUB-71748"
COMPONENT = "SFT"

RULE_ORDER = (
    "INPUT_IDENTITY_VALIDATION",
    "SCHEMA_VALIDATION",
    "JOIN_VALIDATION",
    "OUTPUT_SCHEMA_MAPPING",
    "PII_POLICY",
    "EXACT_DUPLICATE_POLICY",
    "NEAR_DUPLICATE_POLICY",
    "LEAKAGE_POLICY",
    "VALIDATION_SPLIT_POLICY",
    "FINAL_SCHEMA_VALIDATION",
    "STATISTICS_VALIDATION",
    "MANIFEST_FINALIZATION",
)
POLICY_RULES = frozenset(
    {
        "SCHEMA_MAPPING",
        "PII_POLICY",
        "EXACT_DUPLICATE_POLICY",
        "NEAR_DUPLICATE_POLICY",
        "LEAKAGE_POLICY",
        "VALIDATION_SPLIT_POLICY",
    }
)
ALLOWED_ACTIONS = (
    "KEEP",
    "CANONICAL_CANDIDATE",
    "REVIEW_REQUIRED",
    "VALIDATION_EXCLUSION_CANDIDATE",
    "BLOCKED",
    "UNRESOLVED",
)
PROHIBITED_ACTIONS = (
    "automatic_mask",
    "automatic_merge",
    "rewrite",
    "synthetic_replace",
    "split_move",
    "label_generation_from_llm",
)
CONFLICT_PRIORITY = (
    "BLOCKED",
    "VALIDATION_EXCLUSION_CANDIDATE",
    "REVIEW_REQUIRED",
    "CANONICAL_CANDIDATE",
    "KEEP",
)
OUTPUT_SCHEMA_FIELDS = ("instruction", "input", "output", "system", "metadata")
ALLOWED_OUTPUTS = (
    "train.jsonl",
    "validation.jsonl",
    "manifest.yaml",
    "statistics.json",
    "checksums.sha256",
    "processing-result.yaml",
)
FAIL_CLOSED_CODES = (
    "DATASET_IDENTITY_MISMATCH",
    "INPUT_RECORD_COUNT_MISMATCH",
    "INPUT_SCHEMA_MISMATCH",
    "JOIN_CONTRACT_MISMATCH",
    "UNKNOWN_RULE",
    "RULE_ORDER_MISMATCH",
    "RULE_CONFLICT",
    "UNKNOWN_ACTION",
    "INVALID_THRESHOLD",
    "OUTPUT_SCHEMA_MISMATCH",
    "OUTPUT_PATH_CONFLICT",
    "MISSING_APPROVAL",
    "APPROVAL_PERMISSION_ESCALATION",
    "TRAINING_SIZE_BELOW_MINIMUM",
    "VALIDATION_SIZE_BELOW_MINIMUM",
    "EXCLUSION_RATE_ABOVE_LIMIT",
    "UNKNOWN_POLICY_STATE",
)


class AIHub71748ManifestError(ValueError):
    """Manifest validation failed with a fixed, non-sensitive code."""


@dataclass(frozen=True)
class AIHub71748ManifestValidation:
    dataset_id: str
    component: str
    manifest_version: int
    rule_count: int
    processing_allowed: bool = False
    tokenization_allowed: bool = False
    training_allowed: bool = False
    execution_allowed: bool = False


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AIHub71748ManifestError(code)
    return value


def _sequence(value: object, code: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AIHub71748ManifestError(code)
    return tuple(value)


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], code: str) -> None:
    if set(value) != expected:
        raise AIHub71748ManifestError(code)


def _finite_number(value: object, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AIHub71748ManifestError(code)
    number = float(value)
    if not math.isfinite(number):
        raise AIHub71748ManifestError(code)
    return number


def _action_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    mapping = _mapping(value, "UNKNOWN_ACTION")
    if set(mapping) != {"Training", "Validation"}:
        raise AIHub71748ManifestError("UNKNOWN_ACTION")
    actions = tuple(mapping.values())
    if not all(isinstance(action, str) for action in actions):
        raise AIHub71748ManifestError("UNKNOWN_ACTION")
    return actions  # type: ignore[return-value]


def _validate_action_nodes(value: object) -> None:
    if not isinstance(value, Mapping):
        return
    for key, child in value.items():
        if key == "action":
            if any(action not in ALLOWED_ACTIONS for action in _action_values(child)):
                raise AIHub71748ManifestError("UNKNOWN_ACTION")
        elif isinstance(child, Mapping):
            _validate_action_nodes(child)


def _validate_identity(manifest: Mapping[str, object]) -> None:
    identity = _mapping(manifest.get("manifest_identity"), "DATASET_IDENTITY_MISMATCH")
    expected = {
        "manifest_type": MANIFEST_TYPE,
        "manifest_version": MANIFEST_VERSION,
        "provider": "AI_Hub",
        "dataset_id": DATASET_ID,
        "component": COMPONENT,
        "input_components": ["SFTdata", "SFTlabel"],
        "allowed_splits": ["Training", "Validation"],
        "source_selection_status": "CONDITIONALLY_SELECTED",
    }
    if dict(identity) != expected:
        raise AIHub71748ManifestError("DATASET_IDENTITY_MISMATCH")


def _validate_input_contract(manifest: Mapping[str, object]) -> None:
    contract = _mapping(manifest.get("input_contract"), "INPUT_SCHEMA_MISMATCH")
    records = _mapping(contract.get("records"), "INPUT_RECORD_COUNT_MISMATCH")
    if dict(records) != {"Training": 10580, "Validation": 1322, "Total": 11902}:
        raise AIHub71748ManifestError("INPUT_RECORD_COUNT_MISMATCH")
    if contract.get("join_key") != "data_id" or contract.get("join_relationship") != "one_to_one":
        raise AIHub71748ManifestError("JOIN_CONTRACT_MISMATCH")
    required = _mapping(contract.get("required_fields"), "INPUT_SCHEMA_MISMATCH")
    expected_required = {
        "SFTdata": [
            "data_id",
            "question",
            "question_count",
            "question_type",
            "data_category.middle",
        ],
        "SFTlabel": [
            "data_id",
            "question",
            "answer.contents",
            "answer.answer_count",
        ],
    }
    if dict(required) != expected_required:
        raise AIHub71748ManifestError("INPUT_SCHEMA_MISMATCH")
    consistency = _mapping(
        contract.get("component_question_consistency"),
        "JOIN_CONTRACT_MISMATCH",
    )
    if dict(consistency) != {"expected_matches": 11902, "expected_mismatches": 0}:
        raise AIHub71748ManifestError("JOIN_CONTRACT_MISMATCH")


def _validate_output_schema(manifest: Mapping[str, object]) -> None:
    schema = _mapping(manifest.get("output_schema"), "OUTPUT_SCHEMA_MISMATCH")
    if tuple(schema) != OUTPUT_SCHEMA_FIELDS:
        raise AIHub71748ManifestError("OUTPUT_SCHEMA_MISMATCH")
    instruction = _mapping(schema["instruction"], "OUTPUT_SCHEMA_MISMATCH")
    output = _mapping(schema["output"], "OUTPUT_SCHEMA_MISMATCH")
    input_field = _mapping(schema["input"], "OUTPUT_SCHEMA_MISMATCH")
    system = _mapping(schema["system"], "OUTPUT_SCHEMA_MISMATCH")
    metadata = _mapping(schema["metadata"], "OUTPUT_SCHEMA_MISMATCH")
    if dict(instruction) != {
        "source": "SFTdata.question",
        "type": "string",
        "required": True,
    }:
        raise AIHub71748ManifestError("OUTPUT_SCHEMA_MISMATCH")
    if dict(output) != {
        "source": "SFTlabel.answer.contents",
        "type": "string",
        "required": True,
    }:
        raise AIHub71748ManifestError("OUTPUT_SCHEMA_MISMATCH")
    nullable = {"value": None, "type": ["null", "string"], "required": False}
    if dict(input_field) != nullable or dict(system) != nullable:
        raise AIHub71748ManifestError("OUTPUT_SCHEMA_MISMATCH")
    if metadata.get("training_input") is not False:
        raise AIHub71748ManifestError("OUTPUT_SCHEMA_MISMATCH")
    fields = _mapping(metadata.get("fields"), "OUTPUT_SCHEMA_MISMATCH")
    expected_metadata = {
        "provider": {"value": "AI_Hub"},
        "dataset_id": {"value": DATASET_ID},
        "component": {"value": COMPONENT},
        "source_record_id": {"source": "data_id", "persistence": "internal_only"},
        "source_split": {"source": "archive_derived_split"},
        "question_type": {"source": "question_type"},
        "data_category": {"source": "data_category.middle"},
    }
    if dict(fields) != expected_metadata:
        raise AIHub71748ManifestError("OUTPUT_SCHEMA_MISMATCH")


def _validate_rules(manifest: Mapping[str, object]) -> None:
    order = _sequence(manifest.get("rule_order"), "RULE_ORDER_MISMATCH")
    if order != RULE_ORDER:
        raise AIHub71748ManifestError("RULE_ORDER_MISMATCH")
    rules = _mapping(manifest.get("processing_rules"), "UNKNOWN_RULE")
    if set(rules) != POLICY_RULES:
        raise AIHub71748ManifestError("UNKNOWN_RULE")
    for name, rule_value in rules.items():
        rule = _mapping(rule_value, "UNKNOWN_POLICY_STATE")
        if rule.get("enabled") is not True:
            raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")
        if name != "SCHEMA_MAPPING" and rule.get("status") != "approved_for_processing_manifest":
            raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")
    schema_mapping = _mapping(rules["SCHEMA_MAPPING"], "UNKNOWN_POLICY_STATE")
    if schema_mapping.get("action") != "map_to_sft_schema":
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")
    for name, rule in rules.items():
        if name != "SCHEMA_MAPPING":
            _validate_action_nodes(rule)
    _validate_action_nodes(
        _mapping(manifest.get("review_required_handling"), "UNKNOWN_POLICY_STATE")
    )

    pii = _mapping(rules["PII_POLICY"], "UNKNOWN_POLICY_STATE")
    expected_pii_actions = {
        "sensitive_topic_only": "KEEP",
        "single_direct_identifier": "REVIEW_REQUIRED",
        "multiple_direct_identifiers": "BLOCKED",
        "direct_identifier_with_sensitive_topic": "BLOCKED",
        "critical_candidate": "BLOCKED",
    }
    for key, expected_action in expected_pii_actions.items():
        policy = _mapping(pii.get(key), "UNKNOWN_POLICY_STATE")
        if policy.get("action") != expected_action:
            raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")
    sensitive = _mapping(pii["sensitive_topic_only"], "UNKNOWN_POLICY_STATE")
    if sensitive.get("condition") != "no_direct_identifier":
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")

    exact = _mapping(rules["EXACT_DUPLICATE_POLICY"], "UNKNOWN_POLICY_STATE")
    same_split = _mapping(exact.get("exact_qa_duplicate_same_split"), "UNKNOWN_POLICY_STATE")
    if same_split.get("action") != "CANONICAL_CANDIDATE" or same_split.get("canonical_order") != [
        "source_order",
        "first_record",
    ]:
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")
    if _mapping(exact.get("question_conflict"), "UNKNOWN_POLICY_STATE").get("action") != "BLOCKED":
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")
    if _mapping(exact.get("answer_reuse"), "UNKNOWN_POLICY_STATE").get("action") != "KEEP":
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")

    near = _mapping(rules["NEAR_DUPLICATE_POLICY"], "UNKNOWN_POLICY_STATE")
    same_near = _mapping(near.get("near_duplicate_same_split"), "UNKNOWN_POLICY_STATE")
    if _mapping(same_near.get("similarity_0_90_to_0_97"), "UNKNOWN_POLICY_STATE").get("action") != "KEEP":
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")
    if _mapping(same_near.get("similarity_0_97_to_1_00"), "UNKNOWN_POLICY_STATE").get("action") != "REVIEW_REQUIRED":
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")

    leakage = _mapping(rules["LEAKAGE_POLICY"], "UNKNOWN_POLICY_STATE")
    benchmark = _mapping(leakage.get("benchmark_contamination"), "UNKNOWN_POLICY_STATE")
    if dict(benchmark) != {
        "status": "blocked_not_available",
        "processing_effect": "no_record_action",
        "release_effect": "benchmark_validation_required_before_final_release",
    }:
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")

    allowed = _sequence(manifest.get("allowed_actions"), "UNKNOWN_ACTION")
    prohibited = _sequence(manifest.get("prohibited_actions"), "UNKNOWN_ACTION")
    if allowed != ALLOWED_ACTIONS or prohibited != PROHIBITED_ACTIONS:
        raise AIHub71748ManifestError("UNKNOWN_ACTION")

    conflict = _mapping(manifest.get("conflict_resolution"), "RULE_CONFLICT")
    if (
        conflict.get("strategy") != "most_restrictive_action"
        or tuple(_sequence(conflict.get("priority"), "RULE_CONFLICT")) != CONFLICT_PRIORITY
        or conflict.get("unknown_combination") != "fail_closed"
        or conflict.get("merge_candidate_allowed") is not False
    ):
        raise AIHub71748ManifestError("RULE_CONFLICT")


def _validate_thresholds(manifest: Mapping[str, object]) -> None:
    thresholds = _mapping(manifest.get("thresholds"), "INVALID_THRESHOLD")
    near = _mapping(thresholds.get("near_duplicate"), "INVALID_THRESHOLD")
    review_min = _finite_number(near.get("review_min"), "INVALID_THRESHOLD")
    high_min = _finite_number(near.get("high_similarity_min"), "INVALID_THRESHOLD")
    if review_min != 0.90 or high_min != 0.97 or not 0 <= review_min < high_min < 1:
        raise AIHub71748ManifestError("INVALID_THRESHOLD")
    if thresholds.get("critical_pii_maximum") != 0:
        raise AIHub71748ManifestError("INVALID_THRESHOLD")
    if thresholds.get("question_conflict_maximum_groups") != 0:
        raise AIHub71748ManifestError("INVALID_THRESHOLD")

    validation = _mapping(manifest.get("validation_policy"), "INVALID_THRESHOLD")
    expected_validation = {
        "remove_exact_cross_split_qa": True,
        "remove_normalized_cross_split_qa": True,
        "remove_high_similarity_cross_split_qa": True,
        "review_cross_split_question_near_duplicates": True,
        "answer_only_overlap": {"remove": False},
        "minimum_validation_records": 1000,
    }
    if dict(validation) != expected_validation:
        raise AIHub71748ManifestError("INVALID_THRESHOLD")
    expected = _mapping(manifest.get("expected_statistics"), "INVALID_THRESHOLD")
    if dict(_mapping(expected.get("input"), "INVALID_THRESHOLD")) != {
        "Training": 10580,
        "Validation": 1322,
        "Total": 11902,
    }:
        raise AIHub71748ManifestError("INVALID_THRESHOLD")
    output = _mapping(expected.get("output"), "INVALID_THRESHOLD")
    if output.get("exact_total") != "unknown_until_processing":
        raise AIHub71748ManifestError("INVALID_THRESHOLD")
    if output.get("minimum_training_records") != 10000:
        raise AIHub71748ManifestError("INVALID_THRESHOLD")
    if output.get("minimum_validation_records") != 1000:
        raise AIHub71748ManifestError("INVALID_THRESHOLD")
    rate = _finite_number(output.get("maximum_total_exclusion_rate"), "INVALID_THRESHOLD")
    if rate != 0.10 or not 0 <= rate <= 1:
        raise AIHub71748ManifestError("INVALID_THRESHOLD")


def _validate_paths_and_outputs(manifest: Mapping[str, object]) -> None:
    output = _mapping(manifest.get("output_contract"), "OUTPUT_PATH_CONFLICT")
    raw = output.get("raw_root")
    processed = output.get("processed_root")
    run = output.get("run_root")
    if not all(isinstance(value, str) and value for value in (raw, processed, run)):
        raise AIHub71748ManifestError("OUTPUT_PATH_CONFLICT")
    assert isinstance(raw, str) and isinstance(processed, str) and isinstance(run, str)
    expected = {
        "raw_root": "${DOHALM_DATASET_ROOT}/AIHUB-71748",
        "processed_root": "${DOHALM_DATASET_ROOT}/processed/instruct/AIHUB-71748",
        "run_root": "${DOHALM_DATASET_ROOT}/processed/instruct/AIHUB-71748/${PROCESSING_RUN_ID}",
        "overwrite_allowed": False,
        "run_id_reuse_allowed": False,
        "in_place_update_allowed": False,
    }
    if dict(output) != expected or len({raw, processed, run}) != 3:
        raise AIHub71748ManifestError("OUTPUT_PATH_CONFLICT")
    for path in (raw, processed, run):
        if PureWindowsPath(path).is_absolute() or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
            raise AIHub71748ManifestError("OUTPUT_PATH_CONFLICT")
    if _sequence(manifest.get("allowed_outputs"), "UNKNOWN_POLICY_STATE") != ALLOWED_OUTPUTS:
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")


def _validate_approval_and_status(manifest: Mapping[str, object]) -> None:
    approval = _mapping(manifest.get("processing_approval"), "MISSING_APPROVAL")
    expected_keys = frozenset(
        {
            "approval_id",
            "processing_run_id",
            "dataset_id",
            "component",
            "manifest_version",
            "manifest_sha256",
            "source_git_commit",
            "backend_git_commit",
            "approved_by",
            "approved_at",
            "maximum_runs",
            "retry_allowed",
            "resume_allowed",
            "overwrite_allowed",
            "processing_allowed",
            "tokenization_allowed",
            "training_allowed",
            "execution_allowed",
        }
    )
    _exact_keys(approval, expected_keys, "MISSING_APPROVAL")
    if approval.get("dataset_id") != DATASET_ID or approval.get("component") != COMPONENT:
        raise AIHub71748ManifestError("DATASET_IDENTITY_MISMATCH")
    if approval.get("manifest_version") != MANIFEST_VERSION or approval.get("maximum_runs") != 1:
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")
    nullable = (
        "approval_id",
        "processing_run_id",
        "manifest_sha256",
        "source_git_commit",
        "backend_git_commit",
        "approved_by",
        "approved_at",
    )
    if any(approval.get(key) is not None for key in nullable):
        raise AIHub71748ManifestError("APPROVAL_PERMISSION_ESCALATION")
    false_fields = (
        "retry_allowed",
        "resume_allowed",
        "overwrite_allowed",
        "processing_allowed",
        "tokenization_allowed",
        "training_allowed",
        "execution_allowed",
    )
    if any(approval.get(key) is not False for key in false_fields):
        raise AIHub71748ManifestError("APPROVAL_PERMISSION_ESCALATION")

    status = _mapping(manifest.get("status"), "UNKNOWN_POLICY_STATE")
    expected_status = {
        "processing_manifest": "completed",
        "rule_thresholds": "approved_for_processing_manifest",
        "processing_backend": "implemented",
        "processing_execution": "not_approved",
        "processed_dataset": "not_created",
        "tokenization": "not_started",
        "sft_backend": "not_started",
        "sft_training": "not_approved",
        "execution_allowed": False,
    }
    if dict(status) != expected_status:
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")
    if _sequence(manifest.get("fail_closed_error_codes"), "UNKNOWN_POLICY_STATE") != FAIL_CLOSED_CODES:
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")
    run_policy = _mapping(manifest.get("run_id_policy"), "UNKNOWN_POLICY_STATE")
    if dict(run_policy) != {
        "processing_run_id": "AIHUB-71748-SFT-PROCESSING-YYYYMMDD-NNNN",
        "approval_id": "AIHUB-71748-SFT-PROCESSING-APPROVAL-YYYYMMDD-NNNN",
        "single_use": True,
        "new_explicit_user_approval_required": True,
    }:
        raise AIHub71748ManifestError("UNKNOWN_POLICY_STATE")


def validate_aihub_71748_processing_manifest(
    manifest: Mapping[str, object],
) -> AIHub71748ManifestValidation:
    """Validate a non-executable manifest without reading Dataset or runtime files."""

    if not isinstance(manifest, Mapping):
        raise AIHub71748ManifestError("INVALID_MANIFEST")
    if "processing_approval" not in manifest:
        raise AIHub71748ManifestError("MISSING_APPROVAL")
    expected_top_level = frozenset(
        {
            "manifest_identity",
            "source_contract",
            "input_contract",
            "output_schema",
            "rule_order",
            "processing_rules",
            "validation_policy",
            "review_required_handling",
            "allowed_actions",
            "prohibited_actions",
            "conflict_resolution",
            "thresholds",
            "expected_statistics",
            "output_contract",
            "allowed_outputs",
            "processing_approval",
            "run_id_policy",
            "fail_closed_error_codes",
            "status",
        }
    )
    _exact_keys(manifest, expected_top_level, "INVALID_MANIFEST")
    _validate_identity(manifest)
    source = _mapping(manifest.get("source_contract"), "DATASET_IDENTITY_MISMATCH")
    if dict(source) != {
        "logical_root": "${DOHALM_DATASET_ROOT}/AIHUB-71748",
        "absolute_path_allowed": False,
        "dataset_read_required_for_validation": False,
    }:
        raise AIHub71748ManifestError("DATASET_IDENTITY_MISMATCH")
    _validate_input_contract(manifest)
    _validate_output_schema(manifest)
    _validate_rules(manifest)
    _validate_thresholds(manifest)
    _validate_paths_and_outputs(manifest)
    _validate_approval_and_status(manifest)
    return AIHub71748ManifestValidation(
        dataset_id=DATASET_ID,
        component=COMPONENT,
        manifest_version=MANIFEST_VERSION,
        rule_count=len(POLICY_RULES),
    )
