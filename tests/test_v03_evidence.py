from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from src.data.v03_evidence import (
    ARTIFACT_FILENAMES,
    V03EvidenceError,
    calculate_bundle_fingerprint,
    calculate_effective_dataset_fingerprint,
    calculate_exclusion_fingerprint,
    calculate_inventory_fingerprint,
    canonical_v03_json_bytes,
    finalize_v03_evidence_bundle,
    load_v03_evidence,
    make_v03_evidence_artifact,
    serialize_v03_evidence,
    v03_fingerprint,
)
from src.data.v03_evidence_writer import write_v03_evidence


RUN_ID = "SYNTHETIC-FAKE-NOT_FOR_RUNTIME-NOT_APPROVED-NO_REAL_DATASET_PAYLOAD"
DATASET_ID = "SYNTHETIC-FAKE-NOT_FOR_RUNTIME-NO_REAL_DATASET_PAYLOAD"
SOURCE_COMMIT = "a" * 40
CREATED_AT = "2099-01-01T00:00:00Z"
MARKER = "synthetic:fake:not_for_runtime:not_approved:no_real_dataset_payload"
ZERO_SEVERITIES = {key: 0 for key in ("critical", "high", "medium", "low")}
ZERO_PII = {
    key: 0
    for key in (
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
ZERO_SAFETY = {
    key: 0
    for key in (
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
}


def _artifact(
    artifact_type: str,
    payload: dict[str, object],
    input_fingerprint: str,
    *,
    decision: str = "passed",
    run_id: str = RUN_ID,
    dataset_id: str = DATASET_ID,
):
    reviewer = (
        "synthetic-reviewer-not_for_runtime"
        if artifact_type
        in {"pii_review_evidence", "safety_review_evidence", "readiness_decision"}
        else None
    )
    return make_v03_evidence_artifact(
        artifact_type=artifact_type,
        artifact_id=f"synthetic-{artifact_type}-fake-not_for_runtime",
        run_id=run_id,
        dataset_id=dataset_id,
        source_commit=SOURCE_COMMIT,
        created_at=CREATED_AT,
        writer_name="synthetic_writer_not_for_runtime",
        writer_version="v1.synthetic",
        input_fingerprint=input_fingerprint,
        payload=payload,
        approval_status="not_approved",
        reviewer=reviewer,
        decision=decision,
    )


def _predecessor_artifacts(*, license_decision: str = "evidence_insufficient"):
    canonical = v03_fingerprint({"marker": MARKER, "kind": "canonical"})
    split = v03_fingerprint({"marker": MARKER, "kind": "split"})
    findings_pii = v03_fingerprint({"marker": MARKER, "kind": "pii_findings"})
    review_pii = v03_fingerprint({"marker": MARKER, "kind": "pii_review"})
    findings_safety = v03_fingerprint({"marker": MARKER, "kind": "safety_findings"})
    review_safety = v03_fingerprint({"marker": MARKER, "kind": "safety_review"})
    findings_leakage = v03_fingerprint({"marker": MARKER, "kind": "leakage_findings"})
    exclusion = calculate_exclusion_fingerprint(
        canonical_dataset_fingerprint=canonical,
        exclusion_reason_counts={},
        opaque_record_references=[],
    )
    effective = calculate_effective_dataset_fingerprint(
        canonical_dataset_fingerprint=canonical,
        evaluation_exclusion_fingerprint=exclusion,
    )
    inventory_entries = [
        {
            "logical_name": "synthetic_manifest",
            "relative_artifact_name": "synthetic/manifest.json",
            "checksum": v03_fingerprint({"marker": MARKER}),
            "size_bytes": 128,
            "status": "verified",
        }
    ]
    license_status = (
        "approved" if license_decision.startswith("ready") else "not_approved"
    )
    return {
        "license_evidence": _artifact(
            "license_evidence",
            {
                "provider": "synthetic_provider",
                "dataset_component": "sft",
                "permitted_purpose": ["synthetic_contract_testing"],
                "student_noncommercial": True,
                "sft_use_status": license_status,
                "derivative_dataset_status": license_status,
                "adapter_creation_status": license_status,
                "redistribution_status": "not_approved",
                "checkpoint_publication_status": "not_approved",
                "external_service_status": "not_approved",
                "cloud_status": "not_approved",
                "music_reuse_status": "not_approved",
                "commercial_transition_status": "not_approved",
                "evidence_references": [MARKER],
                "unresolved_questions": (
                    []
                    if license_decision.startswith("ready")
                    else ["LICENSE_EVIDENCE_INSUFFICIENT"]
                ),
                "decision": license_decision,
            },
            canonical,
            decision=license_decision,
        ),
        "dataset_lineage": _artifact(
            "dataset_lineage",
            {
                "source_dataset_id": "synthetic-source-not_for_runtime",
                "derived_dataset_id": DATASET_ID,
                "processing_run_ids": ["synthetic-processing-not_for_runtime"],
                "source_record_count": 10,
                "train_record_count": 8,
                "validation_record_count": 2,
                "exclusion_count": 0,
                "canonical_dataset_fingerprint": canonical,
                "effective_dataset_fingerprint": effective,
                "split_fingerprint": split,
                "source_checksums": {
                    "synthetic_source": v03_fingerprint({"marker": MARKER})
                },
                "derivation_method": "synthetic",
                "predecessor_run_id": None,
            },
            canonical,
        ),
        "checksum_inventory": _artifact(
            "checksum_inventory",
            {
                "algorithm": "sha256",
                "entries": inventory_entries,
                "inventory_fingerprint": calculate_inventory_fingerprint(
                    inventory_entries
                ),
            },
            canonical,
        ),
        "pii_scan_summary": _artifact(
            "pii_scan_summary",
            {
                "scanner_version": "synthetic-v1",
                "input_dataset_fingerprint": canonical,
                "scanned_record_count": 10,
                "finding_count_by_category": ZERO_PII,
                "finding_count_by_severity": ZERO_SEVERITIES,
                "unresolved_count": 0,
                "excluded_count": 0,
                "retained_with_review_count": 0,
                "findings_fingerprint": findings_pii,
                "scan_decision": "passed",
            },
            canonical,
        ),
        "pii_review_evidence": _artifact(
            "pii_review_evidence",
            {
                "reviewed_finding_count": 0,
                "unresolved_count": 0,
                "critical_unresolved": 0,
                "high_unresolved": 0,
                "medium_retained_count": 0,
                "reviewer_ids": ["synthetic-reviewer-not_for_runtime"],
                "reason_code_counts": {},
                "review_fingerprint": review_pii,
                "review_decision": "passed",
            },
            findings_pii,
        ),
        "safety_scan_summary": _artifact(
            "safety_scan_summary",
            {
                "category_counts": ZERO_SAFETY,
                "severity_counts": ZERO_SEVERITIES,
                "unresolved_count": 0,
                "excluded_count": 0,
                "retained_with_review_count": 0,
                "findings_fingerprint": findings_safety,
                "scan_decision": "passed",
            },
            canonical,
        ),
        "safety_review_evidence": _artifact(
            "safety_review_evidence",
            {
                "reviewed_finding_count": 0,
                "critical_retained_count": 0,
                "high_retained_count": 0,
                "medium_retained_count": 0,
                "unresolved_count": 0,
                "reviewer_ids": ["synthetic-reviewer-not_for_runtime"],
                "reason_code_counts": {},
                "review_fingerprint": review_safety,
                "review_decision": "passed",
            },
            findings_safety,
        ),
        "leakage_scan_summary": _artifact(
            "leakage_scan_summary",
            {
                "benchmark_identity": "synthetic-benchmark-not_for_runtime",
                "benchmark_version": "synthetic-v1",
                "benchmark_fingerprint": v03_fingerprint(
                    {"marker": MARKER, "kind": "benchmark"}
                ),
                "exact_duplicate_count": 0,
                "normalized_duplicate_count": 0,
                "near_duplicate_count": 0,
                "prompt_overlap_count": 0,
                "answer_overlap_count": 0,
                "template_contamination_count": 0,
                "train_validation_overlap_count": 0,
                "prior_evaluation_overlap_count": 0,
                "unresolved_count": 0,
                "exclusion_count": 0,
                "findings_fingerprint": findings_leakage,
                "scan_decision": "passed",
            },
            canonical,
        ),
        "evaluation_exclusion_manifest": _artifact(
            "evaluation_exclusion_manifest",
            {
                "exclusion_schema_version": 1,
                "canonical_dataset_fingerprint": canonical,
                "excluded_record_count": 0,
                "exclusion_reason_counts": {},
                "opaque_record_references": [],
                "exclusion_fingerprint": exclusion,
                "effective_dataset_fingerprint": effective,
            },
            canonical,
        ),
    }


def _bundle(
    root: Path,
    *,
    license_decision: str = "evidence_insufficient",
    overall_decision: str | None = None,
    predecessor_override=None,
):
    predecessor = predecessor_override or _predecessor_artifacts(
        license_decision=license_decision
    )
    license_decision = predecessor["license_evidence"].decision
    for artifact_type, artifact in predecessor.items():
        write_v03_evidence(
            destination=root / ARTIFACT_FILENAMES[artifact_type], artifact=artifact
        )
    fingerprint = calculate_bundle_fingerprint(predecessor)
    overall = overall_decision or (
        "ready_with_conditions"
        if license_decision == "ready_with_conditions"
        else license_decision
    )
    readiness = _artifact(
        "readiness_decision",
        {
            "license_decision": license_decision,
            "lineage_decision": "passed",
            "checksum_decision": "passed",
            "pii_decision": "passed",
            "safety_decision": "passed",
            "leakage_decision": "passed",
            "effective_dataset_decision": "passed",
            "overall_decision": overall,
            "blocking_reasons": (
                ["LICENSE_EVIDENCE_INSUFFICIENT"]
                if overall == "evidence_insufficient"
                else []
            ),
            "conditional_reasons": (
                ["LOCAL_NONCOMMERCIAL_ONLY"]
                if overall == "ready_with_conditions"
                else []
            ),
            "approved_next_actions": (
                ["fresh_tokenization_preflight"]
                if overall == "ready_with_conditions"
                else []
            ),
            "prohibited_actions": [
                "dataset_payload_read",
                "tokenization",
                "approval_issue",
                "run_reservation",
                "training",
                "gpu_execution",
            ],
            "evidence_bundle_fingerprint": fingerprint,
        },
        fingerprint,
        decision=overall,
    )
    write_v03_evidence(
        destination=root / ARTIFACT_FILENAMES["readiness_decision"],
        artifact=readiness,
    )
    return predecessor, readiness


@pytest.mark.parametrize("artifact_type", sorted(ARTIFACT_FILENAMES))
def test_each_artifact_has_a_valid_full_strict_schema(
    tmp_path: Path, artifact_type: str
) -> None:
    predecessor = _predecessor_artifacts()
    if artifact_type == "readiness_decision":
        _bundle(tmp_path)
        artifact = load_v03_evidence(tmp_path / ARTIFACT_FILENAMES[artifact_type])
    else:
        artifact = predecessor[artifact_type]
    assert artifact.artifact_type == artifact_type
    assert artifact.artifact_checksum.startswith("sha256:")


def test_canonical_serialization_and_fingerprints_are_deterministic() -> None:
    left = {"한글": 1, "marker": MARKER}
    right = {"marker": MARKER, "한글": 1}
    assert canonical_v03_json_bytes(left) == canonical_v03_json_bytes(right)
    assert v03_fingerprint(left) == v03_fingerprint(right)
    assert b" " not in canonical_v03_json_bytes(left)


def test_atomic_write_reload_and_immutable_results(tmp_path: Path) -> None:
    artifact = _predecessor_artifacts()["license_evidence"]
    path = tmp_path / ARTIFACT_FILENAMES[artifact.artifact_type]
    result = write_v03_evidence(destination=path, artifact=artifact)
    assert load_v03_evidence(path) == artifact
    assert path.read_bytes() == serialize_v03_evidence(artifact)
    assert result.bytes_written == len(path.read_bytes())
    with pytest.raises(TypeError):
        artifact.payload["provider"] = "mutated"  # type: ignore[index]
    assert "C:\\" not in repr(artifact)
    assert "C:\\" not in repr(result)


def test_atomic_no_replace_allows_exactly_one_concurrent_success(
    tmp_path: Path,
) -> None:
    artifact = _predecessor_artifacts()["license_evidence"]
    path = tmp_path / ARTIFACT_FILENAMES[artifact.artifact_type]

    def attempt() -> str:
        try:
            write_v03_evidence(destination=path, artifact=artifact)
            return "written"
        except V03EvidenceError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert results.count("written") == 1
    assert load_v03_evidence(path) == artifact


def test_complete_evidence_insufficient_bundle_finalizes(tmp_path: Path) -> None:
    _bundle(tmp_path)
    result = finalize_v03_evidence_bundle(
        bundle_root=tmp_path,
        expected_run_id=RUN_ID,
        expected_dataset_id=DATASET_ID,
    )
    assert result.overall_decision == "evidence_insufficient"
    assert "C:\\" not in repr(result)


def test_ready_with_conditions_requires_explicit_synthetic_conditions(
    tmp_path: Path,
) -> None:
    _bundle(tmp_path, license_decision="ready_with_conditions")
    result = finalize_v03_evidence_bundle(
        bundle_root=tmp_path,
        expected_run_id=RUN_ID,
        expected_dataset_id=DATASET_ID,
    )
    assert result.overall_decision == "ready_with_conditions"


def _write_raw(tmp_path: Path, value: object, raw: bytes | None = None) -> Path:
    path = tmp_path / "artifact.json"
    path.write_bytes(canonical_v03_json_bytes(value) if raw is None else raw)
    return path


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b'{"schema_version":1,"schema_version":1}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
    ],
)
def test_malformed_duplicate_and_nonfinite_json_are_rejected(
    tmp_path: Path, raw: bytes
) -> None:
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_INVALID$"):
        load_v03_evidence(_write_raw(tmp_path, {}, raw))


@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda value: value.update(extra="unknown"), "V03_EVIDENCE_INVALID"),
        (lambda value: value.pop("artifact_id"), "V03_EVIDENCE_INVALID"),
        (
            lambda value: value.update(schema_version=2),
            "V03_EVIDENCE_UNSUPPORTED_VERSION",
        ),
        (lambda value: value.update(source_commit="ABC"), "V03_EVIDENCE_INVALID"),
        (
            lambda value: value.update(created_at="2099-01-01T00:00:00+00:00"),
            "V03_EVIDENCE_INVALID",
        ),
        (lambda value: value.update(input_fingerprint="bad"), "V03_EVIDENCE_INVALID"),
    ],
)
def test_strict_top_level_failures(tmp_path: Path, mutation, code: str) -> None:
    value = _predecessor_artifacts()["license_evidence"].as_dict()
    mutation(value)
    with pytest.raises(V03EvidenceError, match=f"^{code}$"):
        load_v03_evidence(_write_raw(tmp_path, value))


