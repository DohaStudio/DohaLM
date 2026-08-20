from __future__ import annotations

import ast
import inspect
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

import src.data.learning_candidate_review as review_module
from src.data.learning_candidate_consumer import (
    ValidatedLearningCandidate,
    validate_learning_candidate_for_consumption,
)
from src.data.learning_candidate_review import (
    LearningCandidateReviewError,
    ReviewDecision,
    ReviewReason,
    review_learning_candidate,
)

CONSUMED_AT = datetime(2026, 8, 20, tzinfo=timezone.utc)
REVIEWED_AT = datetime(2026, 8, 21, tzinfo=timezone.utc)
CHECKSUM = "sha256:" + "a" * 64


def _envelope(kind: str, object_id: str) -> dict:
    return {
        "schema_name": kind,
        "schema_version": "1.0.0",
        "object_id": object_id,
        "created_at": "2026-08-19T00:00:00Z",
        "created_by": "actor_test",
        "producer": {"name": "synthetic-test", "version": "1.0.0"},
        "workspace_id": "workspace_test",
    }


def _candidate_payload() -> dict:
    return {
        **_envelope("learning_candidate", "candidate_test"),
        "candidate_id": "candidate_test",
        "source_type": "human_edited",
        "task": "lyrics_generation",
        "status": "approved",
        "input_refs": [
            {
                "object_id": "artifact_source",
                "schema_name": "artifact",
                "schema_version": "1.0.0",
                "content_fingerprint": CHECKSUM,
            }
        ],
        "output_refs": [
            {
                "object_id": "artifact_output",
                "schema_name": "artifact",
                "schema_version": "1.0.0",
                "content_fingerprint": "sha256:" + "b" * 64,
            }
        ],
        "rights_metadata_id": "rights_test",
        "review_evidence_ids": ["candidate_review_test"],
        "content_fingerprint": "sha256:" + "c" * 64,
        "parent_candidate_ids": ["candidate_parent"],
    }


def _rights_payload() -> dict:
    return {
        **_envelope("rights_metadata", "rights_test"),
        "rights_metadata_id": "rights_test",
        "source_type": "user_created",
        "rights_status": "approved_limited",
        "user_created": True,
        "generated": False,
        "reference": False,
        "uploaded": False,
        "external": False,
        "analysis_allowed": True,
        "training_allowed": True,
        "redistribution_allowed": False,
        "retention_allowed": {
            "allowed": True,
            "expires_at": "2026-09-20T00:00:00Z",
            "scope": "training",
        },
        "derivative_generation_allowed": True,
        "consent_evidence_refs": ["consent_test"],
        "jurisdiction": "KR",
        "reviewed_at": "2026-08-19T00:00:00Z",
        "reviewed_by": "reviewer_test",
    }


def _eligibility_payload() -> dict:
    return {
        **_envelope("training_eligibility", "eligibility_test"),
        "training_eligibility_id": "eligibility_test",
        "candidate_id": "candidate_test",
        "candidate_status": "approved",
        "rights_metadata_id": "rights_test",
        "policy_version": "1.0.0",
        "usage_purpose": "lyrics_training",
        "checks": {
            key: "pass"
            for key in (
                "review",
                "rights",
                "provenance",
                "consent",
                "retention",
                "purpose_scope",
                "quality",
                "pii",
                "lineage",
                "reference_source_separation",
            )
        },
        "approved": True,
        "training_allowed": True,
        "decision": "eligible",
        "reason_codes": [],
        "reviewed_by": "reviewer_test",
        "reviewed_at": "2026-08-19T00:00:00Z",
        "expires_at": "2026-09-20T00:00:00Z",
    }


def _validated_candidate() -> ValidatedLearningCandidate:
    return validate_learning_candidate_for_consumption(
        _candidate_payload(),
        rights_metadata=_rights_payload(),
        training_eligibility=_eligibility_payload(),
        evaluated_at=CONSUMED_AT,
        usage_purpose="lyrics_training",
        expected_workspace_id="workspace_test",
    )


class _Authority:
    def __init__(self, rights: object, eligibility: object) -> None:
        self.rights = rights
        self.eligibility = eligibility
        self.calls: list[tuple[str, str, datetime]] = []

    def resolve_rights_metadata(
        self, rights_metadata_id: str, *, checked_at: datetime
    ) -> object | None:
        self.calls.append(("rights", rights_metadata_id, checked_at))
        return self.rights

    def resolve_training_eligibility(
        self, training_eligibility_id: str, *, checked_at: datetime
    ) -> object | None:
        self.calls.append(("eligibility", training_eligibility_id, checked_at))
        return self.eligibility


