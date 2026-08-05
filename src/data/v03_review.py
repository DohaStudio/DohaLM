"""Pure review and disposition contracts for V03-R2 scanner findings."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from .v03_evidence import v03_fingerprint
from .v03_scanning import ScannerFinding, ScannerResult

REVIEW_DECISIONS = ("exclude", "retain_with_review", "dismiss", "unresolved")
_REASON = re.compile(r"[A-Z][A-Z0-9_]{2,127}\Z")
_REVIEWER = re.compile(r"opaque-reviewer:v1:[0-9a-f]{64}\Z")


class V03ReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise V03ReviewError(code)


@dataclass(frozen=True)
class ReviewPolicy:
    schema_version: int = 1
    allow_high_retain: bool = False
    retain_medium_requires_reason: bool = True
    exclude_retained_with_review: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != 1 or any(
            type(value) is not bool
            for value in (
                self.allow_high_retain,
                self.retain_medium_requires_reason,
                self.exclude_retained_with_review,
            )
        ):
            _fail("V03_REVIEW_POLICY_VIOLATION")

    @property
    def fingerprint(self) -> str:
        return v03_fingerprint(
            {
                "schema_version": self.schema_version,
                "allow_high_retain": self.allow_high_retain,
                "retain_medium_requires_reason": self.retain_medium_requires_reason,
                "exclude_retained_with_review": self.exclude_retained_with_review,
            }
        )


@dataclass(frozen=True)
class FindingReview:
    review_id: str
    finding_id: str
    opaque_record_reference: str
    reviewer_id: str
    decision: str
    reason_code: str
    reviewed_at: str = field(compare=False)
    review_fingerprint: str

    def __post_init__(self) -> None:
        if (
            self.decision not in REVIEW_DECISIONS
            or _REVIEWER.fullmatch(self.reviewer_id) is None
            or _REASON.fullmatch(self.reason_code) is None
        ):
            _fail("V03_REVIEW_INVALID")


def make_finding_review(
    *,
    finding: ScannerFinding,
    reviewer_id: str,
    decision: str,
    reason_code: str,
    reviewed_at: str = "1970-01-01T00:00:00Z",
) -> FindingReview:
    identity = {
        "finding_id": finding.finding_id,
        "opaque_record_reference": finding.opaque_record_reference,
        "reviewer_id": reviewer_id,
        "decision": decision,
        "reason_code": reason_code,
    }
    fingerprint = v03_fingerprint(identity)
    review_id = "review:v1:" + hashlib.sha256(fingerprint.encode()).hexdigest()
    return FindingReview(
        review_id,
        finding.finding_id,
        finding.opaque_record_reference,
        reviewer_id,
        decision,
        reason_code,
        reviewed_at,
        fingerprint,
    )


@dataclass(frozen=True)
class ReviewResult:
    scanner_type: str
    scanner_version: str
    config_fingerprint: str
    findings_fingerprint: str
    reviewed_count: int
    excluded_count: int
    retained_with_review_count: int
    dismissed_count: int
    unresolved_count: int
    critical_unresolved: int
    high_unresolved: int
    medium_retained_count: int
    critical_retained_count: int
    high_retained_count: int
    reason_code_counts: Mapping[str, int]
    reviews: tuple[FindingReview, ...]
    review_fingerprint: str
    review_decision: str
    policy_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "reason_code_counts", MappingProxyType(dict(self.reason_code_counts))
        )


def finalize_scan_reviews(
    *,
    scan_result: ScannerResult,
    reviews: Sequence[FindingReview],
    policy: ReviewPolicy,
) -> ReviewResult:
    if (
        not isinstance(scan_result, ScannerResult)
        or not isinstance(policy, ReviewPolicy)
        or not isinstance(reviews, (list, tuple))
        or any(not isinstance(item, FindingReview) for item in reviews)
    ):
        _fail("V03_REVIEW_INVALID")
    findings = {item.finding_id: item for item in scan_result.findings}
    if len(findings) != len(scan_result.findings):
        _fail("V03_REVIEW_INVALID")
    seen: set[str] = set()
    ordered: list[FindingReview] = []
    for review in reviews:
        if review.finding_id in seen:
            _fail("V03_REVIEW_INVALID")
        finding = findings.get(review.finding_id)
        if (
            finding is None
            or finding.opaque_record_reference != review.opaque_record_reference
        ):
            _fail("V03_REVIEW_INVALID")
        expected = make_finding_review(
            finding=finding,
            reviewer_id=review.reviewer_id,
            decision=review.decision,
            reason_code=review.reason_code,
            reviewed_at=review.reviewed_at,
        )
        if (
            expected.review_id != review.review_id
            or expected.review_fingerprint != review.review_fingerprint
        ):
            _fail("V03_REVIEW_INVALID")
        if review.decision == "retain_with_review":
            if finding.severity == "critical":
                _fail("V03_REVIEW_POLICY_VIOLATION")
            if finding.severity == "high" and not policy.allow_high_retain:
                _fail("V03_REVIEW_POLICY_VIOLATION")
            if (
                finding.severity == "medium"
                and policy.retain_medium_requires_reason
                and review.reason_code in {"RETAIN", "REVIEWED"}
            ):
                _fail("V03_REVIEW_POLICY_VIOLATION")
        seen.add(review.finding_id)
        ordered.append(review)
    ordered.sort(key=lambda item: item.finding_id)
    missing = tuple(
        item for item in scan_result.findings if item.finding_id not in seen
    )
    unresolved_reviews = [item for item in ordered if item.decision == "unresolved"]
    unresolved_findings = [
        findings[item.finding_id] for item in unresolved_reviews
    ] + list(missing)
    reason_counts: dict[str, int] = {}
    for review in ordered:
        reason_counts[review.reason_code] = reason_counts.get(review.reason_code, 0) + 1
    unresolved_count = len(unresolved_findings)
    critical_unresolved = sum(
        item.severity == "critical" for item in unresolved_findings
    )
    high_unresolved = sum(item.severity == "high" for item in unresolved_findings)
    excluded = sum(item.decision == "exclude" for item in ordered)
    retained = sum(item.decision == "retain_with_review" for item in ordered)
    dismissed = sum(item.decision == "dismiss" for item in ordered)
    medium_retained = sum(
        item.decision == "retain_with_review"
        and findings[item.finding_id].severity == "medium"
        for item in ordered
    )
    critical_retained = sum(
        item.decision == "retain_with_review"
        and findings[item.finding_id].severity == "critical"
        for item in ordered
    )
    high_retained = sum(
        item.decision == "retain_with_review"
        and findings[item.finding_id].severity == "high"
        for item in ordered
    )
    if missing:
        decision = "incomplete"
    elif (
        unresolved_count
        or critical_retained
        or (high_retained and not policy.allow_high_retain)
    ):
        decision = "blocked"
    elif retained:
        decision = "passed_with_conditions"
    else:
        decision = "passed"
    aggregate = {
        "scanner_type": scan_result.scanner_type,
        "scanner_version": scan_result.scanner_version,
        "findings_fingerprint": scan_result.findings_fingerprint,
        "policy_fingerprint": policy.fingerprint,
        "reviews": [item.review_fingerprint for item in ordered],
        "missing_finding_ids": sorted(item.finding_id for item in missing),
        "decision": decision,
    }
    return ReviewResult(
        scan_result.scanner_type,
        scan_result.scanner_version,
        scan_result.config_fingerprint,
        scan_result.findings_fingerprint,
        len(ordered),
        excluded,
        retained,
        dismissed,
        unresolved_count,
        critical_unresolved,
        high_unresolved,
        medium_retained,
        critical_retained,
        high_retained,
        reason_counts,
        tuple(ordered),
        v03_fingerprint(aggregate),
        decision,
        policy.fingerprint,
    )
