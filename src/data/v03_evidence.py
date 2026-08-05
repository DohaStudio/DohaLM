"""Strict, payload-free contracts for General Instruct v0.3 evidence bundles."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence


V03_EVIDENCE_SCHEMA_VERSION = 1
MAX_V03_EVIDENCE_BYTES = 1024 * 1024

ARTIFACT_FILENAMES: Mapping[str, str] = MappingProxyType(
    {
        "license_evidence": "license-evidence.json",
        "dataset_lineage": "dataset-lineage.json",
        "checksum_inventory": "checksum-inventory.json",
        "pii_scan_summary": "pii-scan-summary.json",
        "pii_review_evidence": "pii-review-evidence.json",
        "safety_scan_summary": "safety-scan-summary.json",
        "safety_review_evidence": "safety-review-evidence.json",
        "leakage_scan_summary": "leakage-scan-summary.json",
        "evaluation_exclusion_manifest": "evaluation-exclusion-manifest.json",
        "readiness_decision": "readiness-decision.json",
    }
)

_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_type",
        "artifact_id",
        "run_id",
        "dataset_id",
        "source_commit",
        "created_at",
        "writer_name",
        "writer_version",
        "input_fingerprint",
        "output_fingerprint",
        "payload",
        "approval_status",
        "reviewer",
        "decision",
        "predecessor_artifact_id",
        "artifact_checksum",
    }
)
_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_UTC_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,127}\Z")
_OPAQUE_REFERENCE = re.compile(r"hmac-sha256:[0-9a-f]{64}\Z")

_APPROVAL_STATUSES = frozenset({"not_approved", "reviewed", "approved"})
_STANDARD_DECISIONS = frozenset({"passed", "blocked", "evidence_insufficient"})
_LICENSE_DECISIONS = frozenset(
    {"ready", "ready_with_conditions", "blocked", "evidence_insufficient"}
)
_OVERALL_DECISIONS = frozenset(
    {"ready", "ready_with_conditions", "blocked", "evidence_insufficient"}
)
_SEVERITIES = ("critical", "high", "medium", "low")
_PII_CATEGORIES = (
    "resident_id",
    "phone",
    "email",
    "address",
    "financial_identifier",
    "name_organization",
    "user_id",
    "url_identifier",
    "sensitive_narrative",
    "source_reconstruction",
)
_SAFETY_CATEGORIES = (
    "self_harm",
    "violence",
    "sexual_content",
    "hate_harassment",
    "illegal_activity",
    "privacy",
    "high_risk_advice",
    "child_sensitive",
    "prompt_injection",
    "evaluation_contamination",
)
_LICENSE_STATUSES = frozenset(
    {
        "approved",
        "conditionally_supported",
        "evidence_missing",
        "evidence_insufficient",
        "not_approved",
        "prohibited_by_project_policy",
        "verification_required",
        "new_purpose_approval_required",
        "new_provider_or_legal_approval_required",
    }
)
_APPROVED_ACTIONS = frozenset(
    {"v03_r2_evidence_review", "v03_r3_identity_design", "fresh_tokenization_preflight"}
)
_PROHIBITED_ACTIONS = frozenset(
    {
        "dataset_payload_read",
        "tokenization",
        "approval_issue",
        "run_reservation",
        "training",
        "gpu_execution",
        "v03_r2_evidence_review",
        "v03_r3_identity_design",
        "fresh_tokenization_preflight",
    }
)
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "absolute_path",
        "content",
        "local_path",
        "match",
        "match_substring",
        "path",
        "preview",
        "raw_payload",
        "raw_text",
        "source_path",
        "text",
    }
)


class V03EvidenceError(RuntimeError):
    """Fail-closed error whose string representation contains only a safe code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _error(code: str = "V03_EVIDENCE_INVALID") -> V03EvidenceError:
    return V03EvidenceError(code)


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class V03EvidenceArtifact:
    schema_version: int
    artifact_type: str
    artifact_id: str
    run_id: str
    dataset_id: str
    source_commit: str
    created_at: str
    writer_name: str
    writer_version: str
    input_fingerprint: str
    output_fingerprint: str
    payload: Mapping[str, Any]
    approval_status: str
    reviewer: str | None
    decision: str
    predecessor_artifact_id: str | None
    artifact_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze(_thaw(self.payload)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "dataset_id": self.dataset_id,
            "source_commit": self.source_commit,
            "created_at": self.created_at,
            "writer_name": self.writer_name,
            "writer_version": self.writer_version,
            "input_fingerprint": self.input_fingerprint,
            "output_fingerprint": self.output_fingerprint,
            "payload": _thaw(self.payload),
            "approval_status": self.approval_status,
            "reviewer": self.reviewer,
            "decision": self.decision,
            "predecessor_artifact_id": self.predecessor_artifact_id,
            "artifact_checksum": self.artifact_checksum,
        }


