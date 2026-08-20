from __future__ import annotations

import ast
import inspect
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

import src.data.learning_candidate_dataset_handoff as handoff_module
import src.data.learning_candidate_review as review_module
from src.data.learning_candidate_consumer import (
    ValidatedLearningCandidate,
    validate_learning_candidate_for_consumption,
)
from src.data.learning_candidate_dataset_handoff import (
    DatasetInclusionHandoffError,
    DatasetInclusionHandoffRejected,
    DatasetInclusionHandoffStatus,
    create_dataset_inclusion_handoff,
)
from src.data.learning_candidate_review import (
    ReviewDecision,
    review_learning_candidate,
)

CONSUMED_AT = datetime(2026, 8, 20, tzinfo=timezone.utc)
REVIEWED_AT = datetime(2026, 8, 21, tzinfo=timezone.utc)
HANDOFF_AT = datetime(2026, 8, 22, tzinfo=timezone.utc)
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


def _review(requested: ReviewDecision = ReviewDecision.ACCEPTED):
    return review_learning_candidate(
        _validated_candidate(),
        reviewer_id="reviewer_local",
        reviewed_at=REVIEWED_AT,
        requested_decision=requested,
        review_evidence_reference="review:local:1",
        authority=_Authority(_rights_payload(), _eligibility_payload()),
        expected_workspace_id="workspace_test",
    )


def _handoff(
    *,
    review_result=None,
    rights: object | None = None,
    eligibility: object | None = None,
    authority: object | None = None,
    handoff_created_at: datetime = HANDOFF_AT,
    expected_workspace_id: str | None = "workspace_test",
):
    resolved_authority = authority or _Authority(
        _rights_payload() if rights is None else rights,
        _eligibility_payload() if eligibility is None else eligibility,
    )
    return create_dataset_inclusion_handoff(
        _review() if review_result is None else review_result,
        handoff_created_at=handoff_created_at,
        authority=resolved_authority,
        expected_workspace_id=expected_workspace_id,
    )


def _assert_error(code: str, action, error_type=DatasetInclusionHandoffError):
    with pytest.raises(error_type) as raised:
        action()
    assert raised.value.code == code
    return raised.value


def test_accepted_current_review_creates_deterministic_review_only_handoff() -> None:
    authority = _Authority(_rights_payload(), _eligibility_payload())
    result = _handoff(authority=authority)
    replay = _handoff()

    assert result == replay
    assert result.handoff_id.startswith("handoff:sha256:")
    assert (
        result.status is DatasetInclusionHandoffStatus.PENDING_DATASET_INCLUSION_REVIEW
    )
    assert result.candidate_id == "candidate_test"
    assert result.review_evidence_reference == "review:local:1"
    assert result.workspace_id == "workspace_test"
    assert result.dataset_inclusion_review_allowed is True
    assert result.dataset_version_creation_allowed is False
    assert result.dataset_publication_allowed is False
    assert result.training_allowed is False
    assert result.evaluation_allowed is False
    assert result.promotion_allowed is False
    assert authority.calls == [
        ("rights", "rights_test", HANDOFF_AT),
        ("eligibility", "eligibility_test", HANDOFF_AT),
    ]


@pytest.mark.parametrize(
    "value",
    ({}, _validated_candidate(), type("DuckReview", (), {"decision": "ACCEPTED"})()),
)
def test_only_exact_review_result_is_accepted(value: object) -> None:
    _assert_error("REVIEW_RESULT_INVALID", lambda: _handoff(review_result=value))


@pytest.mark.parametrize(
    "decision",
    (ReviewDecision.REJECTED, ReviewDecision.NEEDS_REVIEW),
)
def test_non_accepted_business_review_is_rejected(decision: ReviewDecision) -> None:
    review_result = _review(decision)
    _assert_error(
        "REVIEW_NOT_ACCEPTED",
        lambda: _handoff(review_result=review_result),
        DatasetInclusionHandoffRejected,
    )


def test_stale_accepted_review_expiry_boundary_is_rejected() -> None:
    eligibility = _eligibility_payload()
    eligibility["expires_at"] = "2026-08-22T00:00:00Z"
    _assert_error(
        "CURRENT_ELIGIBILITY_EXPIRED",
        lambda: _handoff(eligibility=eligibility),
        DatasetInclusionHandoffRejected,
    )


@pytest.mark.parametrize(
    ("target", "mutation", "code"),
    (
        (
            "eligibility",
            {"decision": "revoked", "approved": False, "training_allowed": False},
            "CURRENT_ELIGIBILITY_REVOKED",
        ),
        (
            "eligibility",
            {"decision": "ineligible", "approved": False, "training_allowed": False},
            "CURRENT_ELIGIBILITY_INVALID",
        ),
        (
            "rights",
            {"rights_status": "revoked", "training_allowed": False},
            "CURRENT_RIGHTS_REVOKED",
        ),
        (
            "rights",
            {"rights_status": "rejected", "training_allowed": False},
            "CURRENT_RIGHTS_INVALID",
        ),
    ),
)
def test_current_revocation_and_policy_invalid_states_reject_handoff(
    target: str, mutation: dict, code: str
) -> None:
    rights = _rights_payload()
    eligibility = _eligibility_payload()
    (rights if target == "rights" else eligibility).update(mutation)
    if code == "CURRENT_ELIGIBILITY_INVALID":
        eligibility["checks"]["quality"] = "fail"
    _assert_error(
        code,
        lambda: _handoff(rights=rights, eligibility=eligibility),
        DatasetInclusionHandoffRejected,
    )


def test_unresolved_current_authority_rejects_without_silent_accept() -> None:
    authority = _Authority(None, _eligibility_payload())
    _assert_error(
        "CURRENT_EVIDENCE_UNRESOLVED",
        lambda: _handoff(authority=authority),
        DatasetInclusionHandoffRejected,
    )