@pytest.mark.parametrize("bad_count", [-1, True])
def test_negative_count_and_bool_as_int_are_rejected(bad_count: object) -> None:
    payload = dict(_predecessor_artifacts()["dataset_lineage"].payload)
    payload["source_record_count"] = bad_count
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_INVALID$"):
        _artifact("dataset_lineage", payload, payload["canonical_dataset_fingerprint"])  # type: ignore[arg-type]


def test_invalid_enum_and_path_traversal_are_rejected() -> None:
    predecessor = _predecessor_artifacts()
    license_payload = dict(predecessor["license_evidence"].payload)
    license_payload["sft_use_status"] = "unknown"
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_INVALID$"):
        _artifact(
            "license_evidence",
            license_payload,
            predecessor["license_evidence"].input_fingerprint,
            decision="evidence_insufficient",
        )
    inventory = dict(predecessor["checksum_inventory"].payload)
    entries = [dict(inventory["entries"][0])]
    entries[0]["relative_artifact_name"] = "../escape.json"
    inventory["entries"] = entries
    inventory["inventory_fingerprint"] = calculate_inventory_fingerprint(entries)
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_PATH_INVALID$"):
        _artifact(
            "checksum_inventory",
            inventory,
            predecessor["checksum_inventory"].input_fingerprint,
        )


