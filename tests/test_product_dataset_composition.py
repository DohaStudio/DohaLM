from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

import src.data.learning_candidate_dataset_handoff as handoff_module
import src.data.product_dataset_composition as composition_module
from src.data.checksums import checksum_value
from src.data.common_dataset_contracts import validate_dataset_version
from src.data.learning_candidate_consumer import CommonObjectReference, ProducerIdentity
from src.data.learning_candidate_dataset_handoff import (
    DatasetInclusionHandoff,
    DatasetInclusionHandoffStatus,
)
from src.data.product_dataset_composition import (
    ProductDatasetCompositionAuthorityInput,
    ProductDatasetCompositionError,
    ProductDatasetCompositionStatus,
    ProductDatasetMemberAllocation,
    build_dataset_version_proposal_mapping,
    compose_product_dataset,
)

CREATED_AT = datetime(2026, 8, 22, tzinfo=timezone.utc)
COMPOSED_AT = datetime(2026, 8, 23, tzinfo=timezone.utc)
PRODUCER = ProducerIdentity("synthetic-test", "1.0.0")


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


def _rights(suffix: str) -> dict:
    return {
        **_envelope("rights_metadata", f"rights_{suffix}"),
        "rights_metadata_id": f"rights_{suffix}",
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
        "consent_evidence_refs": [f"consent_{suffix}"],
        "jurisdiction": "KR",
        "reviewed_at": "2026-08-19T00:00:00Z",
        "reviewed_by": "reviewer_test",
    }