def _review(
    requested: ReviewDecision = ReviewDecision.ACCEPTED,
    *,
    candidate: ValidatedLearningCandidate | None = None,
    rights: object | None = None,
    eligibility: object | None = None,
    authority: object | None = None,
    **kwargs: object,
):
    resolved_authority = authority or _Authority(
        _rights_payload() if rights is None else rights,
        _eligibility_payload() if eligibility is None else eligibility,
    )
    return review_learning_candidate(
        _validated_candidate() if candidate is None else candidate,
        reviewer_id=kwargs.pop("reviewer_id", "reviewer_local"),
        reviewed_at=kwargs.pop("reviewed_at", REVIEWED_AT),
        requested_decision=requested,
        review_evidence_reference=kwargs.pop(
            "review_evidence_reference", "review:local:1"
        ),
        authority=resolved_authority,
        expected_workspace_id=kwargs.pop("expected_workspace_id", "workspace_test"),
    )


def _assert_error(code: str, action) -> LearningCandidateReviewError:
    with pytest.raises(LearningCandidateReviewError) as raised:
        action()
    assert raised.value.code == code
    return raised.value


def test_accept_requires_valid_current_authority_and_is_review_only() -> None:
    authority = _Authority(_rights_payload(), _eligibility_payload())
    result = _review(authority=authority)
    assert result.decision is ReviewDecision.ACCEPTED
    assert result.reason_code is ReviewReason.ACCEPTED_VALID_CURRENT_ELIGIBILITY
    assert result.current_evidence_resolved is True
    assert result.dataset_inclusion_review_allowed is True
    assert result.dataset_publication_allowed is False
    assert result.training_allowed is False
    assert result.evaluation_allowed is False
    assert result.promotion_allowed is False
    assert authority.calls == [
        ("rights", "rights_test", REVIEWED_AT),
        ("eligibility", "eligibility_test", REVIEWED_AT),
    ]


def test_explicit_reject_and_needs_review_are_preserved_when_policy_passes() -> None:
    rejected = _review(ReviewDecision.REJECTED)
    assert rejected.decision is ReviewDecision.REJECTED
    assert rejected.reason_code is ReviewReason.REJECTED_BY_REVIEWER
    unresolved = _review(ReviewDecision.NEEDS_REVIEW)
    assert unresolved.decision is ReviewDecision.NEEDS_REVIEW
    assert unresolved.reason_code is ReviewReason.NEEDS_REVIEW_REQUESTED


@pytest.mark.parametrize("reviewer", ("", "owner path", "../reviewer"))
def test_invalid_reviewer_fails_closed(reviewer: str) -> None:
    _assert_error("REVIEWER_INVALID", lambda: _review(reviewer_id=reviewer))


def test_naive_or_earlier_review_time_fails_closed() -> None:
    _assert_error(
        "REVIEW_TIMESTAMP_INVALID",
        lambda: _review(reviewed_at=datetime(2026, 8, 21)),
    )
    earlier = datetime(2026, 8, 19, tzinfo=timezone.utc)
    _assert_error("REVIEW_TIMESTAMP_INVALID", lambda: _review(reviewed_at=earlier))


def test_expired_eligibility_overrides_requested_accept() -> None:
    eligibility = _eligibility_payload()
    eligibility["expires_at"] = "2026-08-21T00:00:00Z"
    result = _review(eligibility=eligibility)
    assert result.decision is ReviewDecision.REJECTED
    assert result.reason_code is ReviewReason.REJECTED_ELIGIBILITY_EXPIRED


def test_revoked_eligibility_overrides_requested_accept() -> None:
    eligibility = _eligibility_payload()
    eligibility.update(decision="revoked", approved=False, training_allowed=False)
    result = _review(eligibility=eligibility)
    assert result.decision is ReviewDecision.REJECTED
    assert result.reason_code is ReviewReason.REJECTED_ELIGIBILITY_REVOKED


def test_invalid_or_revoked_rights_override_requested_accept() -> None:
    invalid = _rights_payload()
    invalid.update(rights_status="rejected", training_allowed=False)
    result = _review(rights=invalid)
    assert result.reason_code is ReviewReason.REJECTED_RIGHTS_INVALID
    revoked = _rights_payload()
    revoked.update(rights_status="revoked", training_allowed=False)
    result = _review(rights=revoked)
    assert result.reason_code is ReviewReason.REJECTED_RIGHTS_REVOKED