def test_checksum_and_exclusion_fingerprint_mismatches_are_rejected(
    tmp_path: Path,
) -> None:
    artifact = _predecessor_artifacts()["license_evidence"]
    value = artifact.as_dict()
    value["artifact_checksum"] = "sha256:" + "0" * 64
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_CHECKSUM_MISMATCH$"):
        load_v03_evidence(_write_raw(tmp_path, value))

    exclusion = dict(_predecessor_artifacts()["evaluation_exclusion_manifest"].payload)
    exclusion["exclusion_fingerprint"] = "sha256:" + "0" * 64
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_CHECKSUM_MISMATCH$"):
        _artifact(
            "evaluation_exclusion_manifest",
            exclusion,
            exclusion["canonical_dataset_fingerprint"],
        )  # type: ignore[arg-type]


def test_destination_exists_and_wrong_name_fail_closed(tmp_path: Path) -> None:
    artifact = _predecessor_artifacts()["license_evidence"]
    path = tmp_path / ARTIFACT_FILENAMES[artifact.artifact_type]
    write_v03_evidence(destination=path, artifact=artifact)
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_ALREADY_EXISTS$"):
        write_v03_evidence(destination=path, artifact=artifact)
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_PATH_INVALID$"):
        write_v03_evidence(destination=tmp_path / "wrong.json", artifact=artifact)