def _eligibility(suffix: str) -> dict:
    return {
        **_envelope("training_eligibility", f"eligibility_{suffix}"),
        "training_eligibility_id": f"eligibility_{suffix}",
        "candidate_id": f"candidate_{suffix}",
        "candidate_status": "approved",
        "rights_metadata_id": f"rights_{suffix}",
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


class _Authority:
    def __init__(self, suffixes: tuple[str, ...] = ("train", "validation", "test")):
        self.rights = {f"rights_{suffix}": _rights(suffix) for suffix in suffixes}
        self.eligibility = {
            f"eligibility_{suffix}": _eligibility(suffix) for suffix in suffixes
        }

    def resolve_rights_metadata(self, rights_metadata_id: str, *, checked_at):
        return self.rights.get(rights_metadata_id)

    def resolve_training_eligibility(self, training_eligibility_id: str, *, checked_at):
        return self.eligibility.get(training_eligibility_id)


def _handoff(
    suffix: str,
    fingerprint_character: str,
    *,
    workspace_id: str = "workspace_test",
) -> DatasetInclusionHandoff:
    handoff = DatasetInclusionHandoff(
        handoff_id="handoff:sha256:" + "0" * 64,
        status=DatasetInclusionHandoffStatus.PENDING_DATASET_INCLUSION_REVIEW,
        handoff_created_at="2026-08-21T00:00:00Z",
        candidate_id=f"candidate_{suffix}",
        review_evidence_reference=f"review:{suffix}",
        reviewer_id="reviewer_local",
        reviewed_at="2026-08-20T00:00:00Z",
        candidate_schema_version="1.0.0",
        candidate_content_fingerprint=("sha256:" + fingerprint_character.lower() * 64),
        candidate_producer=PRODUCER,
        rights_producer=PRODUCER,
        eligibility_producer=PRODUCER,
        source_type="human_edited",
        task="lyrics_generation",
        input_references=(
            CommonObjectReference(
                f"source_{suffix}",
                "artifact",
                "1.0.0",
                "sha256:" + fingerprint_character.lower() * 64,
            ),
        ),
        output_references=(
            CommonObjectReference(
                f"output_{suffix}",
                "artifact",
                "1.0.0",
                "sha256:" + fingerprint_character.lower() * 64,
            ),
        ),
        parent_candidate_ids=(f"parent_{suffix}",),
        candidate_review_evidence_ids=(f"candidate_review_{suffix}",),
        rights_metadata_id=f"rights_{suffix}",
        consent_evidence_refs=(f"consent_{suffix}",),
        training_eligibility_id=f"eligibility_{suffix}",
        usage_purpose="lyrics_training",
        workspace_id=workspace_id,
        rights_checked_at="2026-08-21T00:00:00Z",
        eligibility_checked_at="2026-08-21T00:00:00Z",
    )
    return replace(
        handoff,
        handoff_id=f"handoff:{checksum_value(handoff_module._handoff_projection(handoff))}",
    )


def _handoffs() -> tuple[DatasetInclusionHandoff, ...]:
    return (
        _handoff("train", "a"),
        _handoff("validation", "b"),
        _handoff("test", "c"),
    )


def _authority_input(
    handoffs: tuple[DatasetInclusionHandoff, ...],
    **changes,
) -> ProductDatasetCompositionAuthorityInput:
    value = ProductDatasetCompositionAuthorityInput(
        object_id="dataset_version_product_1",
        dataset_id="dataset_product",
        dataset_version="1.0.0",
        created_at=CREATED_AT,
        created_by="dataset_governance_owner",
        producer=ProducerIdentity("dohalm-product-governance", "1.0.0"),
        workspace_id="workspace_test",
        schema_manifest_id="record_schema_product_1",
        dataset_manifest_id="dataset_manifest_product_1",
        dataset_eligibility_evidence_id="dataset_gate_product_1",
        approval_evidence_ids=("dataset_review_product_1",),
        allocations=tuple(
            ProductDatasetMemberAllocation(handoff.handoff_id, split, f"group_{split}")
            for handoff, split in zip(
                handoffs,
                ("train", "validation", "test"),
                strict=True,
            )
        ),
    )
    return replace(value, **changes)


def _compose(
    handoffs: tuple[DatasetInclusionHandoff, ...] | None = None,
    *,
    authority_input: ProductDatasetCompositionAuthorityInput | None = None,
    authority: _Authority | None = None,
):
    values = handoffs or _handoffs()
    return compose_product_dataset(
        values,
        authority_input=authority_input or _authority_input(values),
        current_authority=authority or _Authority(),
        composed_at=COMPOSED_AT,
    )


def test_valid_composition_is_complete_common_draft_without_governance_call():
    result = _compose()
    mapping = build_dataset_version_proposal_mapping(result)
    assert (
        result.status
        is ProductDatasetCompositionStatus.READY_FOR_DATASET_VERSION_PROPOSAL
    )
    assert [
        len(result.train_members),
        len(result.validation_members),
        len(result.test_members),
    ] == [1, 1, 1]
    assert mapping["status"] == "draft"
    assert (
        mapping["approved"] is mapping["frozen"] is mapping["training_allowed"] is False
    )
    assert validate_dataset_version(mapping) is mapping


@pytest.mark.parametrize("missing_split", ["train", "validation", "test"])
def test_each_split_must_be_non_empty(missing_split: str):
    handoffs = _handoffs()
    authority = _authority_input(handoffs)
    replacements = tuple(
        replace(
            item,
            split=("validation" if missing_split == "train" else "train"),
        )
        if item.split == missing_split
        else item
        for item in authority.allocations
    )
    with pytest.raises(ProductDatasetCompositionError, match="SPLIT_EMPTY"):
        _compose(handoffs, authority_input=replace(authority, allocations=replacements))


def test_duplicate_handoff_and_candidate_fail_closed():
    handoffs = _handoffs()
    duplicate = (handoffs[0], handoffs[0], handoffs[2])
    allocations = (
        ProductDatasetMemberAllocation(handoffs[0].handoff_id, "train", "group_train"),
        ProductDatasetMemberAllocation(handoffs[2].handoff_id, "test", "group_test"),
    )
    with pytest.raises(ProductDatasetCompositionError):
        _compose(
            duplicate,
            authority_input=replace(
                _authority_input(handoffs), allocations=allocations
            ),
        )


def test_duplicate_content_across_distinct_members_fails_closed():
    handoffs = _handoffs()
    changed = replace(
        handoffs[1],
        candidate_content_fingerprint=handoffs[0].candidate_content_fingerprint,
    )
    changed = replace(
        changed,
        handoff_id=f"handoff:{checksum_value(handoff_module._handoff_projection(changed))}",
    )
    values = (handoffs[0], changed, handoffs[2])
    with pytest.raises(ProductDatasetCompositionError, match="DUPLICATE_CONTENT"):
        _compose(values, authority_input=_authority_input(values))


def test_missing_or_cross_split_group_key_fails_closed():
    handoffs = _handoffs()
    authority = _authority_input(handoffs)
    missing = replace(authority.allocations[0], group_key="")
    with pytest.raises(ProductDatasetCompositionError, match="ALLOCATION_INVALID"):
        _compose(
            handoffs,
            authority_input=replace(
                authority, allocations=(missing, *authority.allocations[1:])
            ),
        )
    shared = tuple(
        replace(item, group_key="group_shared") for item in authority.allocations
    )
    with pytest.raises(ProductDatasetCompositionError, match="CROSS_SPLIT_GROUP"):
        _compose(handoffs, authority_input=replace(authority, allocations=shared))


def test_tampered_handoff_wrong_type_status_and_workspace_fail_closed():
    handoffs = _handoffs()
    tampered = replace(handoffs[0], candidate_id="candidate_tampered")
    with pytest.raises(
        ProductDatasetCompositionError, match="HANDOFF_IDENTITY_MISMATCH"
    ):
        _compose((tampered, *handoffs[1:]))
    with pytest.raises(
        ProductDatasetCompositionError, match="HANDOFF_COLLECTION_INVALID"
    ):
        compose_product_dataset(
            [object()],
            authority_input=_authority_input(handoffs),
            current_authority=_Authority(),
            composed_at=COMPOSED_AT,
        )
    wrong_status = replace(handoffs[0], status="future")
    with pytest.raises(ProductDatasetCompositionError, match="HANDOFF_STATUS_INVALID"):
        _compose((wrong_status, *handoffs[1:]))
    other_workspace = _handoff("train", "a", workspace_id="workspace_other")
    with pytest.raises(
        ProductDatasetCompositionError, match="WORKSPACE_SCOPE_MISMATCH"
    ):
        _compose((other_workspace, *handoffs[1:]))


def test_invalid_semver_and_incomplete_allocation_fail_closed():
    handoffs = _handoffs()
    authority = _authority_input(handoffs)
    with pytest.raises(ProductDatasetCompositionError, match="AUTHORITY_INPUT_INVALID"):
        _compose(handoffs, authority_input=replace(authority, dataset_version="v1"))
    with pytest.raises(
        ProductDatasetCompositionError, match="ALLOCATION_COVERAGE_MISMATCH"
    ):
        _compose(
            handoffs,
            authority_input=replace(authority, allocations=authority.allocations[:-1]),
        )


def test_expired_or_revoked_current_evidence_prevents_composition():
    expired = _Authority()
    expired.rights["rights_train"]["retention_allowed"]["expires_at"] = (
        "2026-08-22T00:00:00Z"
    )
    with pytest.raises(ProductDatasetCompositionError, match="CURRENT_RIGHTS_EXPIRED"):
        _compose(authority=expired)
    revoked = _Authority()
    revoked.eligibility["eligibility_train"]["decision"] = "revoked"
    revoked.eligibility["eligibility_train"]["approved"] = False
    revoked.eligibility["eligibility_train"]["training_allowed"] = False
    with pytest.raises(
        ProductDatasetCompositionError, match="CURRENT_ELIGIBILITY_REVOKED"
    ):
        _compose(authority=revoked)


def test_same_logical_input_and_permutation_have_same_identity_and_mapping():
    handoffs = _handoffs()
    authority = _authority_input(handoffs)
    first = _compose(handoffs, authority_input=authority)
    reversed_handoffs = tuple(reversed(handoffs))
    second = _compose(reversed_handoffs, authority_input=authority)
    assert first == second
    assert build_dataset_version_proposal_mapping(
        first
    ) == build_dataset_version_proposal_mapping(second)


def test_audit_time_does_not_change_logical_identity_or_proposal_mapping():
    handoffs = _handoffs()
    authority = _authority_input(handoffs)
    first = compose_product_dataset(
        handoffs,
        authority_input=authority,
        current_authority=_Authority(),
        composed_at=COMPOSED_AT,
    )
    second = compose_product_dataset(
        handoffs,
        authority_input=authority,
        current_authority=_Authority(),
        composed_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )
    assert first.composed_at != second.composed_at
    assert first.composition_id == second.composition_id
    assert build_dataset_version_proposal_mapping(
        first
    ) == build_dataset_version_proposal_mapping(second)


def test_proposal_mapping_preserves_safe_source_parent_and_review_lineage():
    composition = _compose()
    mapping = build_dataset_version_proposal_mapping(composition)
    extension = mapping["extensions"]["dohalm.product_dataset_composition"]
    assert "composed_at" not in extension
    canonical_members = sorted(
        composition.members,
        key=lambda member: member.candidate_id,
    )
    assert [item["candidate_id"] for item in extension["member_bindings"]] == [
        member.candidate_id for member in canonical_members
    ]
    first = extension["member_bindings"][0]
    assert first["input_references"] == [
        composition_module._reference_projection(
            canonical_members[0].input_references[0]
        )
    ]
    assert first["parent_candidate_ids"] == list(
        canonical_members[0].parent_candidate_ids
    )
    assert first["review_evidence_reference"] == (
        canonical_members[0].review_evidence_reference
    )


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("producer", ProducerIdentity("other-governance", "1.0.0")),
        ("schema_manifest_id", "record_schema_product_2"),
        ("dataset_manifest_id", "dataset_manifest_product_2"),
        ("dataset_version", "1.0.1"),
    ],
)
def test_authority_identity_changes_are_collision_safe(change: str, value: object):
    handoffs = _handoffs()
    authority = _authority_input(handoffs)
    first = _compose(handoffs, authority_input=authority)
    second = _compose(handoffs, authority_input=replace(authority, **{change: value}))
    assert first.composition_id != second.composition_id


