from __future__ import annotations

import ast
import inspect
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

import src.data.learning_candidate_consumer as consumer_module
from src.data.learning_candidate_consumer import (
    LearningCandidateConsumerError,
    ValidatedLearningCandidate,
    validate_learning_candidate_for_consumption,
)

NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)
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


def _candidate() -> dict:
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
        "review_evidence_ids": ["review_test"],
        "content_fingerprint": "sha256:" + "c" * 64,
        "parent_candidate_ids": ["candidate_parent"],
    }


def _rights() -> dict:
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


def _eligibility() -> dict:
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


def _consume(
    candidate: object | None = None,
    rights: object | None = None,
    eligibility: object | None = None,
    **kwargs: object,
) -> ValidatedLearningCandidate:
    return validate_learning_candidate_for_consumption(
        _candidate() if candidate is None else candidate,
        rights_metadata=_rights() if rights is None else rights,
        training_eligibility=_eligibility() if eligibility is None else eligibility,
        evaluated_at=kwargs.pop("evaluated_at", NOW),
        usage_purpose=kwargs.pop("usage_purpose", "lyrics_training"),
        expected_workspace_id=kwargs.pop("expected_workspace_id", "workspace_test"),
    )


def _assert_error(code: str, action) -> LearningCandidateConsumerError:
    with pytest.raises(LearningCandidateConsumerError) as raised:
        action()
    assert raised.value.code == code
    return raised.value


def test_valid_canonical_candidate_returns_immutable_projection() -> None:
    result = _consume()
    assert result.candidate_id == "candidate_test"
    assert result.canonical_status == "approved"
    assert result.workspace_id == "workspace_test"
    assert result.parent_candidate_ids == ("candidate_parent",)
    assert result.candidate_producer.name == "synthetic-test"
    assert result.contract_package_version == "0.1.0"
    assert result.contract_policy_version == "1.0.0"
    assert result.contract_authority_commit == (
        "dd75fc88c16e9ae9a04acfafb72756a905f6365b"
    )
    with pytest.raises(FrozenInstanceError):
        result.candidate_id = "changed"  # type: ignore[misc]


def test_malformed_payload_and_unsupported_version_fail_closed() -> None:
    malformed = _candidate()
    malformed["raw_payload"] = "PRIVATE_RAW_CANDIDATE_MARKER"
    error = _assert_error("CONTRACT_INVALID", lambda: _consume(candidate=malformed))
    assert "private" not in str(error)
    unsupported = _candidate()
    unsupported["schema_version"] = "2.0.0"
    _assert_error(
        "UNSUPPORTED_CONTRACT_VERSION", lambda: _consume(candidate=unsupported)
    )


def test_missing_rights_and_eligibility_are_distinct() -> None:
    _assert_error(
        "RIGHTS_MISSING",
        lambda: validate_learning_candidate_for_consumption(
            _candidate(),
            rights_metadata=None,
            training_eligibility=_eligibility(),
            evaluated_at=NOW,
            usage_purpose="lyrics_training",
        ),
    )
    _assert_error(
        "ELIGIBILITY_MISSING",
        lambda: validate_learning_candidate_for_consumption(
            _candidate(),
            rights_metadata=_rights(),
            training_eligibility=None,
            evaluated_at=NOW,
            usage_purpose="lyrics_training",
        ),
    )


@pytest.mark.parametrize(
    ("status", "code"),
    (("revoked", "RIGHTS_REVOKED"), ("expired", "RIGHTS_EXPIRED")),
)
def test_terminal_rights_status_fails_closed(status: str, code: str) -> None:
    rights = _rights()
    rights["rights_status"] = status
    rights["training_allowed"] = False
    _assert_error(code, lambda: _consume(rights=rights))


def test_rights_retention_and_expiry_fail_closed() -> None:
    invalid = _rights()
    invalid["retention_allowed"] = True
    _assert_error("RIGHTS_INVALID", lambda: _consume(rights=invalid))
    expired = _rights()
    expired["retention_allowed"]["expires_at"] = "2026-08-20T00:00:00Z"
    _assert_error("RIGHTS_EXPIRED", lambda: _consume(rights=expired))


def test_eligibility_expired_revoked_and_non_pass_fail_closed() -> None:
    expired = _eligibility()
    expired["expires_at"] = "2026-08-20T00:00:00Z"
    _assert_error("ELIGIBILITY_EXPIRED", lambda: _consume(eligibility=expired))
    revoked = _eligibility()
    revoked.update(decision="revoked", approved=False, training_allowed=False)
    _assert_error("ELIGIBILITY_REVOKED", lambda: _consume(eligibility=revoked))
    invalid = _eligibility()
    invalid["checks"]["quality"] = "fail"
    invalid.update(decision="ineligible", approved=False, training_allowed=False)
    _assert_error("ELIGIBILITY_INVALID", lambda: _consume(eligibility=invalid))


def test_review_and_consent_evidence_are_required() -> None:
    candidate = _candidate()
    candidate["review_evidence_ids"] = []
    _assert_error("EVIDENCE_MISSING", lambda: _consume(candidate=candidate))
    rights = _rights()
    rights["consent_evidence_refs"] = []
    _assert_error("EVIDENCE_MISSING", lambda: _consume(rights=rights))


def test_identity_usage_purpose_and_status_bindings_are_exact() -> None:
    eligibility = _eligibility()
    eligibility["candidate_id"] = "candidate_other"
    _assert_error("IDENTITY_MISMATCH", lambda: _consume(eligibility=eligibility))
    _assert_error(
        "ELIGIBILITY_INVALID",
        lambda: _consume(usage_purpose="different_training"),
    )
    candidate = _candidate()
    candidate["status"] = "in_review"
    eligibility = _eligibility()
    eligibility.update(
        candidate_status="in_review", approved=False, training_allowed=False
    )
    eligibility["decision"] = "needs_review"
    _assert_error(
        "ELIGIBILITY_INVALID",
        lambda: _consume(candidate=candidate, eligibility=eligibility),
    )


def test_lineage_and_workspace_scope_mismatch_fail_closed() -> None:
    candidate = _candidate()
    candidate["parent_candidate_ids"] = []
    candidate["input_refs"] = []
    _assert_error("LINEAGE_INVALID", lambda: _consume(candidate=candidate))
    rights = _rights()
    rights["workspace_id"] = "workspace_other"
    _assert_error("SCOPE_MISMATCH", lambda: _consume(rights=rights))


def test_payloads_are_not_mutated_and_raw_payload_is_not_retained() -> None:
    candidate, rights, eligibility = _candidate(), _rights(), _eligibility()
    before = deepcopy((candidate, rights, eligibility))
    result = _consume(candidate=candidate, rights=rights, eligibility=eligibility)
    assert (candidate, rights, eligibility) == before
    assert not hasattr(result, "payload")
    assert not hasattr(result, "canonical_payload")


def test_boundary_has_no_publication_training_or_persistence_dependency() -> None:
    tree = ast.parse(inspect.getsource(consumer_module))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )
    assert not any("dataset_publication" in name for name in imports)
    assert not any("training" in name for name in imports)
    assert not any("psycopg" in name or "sqlite" in name for name in imports)
    assert _consume().canonical_status == "approved"