def test_destination_symlink_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _predecessor_artifacts()["license_evidence"]
    link = tmp_path / ARTIFACT_FILENAMES[artifact.artifact_type]
    try:
        link.symlink_to(tmp_path / "synthetic-target")
    except OSError:
        original = Path.is_symlink
        monkeypatch.setattr(
            Path, "is_symlink", lambda self: self == link or original(self)
        )
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_PATH_INVALID$"):
        write_v03_evidence(destination=link, artifact=artifact)


def test_partial_and_duplicate_type_bundles_fail_closed(tmp_path: Path) -> None:
    predecessor = _predecessor_artifacts()
    write_v03_evidence(
        destination=tmp_path / ARTIFACT_FILENAMES["license_evidence"],
        artifact=predecessor["license_evidence"],
    )
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_BUNDLE_INCOMPLETE$"):
        finalize_v03_evidence_bundle(
            bundle_root=tmp_path, expected_run_id=RUN_ID, expected_dataset_id=DATASET_ID
        )

    duplicate_root = tmp_path / "duplicate"
    duplicate_root.mkdir()
    _bundle(duplicate_root)
    duplicate_root.joinpath(ARTIFACT_FILENAMES["dataset_lineage"]).write_bytes(
        duplicate_root.joinpath(ARTIFACT_FILENAMES["license_evidence"]).read_bytes()
    )
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_BUNDLE_INCONSISTENT$"):
        finalize_v03_evidence_bundle(
            bundle_root=duplicate_root,
            expected_run_id=RUN_ID,
            expected_dataset_id=DATASET_ID,
        )