def test_split_group_content_source_and_review_changes_are_collision_safe():
    handoffs = _handoffs()
    authority = _authority_input(handoffs)
    baseline = _compose(handoffs, authority_input=authority)
    swapped = (
        replace(
            authority.allocations[0], split="validation", group_key="group_validation_2"
        ),
        replace(authority.allocations[1], split="train", group_key="group_train_2"),
        authority.allocations[2],
    )
    assert (
        _compose(
            handoffs, authority_input=replace(authority, allocations=swapped)
        ).composition_id
        != baseline.composition_id
    )
    group_changed = replace(authority.allocations[0], group_key="group_train_2")
    assert (
        _compose(
            handoffs,
            authority_input=replace(
                authority, allocations=(group_changed, *authority.allocations[1:])
            ),
        ).composition_id
        != baseline.composition_id
    )
    changed = replace(handoffs[0], review_evidence_reference="review:train:changed")
    changed = replace(
        changed,
        handoff_id=f"handoff:{checksum_value(handoff_module._handoff_projection(changed))}",
    )
    values = (changed, *handoffs[1:])
    assert (
        _compose(values, authority_input=_authority_input(values)).composition_id
        != baseline.composition_id
    )
    source_changed = replace(
        handoffs[0],
        input_references=(
            replace(handoffs[0].input_references[0], object_id="source_train_changed"),
        ),
    )
    source_changed = replace(
        source_changed,
        handoff_id=(
            f"handoff:{checksum_value(handoff_module._handoff_projection(source_changed))}"
        ),
    )
    source_values = (source_changed, *handoffs[1:])
    assert (
        _compose(
            source_values,
            authority_input=_authority_input(source_values),
        ).composition_id
        != baseline.composition_id
    )


def test_result_and_inputs_are_immutable_and_raw_payload_is_not_preserved():
    handoffs = _handoffs()
    result = _compose(handoffs)
    with pytest.raises(FrozenInstanceError):
        result.dataset_id = "changed"
    assert handoffs == _handoffs()
    assert not hasattr(result, "raw_payload")
    assert not hasattr(result.members[0], "raw_payload")


def test_mapping_builder_rejects_tampered_composition_identity():
    result = _compose()
    with pytest.raises(
        ProductDatasetCompositionError,
        match="COMPOSITION_IDENTITY_MISMATCH",
    ):
        build_dataset_version_proposal_mapping(
            replace(result, content_fingerprint="sha256:" + "f" * 64)
        )


def test_no_governance_publication_training_or_promotion_calls_exist():
    tree = ast.parse(inspect.getsource(composition_module))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called & {
        "propose_dataset_version",
        "begin_dataset_review",
        "approve_dataset_version",
        "publish_dataset_version",
        "run_training",
        "evaluate_model",
        "promote_model",
    }