def test_expired_rights_and_invalid_eligibility_override_requested_accept() -> None:
    rights = _rights_payload()
    rights["retention_allowed"]["expires_at"] = "2026-08-21T00:00:00Z"
    result = _review(rights=rights)
    assert result.reason_code is ReviewReason.REJECTED_RIGHTS_EXPIRED
    eligibility = _eligibility_payload()
    eligibility["checks"]["quality"] = "fail"
    eligibility.update(decision="ineligible", approved=False, training_allowed=False)
    result = _review(eligibility=eligibility)
    assert result.reason_code is ReviewReason.REJECTED_ELIGIBILITY_INVALID


def test_unresolved_current_authority_never_silently_accepts() -> None:
    result = _review(authority=_Authority(None, None))
    assert result.decision is ReviewDecision.NEEDS_REVIEW
    assert result.reason_code is ReviewReason.NEEDS_REVIEW_EVIDENCE_UNRESOLVED
    assert result.current_evidence_resolved is False
    assert result.dataset_inclusion_review_allowed is False


def test_invalid_or_failing_authority_is_sanitized_and_fails_closed() -> None:
    _assert_error("CURRENT_AUTHORITY_INVALID", lambda: _review(authority=object()))

    class _FailingAuthority(_Authority):
        def resolve_rights_metadata(
            self, rights_metadata_id: str, *, checked_at: datetime
        ) -> object | None:
            raise RuntimeError("PRIVATE_AUTHORITY_DETAIL")

    error = _assert_error(
        "CURRENT_AUTHORITY_UNAVAILABLE",
        lambda: _review(
            authority=_FailingAuthority(_rights_payload(), _eligibility_payload())
        ),
    )
    assert "PRIVATE_AUTHORITY_DETAIL" not in str(error)


def test_malformed_current_contract_is_error_not_review_result() -> None:
    rights = _rights_payload()
    rights["raw_payload"] = "PRIVATE_RAW_MARKER"
    error = _assert_error(
        "CURRENT_RIGHTS_CONTRACT_INVALID", lambda: _review(rights=rights)
    )
    assert "PRIVATE_RAW_MARKER" not in str(error)


def test_identity_evidence_and_authority_drift_fail_closed() -> None:
    eligibility = _eligibility_payload()
    eligibility["candidate_id"] = "candidate_other"
    _assert_error("CURRENT_IDENTITY_MISMATCH", lambda: _review(eligibility=eligibility))
    rights = _rights_payload()
    rights["consent_evidence_refs"] = ["consent_other"]
    _assert_error("EVIDENCE_IDENTITY_MISMATCH", lambda: _review(rights=rights))
    rights = _rights_payload()
    rights["producer"] = {"name": "other-producer", "version": "1.0.0"}
    _assert_error("CURRENT_AUTHORITY_MISMATCH", lambda: _review(rights=rights))


def test_invalid_validated_view_lineage_and_scope_fail_closed() -> None:
    candidate = replace(_validated_candidate(), contract_policy_version="9.0.0")
    _assert_error("VALIDATED_CANDIDATE_INVALID", lambda: _review(candidate=candidate))
    candidate = _validated_candidate()
    candidate = replace(
        candidate,
        parent_candidate_ids=(candidate.candidate_id,),
    )
    _assert_error("LINEAGE_MISMATCH", lambda: _review(candidate=candidate))
    _assert_error(
        "WORKSPACE_SCOPE_MISMATCH",
        lambda: _review(expected_workspace_id="workspace_other"),
    )


def test_result_is_immutable_and_preserves_safe_lineage_only() -> None:
    result = _review()
    assert result.parent_candidate_ids == ("candidate_parent",)
    assert result.input_references[0].object_id == "artifact_source"
    assert result.rights_metadata_id == "rights_test"
    assert result.training_eligibility_id == "eligibility_test"
    assert not hasattr(result, "payload")
    with pytest.raises(FrozenInstanceError):
        result.decision = ReviewDecision.REJECTED  # type: ignore[misc]


def test_inputs_are_not_mutated() -> None:
    candidate = _validated_candidate()
    rights = _rights_payload()
    eligibility = _eligibility_payload()
    before = deepcopy((candidate, rights, eligibility))
    _review(candidate=candidate, rights=rights, eligibility=eligibility)
    assert (candidate, rights, eligibility) == before


def test_gate_has_no_schema_persistence_publication_training_or_api_dependency() -> (
    None
):
    tree = ast.parse(inspect.getsource(review_module))
    class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    assert not {
        "LearningCandidate",
        "RightsMetadata",
        "TrainingEligibility",
    }.intersection(class_names)
    imports = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not any("dataset_publication" in name for name in imports)
    assert not any("training" in name for name in imports)
    assert not any("evaluation" in name or "promotion" in name for name in imports)
    assert not any("psycopg" in name or "fastapi" in name for name in imports)