def test_run_dataset_and_fingerprint_chain_mismatch_fail_closed(tmp_path: Path) -> None:
    _bundle(tmp_path)
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_BUNDLE_INCONSISTENT$"):
        finalize_v03_evidence_bundle(
            bundle_root=tmp_path,
            expected_run_id="synthetic-wrong-run",
            expected_dataset_id=DATASET_ID,
        )
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_BUNDLE_INCONSISTENT$"):
        finalize_v03_evidence_bundle(
            bundle_root=tmp_path,
            expected_run_id=RUN_ID,
            expected_dataset_id="synthetic-wrong-dataset",
        )
    readiness_path = tmp_path / ARTIFACT_FILENAMES["readiness_decision"]
    value = load_v03_evidence(readiness_path).as_dict()
    value["input_fingerprint"] = "sha256:" + "0" * 64
    value["artifact_checksum"] = ""
    value["artifact_checksum"] = v03_fingerprint(value)
    readiness_path.write_bytes(canonical_v03_json_bytes(value))
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_BUNDLE_INCONSISTENT$"):
        finalize_v03_evidence_bundle(
            bundle_root=tmp_path, expected_run_id=RUN_ID, expected_dataset_id=DATASET_ID
        )


def test_readiness_cannot_claim_stronger_state_than_evidence(tmp_path: Path) -> None:
    _bundle(tmp_path, overall_decision="ready")
    with pytest.raises(
        V03EvidenceError, match="^V03_EVIDENCE_READINESS_CONTRADICTION$"
    ):
        finalize_v03_evidence_bundle(
            bundle_root=tmp_path, expected_run_id=RUN_ID, expected_dataset_id=DATASET_ID
        )