@pytest.mark.parametrize(
    ("target", "mutator", "code"),
    (
        (
            "eligibility",
            lambda value: value.update(candidate_id="candidate_other"),
            "CURRENT_IDENTITY_MISMATCH",
        ),
        (
            "rights",
            lambda value: value.update(consent_evidence_refs=["consent_other"]),
            "EVIDENCE_IDENTITY_MISMATCH",
        ),
        (
            "rights",
            lambda value: value.update(producer={"name": "other", "version": "1.0.0"}),
            "CURRENT_AUTHORITY_MISMATCH",
        ),
        (
            "eligibility",
            lambda value: value.update(workspace_id="workspace_other"),
            "WORKSPACE_SCOPE_MISMATCH",
        ),
    ),
)
def test_current_identity_evidence_authority_and_scope_drift_fail_closed(
    target: str, mutator, code: str
) -> None:
    rights = _rights_payload()
    eligibility = _eligibility_payload()
    mutator(rights if target == "rights" else eligibility)
    _assert_error(code, lambda: _handoff(rights=rights, eligibility=eligibility))


def test_review_identity_lineage_and_workspace_tampering_fail_closed() -> None:
    review_result = _review()
    _assert_error(
        "REVIEW_IDENTITY_INVALID",
        lambda: _handoff(
            review_result=replace(review_result, candidate_id="../private")
        ),
    )
    _assert_error(
        "CURRENT_IDENTITY_MISMATCH",
        lambda: _handoff(
            review_result=replace(review_result, rights_metadata_id="rights_other")
        ),
    )
    _assert_error(
        "LINEAGE_MISMATCH",
        lambda: _handoff(
            review_result=replace(
                review_result,
                parent_candidate_ids=(review_result.candidate_id,),
            )
        ),
    )
    _assert_error(
        "REVIEW_IDENTITY_INVALID",
        lambda: _handoff(
            review_result=replace(review_result, source_type="../private")
        ),
    )
    _assert_error(
        "REVIEW_IDENTITY_INVALID",
        lambda: _handoff(
            review_result=replace(
                review_result,
                candidate_review_evidence_ids=("../private",),
            )
        ),
    )
    _assert_error(
        "WORKSPACE_SCOPE_MISMATCH",
        lambda: _handoff(expected_workspace_id="workspace_other"),
    )


def test_handoff_timestamp_is_explicit_aware_and_after_review() -> None:
    _assert_error(
        "HANDOFF_TIMESTAMP_INVALID",
        lambda: _handoff(handoff_created_at=datetime(2026, 8, 22)),
    )
    _assert_error(
        "REVIEW_TIMESTAMP_INVALID",
        lambda: _handoff(handoff_created_at=datetime(2026, 8, 20, tzinfo=timezone.utc)),
    )


def test_result_is_immutable_and_preserves_only_safe_identity_projection() -> None:
    result = _handoff()
    assert result.parent_candidate_ids == ("candidate_parent",)
    assert result.input_references[0].object_id == "artifact_source"
    assert result.rights_metadata_id == "rights_test"
    assert result.training_eligibility_id == "eligibility_test"
    assert not hasattr(result, "payload")
    assert not hasattr(result, "canonical_payload")
    assert not hasattr(result, "training_ready")
    with pytest.raises(FrozenInstanceError):
        result.candidate_id = "mutated"  # type: ignore[misc]


def test_review_and_current_evidence_inputs_are_not_mutated() -> None:
    review_result = _review()
    rights = _rights_payload()
    eligibility = _eligibility_payload()
    before = deepcopy((review_result, rights, eligibility))
    _handoff(review_result=review_result, rights=rights, eligibility=eligibility)
    assert (review_result, rights, eligibility) == before


def test_common_validators_are_reused_for_current_evidence(monkeypatch) -> None:
    calls: list[str] = []
    review_result = _review()
    rights_validator = review_module.validate_rights_metadata
    eligibility_validator = review_module.validate_training_eligibility

    def validate_rights(value):
        calls.append("rights")
        return rights_validator(value)

    def validate_eligibility(value):
        calls.append("eligibility")
        return eligibility_validator(value)

    monkeypatch.setattr(review_module, "validate_rights_metadata", validate_rights)
    monkeypatch.setattr(
        review_module,
        "validate_training_eligibility",
        validate_eligibility,
    )
    _handoff(review_result=review_result)
    assert calls == ["rights", "eligibility"]


def test_authority_failure_is_sanitized() -> None:
    class FailingAuthority:
        def resolve_rights_metadata(self, *_args, **_kwargs):
            raise RuntimeError("PRIVATE_RAW_PAYLOAD credential=secret")

        def resolve_training_eligibility(self, *_args, **_kwargs):
            raise AssertionError("must not matter")

    error = _assert_error(
        "CURRENT_AUTHORITY_UNAVAILABLE",
        lambda: _handoff(authority=FailingAuthority()),
    )
    assert "PRIVATE_RAW_PAYLOAD" not in str(error)
    assert "credential" not in str(error)


def test_boundary_has_no_dataset_publication_training_persistence_or_api_dependency() -> (
    None
):
    tree = ast.parse(inspect.getsource(handoff_module))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    assert "DatasetVersion" not in names
    assert "ApprovedDatasetVersion" not in names
    assert "publish_dataset_version" not in names
    assert not any("dataset_governance" in name for name in imports)
    assert not any("dataset_publication" in name for name in imports)
    assert not any("training" in name for name in imports)
    assert not any("evaluation" in name or "promotion" in name for name in imports)
    assert not any("psycopg" in name or "fastapi" in name for name in imports)