@dataclass(frozen=True)
class V03EvidenceBundleResult:
    schema_version: int
    run_id: str
    dataset_id: str
    overall_decision: str
    evidence_bundle_fingerprint: str
    readiness_artifact_checksum: str
    artifact_checksums: tuple[tuple[str, str], ...]


def canonical_v03_json_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 JSON without a trailing newline."""
    try:
        return json.dumps(
            _thaw(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise _error() from None


def v03_fingerprint(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_v03_json_bytes(value)).hexdigest()}"


def _strict_object(value: object, fields: Sequence[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(fields):
        raise _error()
    return value


def _string(value: object, *, identifier: bool = False) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise _error()
    if "\x00" in value or "\n" in value or "\r" in value:
        raise _error()
    if identifier and _IDENTIFIER.fullmatch(value) is None:
        raise _error()
    return value


def _optional_identifier(value: object) -> str | None:
    if value is None:
        return None
    return _string(value, identifier=True)


def _enum(value: object, allowed: frozenset[str]) -> str:
    candidate = _string(value)
    if candidate not in allowed:
        raise _error()
    return candidate


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise _error()
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise _error()
    return value


def _fingerprint(value: object) -> str:
    candidate = _string(value)
    if _FINGERPRINT.fullmatch(candidate) is None:
        raise _error()
    return candidate


def _timestamp(value: object) -> str:
    candidate = _string(value)
    if _UTC_Z.fullmatch(candidate) is None:
        raise _error()
    try:
        parsed = datetime.fromisoformat(candidate[:-1] + "+00:00")
    except ValueError:
        raise _error() from None
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise _error()
    return candidate


def _reason_codes(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise _error()
    result = tuple(_string(item) for item in value)
    if len(result) != len(set(result)) or any(
        _REASON_CODE.fullmatch(item) is None for item in result
    ):
        raise _error()
    return result


def _enum_list(
    value: object, allowed: frozenset[str], *, nonempty: bool = False
) -> tuple[str, ...]:
    if type(value) is not list:
        raise _error()
    result = tuple(_enum(item, allowed) for item in value)
    if (nonempty and not result) or len(result) != len(set(result)):
        raise _error()
    return result


def _count_map(value: object, keys: Sequence[str]) -> dict[str, int]:
    item = _strict_object(value, keys)
    return {key: _integer(item[key]) for key in keys}


def _reason_count_map(value: object) -> dict[str, int]:
    if type(value) is not dict:
        raise _error()
    result: dict[str, int] = {}
    for key, count in value.items():
        if type(key) is not str or _REASON_CODE.fullmatch(key) is None:
            raise _error()
        result[key] = _integer(count)
    return result


def _safe_payload(value: Any, *, key: str | None = None) -> None:
    if key in _FORBIDDEN_PAYLOAD_KEYS:
        raise _error(
            "V03_EVIDENCE_PATH_INVALID" if "path" in key else "V03_EVIDENCE_INVALID"
        )
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            if type(child_key) is not str:
                raise _error()
            _safe_payload(child, key=child_key)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _safe_payload(child, key=key)
    elif type(value) is str:
        if "\x00" in value or "\n" in value or "\r" in value:
            raise _error()
        windows = PureWindowsPath(value)
        posix = PurePosixPath(value)
        if (
            windows.is_absolute()
            or bool(windows.drive)
            or posix.is_absolute()
            or ".." in posix.parts
        ):
            raise _error("V03_EVIDENCE_PATH_INVALID")


def _relative_artifact_name(value: object) -> str:
    text = _string(value)
    posix, windows = PurePosixPath(text), PureWindowsPath(text)
    if (
        "\\" in text
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or not posix.parts
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise _error("V03_EVIDENCE_PATH_INVALID")
    return text


def calculate_inventory_fingerprint(entries: Sequence[Mapping[str, Any]]) -> str:
    return v03_fingerprint({"algorithm": "sha256", "entries": list(entries)})


def calculate_exclusion_fingerprint(
    *,
    canonical_dataset_fingerprint: str,
    exclusion_reason_counts: Mapping[str, int],
    opaque_record_references: Sequence[str],
) -> str:
    return v03_fingerprint(
        {
            "canonical_dataset_fingerprint": canonical_dataset_fingerprint,
            "exclusion_reason_counts": dict(exclusion_reason_counts),
            "opaque_record_references": list(opaque_record_references),
        }
    )


def calculate_effective_dataset_fingerprint(
    *,
    canonical_dataset_fingerprint: str,
    evaluation_exclusion_fingerprint: str,
) -> str:
    return v03_fingerprint(
        {
            "canonical_dataset_fingerprint": canonical_dataset_fingerprint,
            "evaluation_exclusion_fingerprint": evaluation_exclusion_fingerprint,
        }
    )


def _validate_license(payload: object) -> dict[str, Any]:
    fields = (
        "provider",
        "dataset_component",
        "permitted_purpose",
        "student_noncommercial",
        "sft_use_status",
        "derivative_dataset_status",
        "adapter_creation_status",
        "redistribution_status",
        "checkpoint_publication_status",
        "external_service_status",
        "cloud_status",
        "music_reuse_status",
        "commercial_transition_status",
        "evidence_references",
        "unresolved_questions",
        "decision",
    )
    item = _strict_object(payload, fields)
    _string(item["provider"], identifier=True)
    _enum(item["dataset_component"], frozenset({"sft"}))
    _enum_list(
        item["permitted_purpose"],
        frozenset(
            {"local_student_noncommercial_research", "synthetic_contract_testing"}
        ),
        nonempty=True,
    )
    _boolean(item["student_noncommercial"])
    for field in fields[4:13]:
        _enum(item[field], _LICENSE_STATUSES)
    if type(item["evidence_references"]) is not list:
        raise _error()
    for reference in item["evidence_references"]:
        _string(reference)
    _reason_codes(item["unresolved_questions"])
    _enum(item["decision"], _LICENSE_DECISIONS)
    return item


def _validate_lineage(payload: object) -> dict[str, Any]:
    fields = (
        "source_dataset_id",
        "derived_dataset_id",
        "processing_run_ids",
        "source_record_count",
        "train_record_count",
        "validation_record_count",
        "exclusion_count",
        "canonical_dataset_fingerprint",
        "effective_dataset_fingerprint",
        "split_fingerprint",
        "source_checksums",
        "derivation_method",
        "predecessor_run_id",
    )
    item = _strict_object(payload, fields)
    _string(item["source_dataset_id"], identifier=True)
    _string(item["derived_dataset_id"], identifier=True)
    if type(item["processing_run_ids"]) is not list or not item["processing_run_ids"]:
        raise _error()
    for run_id in item["processing_run_ids"]:
        _string(run_id, identifier=True)
    for field in fields[3:7]:
        _integer(item[field])
    for field in fields[7:10]:
        _fingerprint(item[field])
    if type(item["source_checksums"]) is not dict or not item["source_checksums"]:
        raise _error()
    for logical_name, checksum in item["source_checksums"].items():
        _string(logical_name, identifier=True)
        _fingerprint(checksum)
    _enum(
        item["derivation_method"],
        frozenset({"read_only_versioned_derivation", "synthetic"}),
    )
    _optional_identifier(item["predecessor_run_id"])
    return item


def _validate_inventory(payload: object) -> dict[str, Any]:
    item = _strict_object(payload, ("algorithm", "entries", "inventory_fingerprint"))
    if (
        item["algorithm"] != "sha256"
        or type(item["entries"]) is not list
        or not item["entries"]
    ):
        raise _error()
    names: set[str] = set()
    relative_names: set[str] = set()
    for raw in item["entries"]:
        entry = _strict_object(
            raw,
            (
                "logical_name",
                "relative_artifact_name",
                "checksum",
                "size_bytes",
                "status",
            ),
        )
        logical_name = _string(entry["logical_name"], identifier=True)
        relative_name = _relative_artifact_name(entry["relative_artifact_name"])
        _fingerprint(entry["checksum"])
        _integer(entry["size_bytes"])
        _enum(entry["status"], frozenset({"verified", "missing", "mismatch"}))
        if logical_name in names or relative_name in relative_names:
            raise _error()
        names.add(logical_name)
        relative_names.add(relative_name)
    if _fingerprint(item["inventory_fingerprint"]) != calculate_inventory_fingerprint(
        item["entries"]
    ):
        raise _error("V03_EVIDENCE_CHECKSUM_MISMATCH")
    return item


def _validate_pii_scan(payload: object) -> dict[str, Any]:
    fields = (
        "scanner_version",
        "input_dataset_fingerprint",
        "scanned_record_count",
        "finding_count_by_category",
        "finding_count_by_severity",
        "unresolved_count",
        "excluded_count",
        "retained_with_review_count",
        "findings_fingerprint",
        "scan_decision",
    )
    item = _strict_object(payload, fields)
    _string(item["scanner_version"], identifier=True)
    _fingerprint(item["input_dataset_fingerprint"])
    _integer(item["scanned_record_count"])
    _count_map(item["finding_count_by_category"], _PII_CATEGORIES)
    _count_map(item["finding_count_by_severity"], _SEVERITIES)
    for field in fields[5:8]:
        _integer(item[field])
    _fingerprint(item["findings_fingerprint"])
    _enum(item["scan_decision"], _STANDARD_DECISIONS)
    return item


def _validate_pii_review(payload: object) -> dict[str, Any]:
    fields = (
        "reviewed_finding_count",
        "unresolved_count",
        "critical_unresolved",
        "high_unresolved",
        "medium_retained_count",
        "reviewer_ids",
        "reason_code_counts",
        "review_fingerprint",
        "review_decision",
    )
    item = _strict_object(payload, fields)
    for field in fields[:5]:
        _integer(item[field])
    if type(item["reviewer_ids"]) is not list or not item["reviewer_ids"]:
        raise _error()
    reviewers = tuple(_string(value, identifier=True) for value in item["reviewer_ids"])
    if len(reviewers) != len(set(reviewers)):
        raise _error()
    _reason_count_map(item["reason_code_counts"])
    _fingerprint(item["review_fingerprint"])
    _enum(item["review_decision"], _STANDARD_DECISIONS)
    return item


def _validate_safety_scan(payload: object) -> dict[str, Any]:
    fields = (
        "category_counts",
        "severity_counts",
        "unresolved_count",
        "excluded_count",
        "retained_with_review_count",
        "findings_fingerprint",
        "scan_decision",
    )
    item = _strict_object(payload, fields)
    _count_map(item["category_counts"], _SAFETY_CATEGORIES)
    _count_map(item["severity_counts"], _SEVERITIES)
    for field in fields[2:5]:
        _integer(item[field])
    _fingerprint(item["findings_fingerprint"])
    _enum(item["scan_decision"], _STANDARD_DECISIONS)
    return item


def _validate_safety_review(payload: object) -> dict[str, Any]:
    fields = (
        "reviewed_finding_count",
        "critical_retained_count",
        "high_retained_count",
        "medium_retained_count",
        "unresolved_count",
        "reviewer_ids",
        "reason_code_counts",
        "review_fingerprint",
        "review_decision",
    )
    item = _strict_object(payload, fields)
    for field in fields[:5]:
        _integer(item[field])
    if type(item["reviewer_ids"]) is not list or not item["reviewer_ids"]:
        raise _error()
    for reviewer in item["reviewer_ids"]:
        _string(reviewer, identifier=True)
    _reason_count_map(item["reason_code_counts"])
    _fingerprint(item["review_fingerprint"])
    _enum(item["review_decision"], _STANDARD_DECISIONS)
    return item


def _validate_leakage(payload: object) -> dict[str, Any]:
    fields = (
        "benchmark_identity",
        "benchmark_version",
        "benchmark_fingerprint",
        "exact_duplicate_count",
        "normalized_duplicate_count",
        "near_duplicate_count",
        "prompt_overlap_count",
        "answer_overlap_count",
        "template_contamination_count",
        "train_validation_overlap_count",
        "prior_evaluation_overlap_count",
        "unresolved_count",
        "exclusion_count",
        "findings_fingerprint",
        "scan_decision",
    )
    item = _strict_object(payload, fields)
    _string(item["benchmark_identity"], identifier=True)
    _string(item["benchmark_version"], identifier=True)
    _fingerprint(item["benchmark_fingerprint"])
    for field in fields[3:13]:
        _integer(item[field])
    _fingerprint(item["findings_fingerprint"])
    _enum(item["scan_decision"], _STANDARD_DECISIONS)
    return item


def _validate_exclusion(payload: object) -> dict[str, Any]:
    fields = (
        "exclusion_schema_version",
        "canonical_dataset_fingerprint",
        "excluded_record_count",
        "exclusion_reason_counts",
        "opaque_record_references",
        "exclusion_fingerprint",
        "effective_dataset_fingerprint",
    )
    item = _strict_object(payload, fields)
    if (
        type(item["exclusion_schema_version"]) is not int
        or item["exclusion_schema_version"] != 1
    ):
        raise _error()
    canonical = _fingerprint(item["canonical_dataset_fingerprint"])
    count = _integer(item["excluded_record_count"])
    reasons = _reason_count_map(item["exclusion_reason_counts"])
    if type(item["opaque_record_references"]) is not list:
        raise _error()
    references = tuple(_string(value) for value in item["opaque_record_references"])
    if len(references) != len(set(references)) or any(
        _OPAQUE_REFERENCE.fullmatch(value) is None for value in references
    ):
        raise _error()
    if count != len(references) or count != sum(reasons.values()):
        raise _error()
    expected = calculate_exclusion_fingerprint(
        canonical_dataset_fingerprint=canonical,
        exclusion_reason_counts=reasons,
        opaque_record_references=references,
    )
    if _fingerprint(item["exclusion_fingerprint"]) != expected:
        raise _error("V03_EVIDENCE_CHECKSUM_MISMATCH")
    _fingerprint(item["effective_dataset_fingerprint"])
    return item


def _validate_readiness(payload: object) -> dict[str, Any]:
    fields = (
        "license_decision",
        "lineage_decision",
        "checksum_decision",
        "pii_decision",
        "safety_decision",
        "leakage_decision",
        "effective_dataset_decision",
        "overall_decision",
        "blocking_reasons",
        "conditional_reasons",
        "approved_next_actions",
        "prohibited_actions",
        "evidence_bundle_fingerprint",
    )
    item = _strict_object(payload, fields)
    _enum(item["license_decision"], _LICENSE_DECISIONS)
    for field in fields[1:7]:
        _enum(item[field], _STANDARD_DECISIONS)
    _enum(item["overall_decision"], _OVERALL_DECISIONS)
    _reason_codes(item["blocking_reasons"])
    _reason_codes(item["conditional_reasons"])
    approved = _enum_list(item["approved_next_actions"], _APPROVED_ACTIONS)
    prohibited = _enum_list(item["prohibited_actions"], _PROHIBITED_ACTIONS)
    if set(approved) & set(prohibited):
        raise _error("V03_EVIDENCE_READINESS_CONTRADICTION")
    _fingerprint(item["evidence_bundle_fingerprint"])
    return item


_PAYLOAD_VALIDATORS = {
    "license_evidence": _validate_license,
    "dataset_lineage": _validate_lineage,
    "checksum_inventory": _validate_inventory,
    "pii_scan_summary": _validate_pii_scan,
    "pii_review_evidence": _validate_pii_review,
    "safety_scan_summary": _validate_safety_scan,
    "safety_review_evidence": _validate_safety_review,
    "leakage_scan_summary": _validate_leakage,
    "evaluation_exclusion_manifest": _validate_exclusion,
    "readiness_decision": _validate_readiness,
}


def _validate_artifact_value(value: object) -> V03EvidenceArtifact:
    item = _strict_object(value, _TOP_LEVEL_FIELDS)
    version = item["schema_version"]
    if type(version) is not int:
        raise _error()
    if version != V03_EVIDENCE_SCHEMA_VERSION:
        raise _error("V03_EVIDENCE_UNSUPPORTED_VERSION")
    artifact_type = _string(item["artifact_type"])
    if artifact_type not in ARTIFACT_FILENAMES:
        raise _error()
    artifact_id = _string(item["artifact_id"], identifier=True)
    run_id = _string(item["run_id"], identifier=True)
    dataset_id = _string(item["dataset_id"], identifier=True)
    source_commit = _string(item["source_commit"])
    if _GIT_SHA.fullmatch(source_commit) is None:
        raise _error()
    created_at = _timestamp(item["created_at"])
    writer_name = _string(item["writer_name"], identifier=True)
    writer_version = _string(item["writer_version"], identifier=True)
    input_fingerprint = _fingerprint(item["input_fingerprint"])
    output_fingerprint = _fingerprint(item["output_fingerprint"])
    payload = _PAYLOAD_VALIDATORS[artifact_type](item["payload"])
    _safe_payload(payload)
    approval_status = _enum(item["approval_status"], _APPROVAL_STATUSES)
    reviewer = _optional_identifier(item["reviewer"])
    if approval_status in {"reviewed", "approved"} and reviewer is None:
        raise _error()
    if (
        artifact_type
        in {"pii_review_evidence", "safety_review_evidence", "readiness_decision"}
        and reviewer is None
    ):
        raise _error()
    decision = _string(item["decision"])
    predecessor = _optional_identifier(item["predecessor_artifact_id"])
    checksum = _fingerprint(item["artifact_checksum"])

    payload_decision_field = {
        "license_evidence": "decision",
        "pii_scan_summary": "scan_decision",
        "pii_review_evidence": "review_decision",
        "safety_scan_summary": "scan_decision",
        "safety_review_evidence": "review_decision",
        "leakage_scan_summary": "scan_decision",
        "readiness_decision": "overall_decision",
    }.get(artifact_type)
    allowed = (
        _LICENSE_DECISIONS
        if artifact_type == "license_evidence"
        else _STANDARD_DECISIONS
    )
    if artifact_type == "readiness_decision":
        allowed = _OVERALL_DECISIONS
    _enum(decision, allowed)
    if (
        payload_decision_field is not None
        and payload[payload_decision_field] != decision
    ):
        raise _error("V03_EVIDENCE_READINESS_CONTRADICTION")

    artifact = V03EvidenceArtifact(
        schema_version=version,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        run_id=run_id,
        dataset_id=dataset_id,
        source_commit=source_commit,
        created_at=created_at,
        writer_name=writer_name,
        writer_version=writer_version,
        input_fingerprint=input_fingerprint,
        output_fingerprint=output_fingerprint,
        payload=payload,
        approval_status=approval_status,
        reviewer=reviewer,
        decision=decision,
        predecessor_artifact_id=predecessor,
        artifact_checksum=checksum,
    )
    if artifact.output_fingerprint != v03_fingerprint(payload):
        raise _error("V03_EVIDENCE_CHECKSUM_MISMATCH")
    checksum_value = artifact.as_dict()
    checksum_value["artifact_checksum"] = ""
    if artifact.artifact_checksum != v03_fingerprint(checksum_value):
        raise _error("V03_EVIDENCE_CHECKSUM_MISMATCH")
    return artifact


def make_v03_evidence_artifact(
    *,
    artifact_type: str,
    artifact_id: str,
    run_id: str,
    dataset_id: str,
    source_commit: str,
    created_at: str,
    writer_name: str,
    writer_version: str,
    input_fingerprint: str,
    payload: Mapping[str, Any],
    approval_status: str,
    reviewer: str | None,
    decision: str,
    predecessor_artifact_id: str | None = None,
) -> V03EvidenceArtifact:
    """Create and fully validate an immutable evidence artifact."""
    value: dict[str, Any] = {
        "schema_version": V03_EVIDENCE_SCHEMA_VERSION,
        "artifact_type": artifact_type,
        "artifact_id": artifact_id,
        "run_id": run_id,
        "dataset_id": dataset_id,
        "source_commit": source_commit,
        "created_at": created_at,
        "writer_name": writer_name,
        "writer_version": writer_version,
        "input_fingerprint": input_fingerprint,
        "output_fingerprint": v03_fingerprint(payload),
        "payload": _thaw(payload),
        "approval_status": approval_status,
        "reviewer": reviewer,
        "decision": decision,
        "predecessor_artifact_id": predecessor_artifact_id,
        "artifact_checksum": "",
    }
    value["artifact_checksum"] = v03_fingerprint(value)
    return _validate_artifact_value(value)


def serialize_v03_evidence(artifact: V03EvidenceArtifact) -> bytes:
    if not isinstance(artifact, V03EvidenceArtifact):
        raise _error()
    validated = _validate_artifact_value(artifact.as_dict())
    return canonical_v03_json_bytes(validated.as_dict())


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _error()
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise _error()


def load_v03_evidence(path: Path) -> V03EvidenceArtifact:
    """Strictly load one explicitly supplied, canonical, non-symlink JSON file."""
    if not isinstance(path, Path):
        raise _error("V03_EVIDENCE_PATH_INVALID")
    try:
        if path.is_symlink():
            raise _error("V03_EVIDENCE_PATH_INVALID")
        if not path.exists():
            raise _error("V03_EVIDENCE_NOT_FOUND")
        if not path.is_file():
            raise _error("V03_EVIDENCE_PATH_INVALID")
        if path.stat().st_size > MAX_V03_EVIDENCE_BYTES:
            raise _error()
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except V03EvidenceError:
        raise
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ):
        raise _error() from None
    artifact = _validate_artifact_value(value)
    if raw != serialize_v03_evidence(artifact):
        raise _error()
    return artifact


def calculate_bundle_fingerprint(artifacts: Mapping[str, V03EvidenceArtifact]) -> str:
    """Fingerprint the nine predecessor artifacts; readiness is intentionally excluded."""
    expected = set(ARTIFACT_FILENAMES) - {"readiness_decision"}
    if set(artifacts) != expected:
        raise _error("V03_EVIDENCE_BUNDLE_INCOMPLETE")
    return v03_fingerprint(
        {
            artifact_type: artifacts[artifact_type].artifact_checksum
            for artifact_type in sorted(expected)
        }
    )


def _aggregate_decision(*decisions: str, coherent: bool) -> str:
    if "evidence_insufficient" in decisions:
        return "evidence_insufficient"
    if "blocked" in decisions or not coherent:
        return "blocked"
    return "passed"


def _validate_bundle_relationships(artifacts: Mapping[str, V03EvidenceArtifact]) -> str:
    lineage = artifacts["dataset_lineage"]
    canonical = lineage.payload["canonical_dataset_fingerprint"]
    effective = lineage.payload["effective_dataset_fingerprint"]
    if lineage.payload["derived_dataset_id"] != lineage.dataset_id:
        raise _error("V03_EVIDENCE_BUNDLE_INCONSISTENT")
    for artifact_type in (
        "license_evidence",
        "dataset_lineage",
        "checksum_inventory",
        "pii_scan_summary",
        "safety_scan_summary",
        "leakage_scan_summary",
        "evaluation_exclusion_manifest",
    ):
        if artifacts[artifact_type].input_fingerprint != canonical:
            raise _error("V03_EVIDENCE_BUNDLE_INCONSISTENT")

    pii_scan = artifacts["pii_scan_summary"]
    pii_review = artifacts["pii_review_evidence"]
    safety_scan = artifacts["safety_scan_summary"]
    safety_review = artifacts["safety_review_evidence"]
    exclusion = artifacts["evaluation_exclusion_manifest"]
    if (
        pii_scan.payload["input_dataset_fingerprint"] != canonical
        or safety_scan.input_fingerprint != canonical
        or pii_review.input_fingerprint != pii_scan.payload["findings_fingerprint"]
        or safety_review.input_fingerprint
        != safety_scan.payload["findings_fingerprint"]
        or exclusion.payload["canonical_dataset_fingerprint"] != canonical
    ):
        raise _error("V03_EVIDENCE_BUNDLE_INCONSISTENT")
    expected_effective = calculate_effective_dataset_fingerprint(
        canonical_dataset_fingerprint=canonical,
        evaluation_exclusion_fingerprint=exclusion.payload["exclusion_fingerprint"],
    )
    if (
        effective != expected_effective
        or exclusion.payload["effective_dataset_fingerprint"] != effective
    ):
        raise _error("V03_EVIDENCE_BUNDLE_INCONSISTENT")

    readiness = artifacts["readiness_decision"]
    predecessor = {
        key: value for key, value in artifacts.items() if key != "readiness_decision"
    }
    bundle_fingerprint = calculate_bundle_fingerprint(predecessor)
    if (
        readiness.input_fingerprint != bundle_fingerprint
        or readiness.payload["evidence_bundle_fingerprint"] != bundle_fingerprint
    ):
        raise _error("V03_EVIDENCE_BUNDLE_INCONSISTENT")

    inventory = artifacts["checksum_inventory"].payload
    checksum_coherent = all(
        entry["status"] == "verified" for entry in inventory["entries"]
    )
    pii_coherent = (
        pii_scan.payload["unresolved_count"] == 0
        and pii_scan.payload["excluded_count"] == 0
        and pii_review.payload["unresolved_count"] == 0
        and pii_review.payload["critical_unresolved"] == 0
        and pii_review.payload["high_unresolved"] == 0
    )
    safety_coherent = (
        safety_scan.payload["unresolved_count"] == 0
        and safety_scan.payload["excluded_count"] == 0
        and safety_review.payload["unresolved_count"] == 0
        and safety_review.payload["critical_retained_count"] == 0
    )
    leakage_coherent = (
        artifacts["leakage_scan_summary"].payload["unresolved_count"] == 0
    )

    expected_components = {
        "license_decision": artifacts["license_evidence"].decision,
        "lineage_decision": artifacts["dataset_lineage"].decision,
        "checksum_decision": _aggregate_decision(
            artifacts["checksum_inventory"].decision, coherent=checksum_coherent
        ),
        "pii_decision": _aggregate_decision(
            pii_scan.decision, pii_review.decision, coherent=pii_coherent
        ),
        "safety_decision": _aggregate_decision(
            safety_scan.decision, safety_review.decision, coherent=safety_coherent
        ),
        "leakage_decision": _aggregate_decision(
            artifacts["leakage_scan_summary"].decision, coherent=leakage_coherent
        ),
        "effective_dataset_decision": "passed",
    }
    for field, expected in expected_components.items():
        if readiness.payload[field] != expected:
            raise _error("V03_EVIDENCE_READINESS_CONTRADICTION")

    component_values = tuple(expected_components.values())
    license_decision = expected_components["license_decision"]
    if "evidence_insufficient" in component_values:
        expected_overall = "evidence_insufficient"
    elif "blocked" in component_values:
        expected_overall = "blocked"
    elif license_decision == "ready_with_conditions":
        expected_overall = "ready_with_conditions"
    elif license_decision == "ready":
        expected_overall = "ready"
    else:
        expected_overall = license_decision
    if readiness.decision != expected_overall:
        raise _error("V03_EVIDENCE_READINESS_CONTRADICTION")

    blocking = readiness.payload["blocking_reasons"]
    conditional = readiness.payload["conditional_reasons"]
    approved = readiness.payload["approved_next_actions"]
    if expected_overall in {"blocked", "evidence_insufficient"}:
        if not blocking or conditional or approved:
            raise _error("V03_EVIDENCE_READINESS_CONTRADICTION")
    elif expected_overall == "ready":
        if blocking or conditional:
            raise _error("V03_EVIDENCE_READINESS_CONTRADICTION")
    elif not conditional or blocking:
        raise _error("V03_EVIDENCE_READINESS_CONTRADICTION")
    return bundle_fingerprint


def finalize_v03_evidence_bundle(
    *,
    bundle_root: Path,
    expected_run_id: str,
    expected_dataset_id: str,
) -> V03EvidenceBundleResult:
    """Validate an explicitly named, complete bundle without writing or scanning data."""
    if not isinstance(bundle_root, Path):
        raise _error("V03_EVIDENCE_PATH_INVALID")
    _string(expected_run_id, identifier=True)
    _string(expected_dataset_id, identifier=True)
    try:
        if bundle_root.is_symlink() or not bundle_root.is_dir():
            raise _error("V03_EVIDENCE_PATH_INVALID")
        entries = tuple(bundle_root.iterdir())
    except V03EvidenceError:
        raise
    except OSError:
        raise _error("V03_EVIDENCE_PATH_INVALID") from None
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise _error("V03_EVIDENCE_PATH_INVALID")
    expected_names = set(ARTIFACT_FILENAMES.values())
    if {entry.name for entry in entries} != expected_names:
        raise _error("V03_EVIDENCE_BUNDLE_INCOMPLETE")

    artifacts: dict[str, V03EvidenceArtifact] = {}
    for expected_type, filename in ARTIFACT_FILENAMES.items():
        artifact = load_v03_evidence(bundle_root / filename)
        if (
            artifact.artifact_type in artifacts
            or artifact.artifact_type != expected_type
        ):
            raise _error("V03_EVIDENCE_BUNDLE_INCONSISTENT")
        artifacts[artifact.artifact_type] = artifact
    if any(
        artifact.run_id != expected_run_id or artifact.dataset_id != expected_dataset_id
        for artifact in artifacts.values()
    ):
        raise _error("V03_EVIDENCE_BUNDLE_INCONSISTENT")
    if len({artifact.source_commit for artifact in artifacts.values()}) != 1:
        raise _error("V03_EVIDENCE_BUNDLE_INCONSISTENT")
    if len({artifact.artifact_id for artifact in artifacts.values()}) != len(artifacts):
        raise _error("V03_EVIDENCE_BUNDLE_INCONSISTENT")

    bundle_fingerprint = _validate_bundle_relationships(artifacts)
    readiness = artifacts["readiness_decision"]
    return V03EvidenceBundleResult(
        schema_version=V03_EVIDENCE_SCHEMA_VERSION,
        run_id=expected_run_id,
        dataset_id=expected_dataset_id,
        overall_decision=readiness.decision,
        evidence_bundle_fingerprint=bundle_fingerprint,
        readiness_artifact_checksum=readiness.artifact_checksum,
        artifact_checksums=tuple(
            (artifact_type, artifacts[artifact_type].artifact_checksum)
            for artifact_type in sorted(artifacts)
        ),
    )