@pytest.mark.parametrize(
    "artifact_type,field,value",
    [
        ("pii_scan_summary", "unresolved_count", 1),
        ("pii_scan_summary", "excluded_count", 1),
        ("pii_review_evidence", "critical_unresolved", 1),
        ("pii_review_evidence", "high_unresolved", 1),
        ("safety_scan_summary", "unresolved_count", 1),
        ("safety_scan_summary", "excluded_count", 1),
        ("safety_review_evidence", "critical_retained_count", 1),
        ("leakage_scan_summary", "unresolved_count", 1),
    ],
)
def test_ready_rejects_unresolved_or_critical_gate_evidence(
    tmp_path: Path,
    artifact_type: str,
    field: str,
    value: int,
) -> None:
    predecessor = _predecessor_artifacts(license_decision="ready")
    original = predecessor[artifact_type]
    payload = dict(original.payload)
    payload[field] = value
    predecessor[artifact_type] = _artifact(
        artifact_type,
        payload,
        original.input_fingerprint,
        decision=original.decision,
    )
    _bundle(tmp_path, overall_decision="ready", predecessor_override=predecessor)
    with pytest.raises(
        V03EvidenceError, match="^V03_EVIDENCE_READINESS_CONTRADICTION$"
    ):
        finalize_v03_evidence_bundle(
            bundle_root=tmp_path, expected_run_id=RUN_ID, expected_dataset_id=DATASET_ID
        )


def test_raw_field_absolute_path_and_noncanonical_json_are_rejected(
    tmp_path: Path,
) -> None:
    artifact = _predecessor_artifacts()["license_evidence"]
    payload = dict(artifact.payload)
    payload["evidence_references"] = [r"C:\\private\\evidence.json"]
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_PATH_INVALID$"):
        _artifact(
            "license_evidence",
            payload,
            artifact.input_fingerprint,
            decision="evidence_insufficient",
        )
    payload = dict(artifact.payload)
    payload["raw_text"] = "synthetic raw value"
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_INVALID$"):
        _artifact(
            "license_evidence",
            payload,
            artifact.input_fingerprint,
            decision="evidence_insufficient",
        )
    path = tmp_path / "noncanonical.json"
    path.write_text(json.dumps(artifact.as_dict(), indent=2), encoding="utf-8")
    with pytest.raises(V03EvidenceError, match="^V03_EVIDENCE_INVALID$"):
        load_v03_evidence(path)


def test_approved_and_prohibited_action_collision_is_rejected() -> None:
    predecessor = _predecessor_artifacts(license_decision="ready_with_conditions")
    fingerprint = calculate_bundle_fingerprint(predecessor)
    payload = {
        "license_decision": "ready_with_conditions",
        "lineage_decision": "passed",
        "checksum_decision": "passed",
        "pii_decision": "passed",
        "safety_decision": "passed",
        "leakage_decision": "passed",
        "effective_dataset_decision": "passed",
        "overall_decision": "ready_with_conditions",
        "blocking_reasons": [],
        "conditional_reasons": ["LOCAL_NONCOMMERCIAL_ONLY"],
        "approved_next_actions": ["fresh_tokenization_preflight"],
        "prohibited_actions": ["fresh_tokenization_preflight"],
        "evidence_bundle_fingerprint": fingerprint,
    }
    with pytest.raises(
        V03EvidenceError, match="^V03_EVIDENCE_READINESS_CONTRADICTION$"
    ):
        _artifact(
            "readiness_decision", payload, fingerprint, decision="ready_with_conditions"
        )
