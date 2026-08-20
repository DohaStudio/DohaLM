"""Fail-closed adapter for the immutable Common Dataset contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as distribution_version
from typing import Any

from dohastudio_common_ai import (
    build_registry,
    contract_policy_version,
    get_schema,
    validate_contract,
    validate_scenario,
)

COMMON_CONTRACT_DISTRIBUTION = "dohastudio-common-ai-contracts"
COMMON_CONTRACT_PACKAGE_VERSION = "0.1.0"
COMMON_CONTRACT_POLICY_VERSION = "1.0.0"
COMMON_CONTRACT_AUTHORITY_COMMIT = "dd75fc88c16e9ae9a04acfafb72756a905f6365b"
LEARNING_CANDIDATE_SCHEMA_ID = (
    "https://schemas.dohastudio.org/common-ai/v1/learning-candidate.schema.json"
)
RIGHTS_METADATA_SCHEMA_ID = (
    "https://schemas.dohastudio.org/common-ai/v1/rights-metadata.schema.json"
)
TRAINING_ELIGIBILITY_SCHEMA_ID = (
    "https://schemas.dohastudio.org/common-ai/v1/training-eligibility.schema.json"
)
DATASET_VERSION_SCHEMA_ID = (
    "https://schemas.dohastudio.org/common-ai/v1/dataset-version.schema.json"
)
DATASET_MANIFEST_SCHEMA_ID = (
    "https://schemas.dohastudio.org/common-ai/v1/dataset-manifest.schema.json"
)

_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SAFE_PATH = re.compile(r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\])*$")
_RUNTIME_FAILURES = (LookupError, OSError, RuntimeError, TypeError, ValueError)


@dataclass(frozen=True, order=True)
class CommonContractIssue:
    """Non-sensitive projection of an authority validation issue."""

    code: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path}


class CommonContractRuntimeError(RuntimeError):
    """The pinned Common Contract runtime is absent or inconsistent."""

    code = "COMMON_CONTRACT_RUNTIME_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


class CommonDatasetValidationError(ValueError):
    """A Dataset object or publication scenario failed closed."""

    code = "COMMON_DATASET_CONTRACT_INVALID"

    def __init__(self, kind: str, issues: tuple[CommonContractIssue, ...]) -> None:
        self.kind = kind
        self.issues = issues
        issue_codes = ",".join(sorted({issue.code for issue in issues}))
        super().__init__(f"{self.code}:{kind}:{issue_codes}")


def verify_common_contract_runtime() -> None:
    """Verify the immutable package, policy, schemas, and offline registry."""

    try:
        if distribution_version(COMMON_CONTRACT_DISTRIBUTION) != (
            COMMON_CONTRACT_PACKAGE_VERSION
        ):
            raise CommonContractRuntimeError
        if contract_policy_version() != COMMON_CONTRACT_POLICY_VERSION:
            raise CommonContractRuntimeError
        expected_schema_ids = {
            "learning_candidate": LEARNING_CANDIDATE_SCHEMA_ID,
            "rights_metadata": RIGHTS_METADATA_SCHEMA_ID,
            "training_eligibility": TRAINING_ELIGIBILITY_SCHEMA_ID,
            "dataset_version": DATASET_VERSION_SCHEMA_ID,
            "dataset_manifest": DATASET_MANIFEST_SCHEMA_ID,
        }
        if any(
            get_schema(kind).get("$id") != schema_id
            for kind, schema_id in expected_schema_ids.items()
        ):
            raise CommonContractRuntimeError
        build_registry()
    except CommonContractRuntimeError:
        raise
    except (PackageNotFoundError, *_RUNTIME_FAILURES) as exc:
        raise CommonContractRuntimeError from exc


def validate_dataset_version(payload: Any) -> Any:
    """Return the unchanged DatasetVersion only when authority validation passes."""

    return _validate_object(payload, "dataset_version")


def validate_learning_candidate(payload: Any) -> Any:
    """Return the unchanged LearningCandidate after authority validation."""

    return _validate_object(payload, "learning_candidate")


def validate_rights_metadata(payload: Any) -> Any:
    """Return the unchanged RightsMetadata after authority validation."""

    return _validate_object(payload, "rights_metadata")


def validate_training_eligibility(payload: Any) -> Any:
    """Return the unchanged TrainingEligibility after authority validation."""

    return _validate_object(payload, "training_eligibility")


def validate_dataset_manifest(payload: Any) -> Any:
    """Return the unchanged DatasetManifest only when authority validation passes."""

    return _validate_object(payload, "dataset_manifest")


def validate_dataset_publication_scenario(scenario: Any) -> Any:
    """Validate the frozen Version + issued Manifest boundary as one scenario."""

    verify_common_contract_runtime()
    try:
        issues = validate_scenario(scenario)
    except _RUNTIME_FAILURES as exc:
        raise CommonContractRuntimeError from exc
    _raise_for_issues("dataset_publication_scenario", issues)
    return scenario


def _validate_object(payload: Any, kind: str) -> Any:
    verify_common_contract_runtime()
    try:
        issues = validate_contract(payload, expected_kind=kind)
    except _RUNTIME_FAILURES as exc:
        raise CommonContractRuntimeError from exc
    _raise_for_issues(kind, issues)
    return payload


def _raise_for_issues(kind: str, authority_issues: Any) -> None:
    issues = tuple(_project_issue(issue) for issue in authority_issues)
    if issues:
        raise CommonDatasetValidationError(kind, issues)


def _project_issue(issue: Any) -> CommonContractIssue:
    code = issue.code if isinstance(issue.code, str) else ""
    path = issue.path if isinstance(issue.path, str) else ""
    return CommonContractIssue(
        code=code if _SAFE_CODE.fullmatch(code) else "COMMON_CONTRACT_VALIDATION_ERROR",
        path=path if _SAFE_PATH.fullmatch(path) else "$",
    )


__all__ = [
    "COMMON_CONTRACT_DISTRIBUTION",
    "COMMON_CONTRACT_AUTHORITY_COMMIT",
    "COMMON_CONTRACT_PACKAGE_VERSION",
    "COMMON_CONTRACT_POLICY_VERSION",
    "CommonContractIssue",
    "CommonContractRuntimeError",
    "CommonDatasetValidationError",
    "DATASET_MANIFEST_SCHEMA_ID",
    "DATASET_VERSION_SCHEMA_ID",
    "LEARNING_CANDIDATE_SCHEMA_ID",
    "RIGHTS_METADATA_SCHEMA_ID",
    "TRAINING_ELIGIBILITY_SCHEMA_ID",
    "validate_dataset_manifest",
    "validate_dataset_publication_scenario",
    "validate_dataset_version",
    "validate_learning_candidate",
    "validate_rights_metadata",
    "validate_training_eligibility",
    "verify_common_contract_runtime",
]
