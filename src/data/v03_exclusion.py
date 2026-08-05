"""V03-R2 exclusion view and V03-R1 payload adapter contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from .v03_evidence import (
    calculate_effective_dataset_fingerprint,
    calculate_exclusion_fingerprint,
)
from .v03_review import ReviewPolicy, ReviewResult
from .v03_scanning import PII_CATEGORIES, SAFETY_CATEGORIES, ScannerResult


class V03ExclusionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise V03ExclusionError(code)


@dataclass(frozen=True)
class ExclusionManifest:
    exclusion_schema_version: int
    canonical_dataset_fingerprint: str
    excluded_record_count: int
    exclusion_reason_counts: Mapping[str, int]
    opaque_record_references: tuple[str, ...]
    exclusion_fingerprint: str
    effective_dataset_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "exclusion_reason_counts",
            MappingProxyType(dict(self.exclusion_reason_counts)),
        )


def _consistent(scan: ScannerResult, review: ReviewResult) -> None:
    if (
        scan.scanner_type,
        scan.scanner_version,
        scan.config_fingerprint,
        scan.findings_fingerprint,
    ) != (
        review.scanner_type,
        review.scanner_version,
        review.config_fingerprint,
        review.findings_fingerprint,
    ):
        _fail("V03_EVIDENCE_PAYLOAD_INCONSISTENT")


def build_exclusion_manifest(
    *,
    canonical_dataset_fingerprint: str,
    scanner_reviews: Sequence[tuple[ScannerResult, ReviewResult]],
    policy: ReviewPolicy,
) -> ExclusionManifest:
    if (
        not canonical_dataset_fingerprint.startswith("sha256:")
        or len(canonical_dataset_fingerprint) != 71
    ):
        _fail("V03_EXCLUSION_INVALID")
    excluded: dict[str, set[str]] = {}
    for scan, result in scanner_reviews:
        _consistent(scan, result)
        if (
            result.review_decision in {"blocked", "incomplete"}
            or result.unresolved_count
        ):
            _fail("V03_REVIEW_INCOMPLETE")
        findings = {item.finding_id: item for item in scan.findings}
        for review in result.reviews:
            should_exclude = review.decision == "exclude" or (
                review.decision == "retain_with_review"
                and policy.exclude_retained_with_review
            )
            if should_exclude:
                ref = findings[review.finding_id].opaque_record_reference
                excluded.setdefault(ref, set()).add(review.reason_code)
    references = tuple(sorted(excluded))
    reason_counts: dict[str, int] = {}
    for reasons in excluded.values():
        for reason in reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    reason_counts = dict(sorted(reason_counts.items()))
    exclusion_fp = calculate_exclusion_fingerprint(
        canonical_dataset_fingerprint=canonical_dataset_fingerprint,
        exclusion_reason_counts=reason_counts,
        opaque_record_references=references,
    )
    effective_fp = calculate_effective_dataset_fingerprint(
        canonical_dataset_fingerprint=canonical_dataset_fingerprint,
        evaluation_exclusion_fingerprint=exclusion_fp,
    )
    return ExclusionManifest(
        1,
        canonical_dataset_fingerprint,
        len(references),
        reason_counts,
        references,
        exclusion_fp,
        effective_fp,
    )


_PII_R1_MAP = {
    "resident_registration_number": "resident_id",
    "phone_number": "phone",
    "email": "email",
    "postal_address": "address",
    "bank_account": "financial_identifier",
    "card_number": "financial_identifier",
    "person_organization_combination": "name_organization",
    "user_identifier": "user_id",
    "personal_url_identifier": "url_identifier",
    "sensitive_free_text": "sensitive_narrative",
    "reconstruction_risk": "source_reconstruction",
}


def _r1_decision(result: ReviewResult) -> str:
    return (
        "passed"
        if result.review_decision in {"passed", "passed_with_conditions"}
        else "blocked"
    )


def build_pii_scan_summary_payload(
    *, scan_result: ScannerResult, review_result: ReviewResult
) -> dict[str, object]:
    _consistent(scan_result, review_result)
    if scan_result.scanner_type != "pii" or set(scan_result.category_counts) != set(
        PII_CATEGORIES
    ):
        _fail("V03_EVIDENCE_PAYLOAD_INCONSISTENT")
    counts = {
        name: 0
        for name in (
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
    }
    for source, count in scan_result.category_counts.items():
        counts[_PII_R1_MAP[source]] += count
    return {
        "scanner_version": scan_result.scanner_version,
        "input_dataset_fingerprint": scan_result.input_dataset_fingerprint,
        "scanned_record_count": scan_result.scanned_record_count,
        "finding_count_by_category": counts,
        "finding_count_by_severity": dict(scan_result.severity_counts),
        "unresolved_count": review_result.unresolved_count,
        "excluded_count": review_result.excluded_count,
        "retained_with_review_count": review_result.retained_with_review_count,
        "findings_fingerprint": scan_result.findings_fingerprint,
        "scan_decision": _r1_decision(review_result),
    }


def build_pii_review_evidence_payload(
    *, scan_result: ScannerResult, review_result: ReviewResult
) -> dict[str, object]:
    _consistent(scan_result, review_result)
    return {
        "reviewed_finding_count": review_result.reviewed_count,
        "unresolved_count": review_result.unresolved_count,
        "critical_unresolved": review_result.critical_unresolved,
        "high_unresolved": review_result.high_unresolved,
        "medium_retained_count": review_result.medium_retained_count,
        "reviewer_ids": sorted({item.reviewer_id for item in review_result.reviews})
        or ["synthetic-reviewer-not_for_runtime"],
        "reason_code_counts": dict(review_result.reason_code_counts),
        "review_fingerprint": review_result.review_fingerprint,
        "review_decision": _r1_decision(review_result),
    }


def build_safety_scan_summary_payload(
    *, scan_result: ScannerResult, review_result: ReviewResult
) -> dict[str, object]:
    _consistent(scan_result, review_result)
    if scan_result.scanner_type != "safety" or set(scan_result.category_counts) != set(
        SAFETY_CATEGORIES
    ):
        _fail("V03_EVIDENCE_PAYLOAD_INCONSISTENT")
    return {
        "category_counts": dict(scan_result.category_counts),
        "severity_counts": dict(scan_result.severity_counts),
        "unresolved_count": review_result.unresolved_count,
        "excluded_count": review_result.excluded_count,
        "retained_with_review_count": review_result.retained_with_review_count,
        "findings_fingerprint": scan_result.findings_fingerprint,
        "scan_decision": _r1_decision(review_result),
    }


def build_safety_review_evidence_payload(
    *, scan_result: ScannerResult, review_result: ReviewResult
) -> dict[str, object]:
    _consistent(scan_result, review_result)
    return {
        "reviewed_finding_count": review_result.reviewed_count,
        "critical_retained_count": review_result.critical_retained_count,
        "high_retained_count": review_result.high_retained_count,
        "medium_retained_count": review_result.medium_retained_count,
        "unresolved_count": review_result.unresolved_count,
        "reviewer_ids": sorted({item.reviewer_id for item in review_result.reviews})
        or ["synthetic-reviewer-not_for_runtime"],
        "reason_code_counts": dict(review_result.reason_code_counts),
        "review_fingerprint": review_result.review_fingerprint,
        "review_decision": _r1_decision(review_result),
    }


def build_leakage_scan_summary_payload(
    *,
    scan_result: ScannerResult,
    review_result: ReviewResult,
    benchmark_identity: str,
    benchmark_version: str,
    benchmark_fingerprint: str,
) -> dict[str, object]:
    _consistent(scan_result, review_result)
    if scan_result.scanner_type != "leakage":
        _fail("V03_EVIDENCE_PAYLOAD_INCONSISTENT")
    counts = scan_result.category_counts
    return {
        "benchmark_identity": benchmark_identity,
        "benchmark_version": benchmark_version,
        "benchmark_fingerprint": benchmark_fingerprint,
        "exact_duplicate_count": counts["exact_duplicate"],
        "normalized_duplicate_count": counts["normalized_duplicate"],
        "near_duplicate_count": counts["near_duplicate"],
        "prompt_overlap_count": counts["prompt_overlap"],
        "answer_overlap_count": counts["answer_overlap"],
        "template_contamination_count": counts["template_contamination"],
        "train_validation_overlap_count": counts["train_validation_overlap"],
        "prior_evaluation_overlap_count": counts["prior_evaluation_overlap"],
        "unresolved_count": review_result.unresolved_count,
        "exclusion_count": review_result.excluded_count,
        "findings_fingerprint": scan_result.findings_fingerprint,
        "scan_decision": _r1_decision(review_result),
    }


def build_evaluation_exclusion_manifest_payload(
    *, manifest: ExclusionManifest
) -> dict[str, object]:
    # R1 predates the R2 opaque:v1 label. Preserve the same HMAC digest while
    # adapting only the public scheme label required by the strict R1 schema.
    references = [
        "hmac-sha256:" + value.removeprefix("opaque:v1:")
        for value in manifest.opaque_record_references
    ]
    exclusion_fingerprint = calculate_exclusion_fingerprint(
        canonical_dataset_fingerprint=manifest.canonical_dataset_fingerprint,
        exclusion_reason_counts=manifest.exclusion_reason_counts,
        opaque_record_references=references,
    )
    return {
        "exclusion_schema_version": manifest.exclusion_schema_version,
        "canonical_dataset_fingerprint": manifest.canonical_dataset_fingerprint,
        "excluded_record_count": manifest.excluded_record_count,
        "exclusion_reason_counts": dict(manifest.exclusion_reason_counts),
        "opaque_record_references": references,
        "exclusion_fingerprint": exclusion_fingerprint,
        "effective_dataset_fingerprint": calculate_effective_dataset_fingerprint(
            canonical_dataset_fingerprint=manifest.canonical_dataset_fingerprint,
            evaluation_exclusion_fingerprint=exclusion_fingerprint,
        ),
    }
