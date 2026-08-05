"""Synthetic, fake, not_for_runtime V03-R2 contract tests.

Fixtures contain no real dataset, person, benchmark, or runtime secret.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.data.v03_evidence import make_v03_evidence_artifact, v03_fingerprint
from src.data.v03_exclusion import (
    V03ExclusionError,
    build_evaluation_exclusion_manifest_payload,
    build_exclusion_manifest,
    build_leakage_scan_summary_payload,
    build_pii_review_evidence_payload,
    build_pii_scan_summary_payload,
    build_safety_review_evidence_payload,
    build_safety_scan_summary_payload,
)
from src.data.v03_review import (
    ReviewPolicy,
    V03ReviewError,
    finalize_scan_reviews,
    make_finding_review,
)
from src.data.v03_scanning import (
    PII_CATEGORIES,
    SAFETY_CATEGORIES,
    LeakageScannerConfig,
    SyntheticBenchmarkRecord,
    SyntheticRecord,
    V03ScanningError,
    make_opaque_record_reference,
    scan_leakage_records,
    scan_pii_records,
    scan_safety_records,
)

SECRET = b"synthetic-fixed-secret-not_for_runtime-0001"
DATASET_ID = "synthetic-dataset-no_real_dataset"
DATASET_FP = "sha256:" + "1" * 64
REVIEWER = "opaque-reviewer:v1:" + "2" * 64
MARKERS = (
    "synthetic",
    "fake",
    "not_for_runtime",
    "no_real_dataset",
    "no_real_person",
    "no_real_benchmark",
)


def record(
    record_id: str,
    instruction: str,
    output: str = "synthetic clean output",
    split: str = "train",
) -> SyntheticRecord:
    return SyntheticRecord(
        record_id,
        split,
        instruction,
        output,
        {"fixture_markers": MARKERS},
        v03_fingerprint({"synthetic": record_id}),
    )


def reviews_for(scan, decision: str = "exclude"):
    return [
        make_finding_review(
            finding=item,
            reviewer_id=REVIEWER,
            decision=decision,
            reason_code="SYNTHETIC_POLICY_DECISION",
        )
        for item in scan.findings
    ]


def test_opaque_reference_is_deterministic_domain_separated_and_non_disclosing() -> (
    None
):
    kwargs = {
        "dataset_id": DATASET_ID,
        "source_record_id": "private-synthetic-source-id",
        "namespace": "pii",
        "secret": SECRET,
    }
    reference = make_opaque_record_reference(**kwargs)
    assert reference == make_opaque_record_reference(**kwargs)
    assert reference.startswith("opaque:v1:") and len(reference) == 74
    assert reference != make_opaque_record_reference(
        **(kwargs | {"namespace": "safety"})
    )
    assert reference != make_opaque_record_reference(
        **(kwargs | {"dataset_id": "synthetic-other"})
    )
    assert "private-synthetic-source-id" not in reference
    with pytest.raises(V03ScanningError, match="^V03_OPAQUE_REFERENCE_INVALID$"):
        make_opaque_record_reference(**(kwargs | {"secret": b"short"}))
    with pytest.raises(V03ScanningError, match="^V03_OPAQUE_REFERENCE_INVALID$"):
        make_opaque_record_reference(
            dataset_id=DATASET_ID, source_record_id="id", namespace="pii", secret=b""
        )


@pytest.mark.parametrize("category", PII_CATEGORIES)
def test_each_pii_category_uses_synthetic_marker_without_text_output(
    category: str,
) -> None:
    source_id = f"private-{category}"
    result = scan_pii_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[record(source_id, f"[synthetic-pii:{category}]")],
        secret=SECRET,
    )
    assert result.category_counts[category] == 1
    assert source_id not in repr(result)
    assert f"[synthetic-pii:{category}]" not in repr(result)
    assert all(
        not hasattr(item, "text") and not hasattr(item, "match")
        for item in result.findings
    )


def test_pii_fake_patterns_multiple_clean_invalid_and_config_fingerprint() -> None:
    rows = [
        record("fake-one", "fake@example.invalid and 000-0000-0000"),
        record("fake-clean", "clean synthetic sentence"),
    ]
    first = scan_pii_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=rows,
        secret=SECRET,
    )
    second = scan_pii_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=rows,
        secret=SECRET,
    )
    assert (
        first.findings == second.findings
        and first.findings_fingerprint == second.findings_fingerprint
    )
    assert first.category_counts["email"] == first.category_counts["phone_number"] == 1
    assert len(first.findings) == 2
    with pytest.raises(V03ScanningError, match="^V03_SCAN_INPUT_INVALID$"):
        record("bad", "text", split="test")
    with pytest.raises(V03ScanningError, match="^V03_SCAN_INPUT_INVALID$"):
        scan_pii_records(
            dataset_id=DATASET_ID,
            input_dataset_fingerprint="bad",
            records=[],
            secret=SECRET,
        )
    with pytest.raises(V03ScanningError, match="^V03_OPAQUE_REFERENCE_INVALID$"):
        scan_pii_records(
            dataset_id=DATASET_ID,
            input_dataset_fingerprint=DATASET_FP,
            records=[],
            secret=b"short",
        )


@pytest.mark.parametrize("category", SAFETY_CATEGORIES)
def test_each_safety_category_and_severity_is_deterministic(category: str) -> None:
    result = scan_safety_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[record("safe-fixture", f"[synthetic-safety:{category}]")],
        secret=SECRET,
    )
    assert result.category_counts[category] == 1
    assert result.findings[0].severity in {"medium", "high"}
    assert result == scan_safety_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[record("safe-fixture", f"[synthetic-safety:{category}]")],
        secret=SECRET,
    )


def test_safety_clean_and_multiple_categories() -> None:
    clean = scan_safety_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[record("clean", "ordinary fake fixture")],
        secret=SECRET,
    )
    assert not clean.findings
    multiple = scan_safety_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[
            record(
                "multi",
                "[synthetic-safety:privacy] [synthetic-safety:prompt_injection]",
            )
        ],
        secret=SECRET,
    )
    assert len(multiple.findings) == 2


def test_leakage_exact_normalized_cross_split_prompt_answer_and_prior_evaluation() -> (
    None
):
    rows = [
        record("train-a", "Synthetic Prompt", "Synthetic Answer"),
        record(
            "validation-b",
            "  synthetic   prompt ",
            "synthetic answer",
            split="validation",
        ),
        record("train-c", "Synthetic Prompt", "different answer"),
    ]
    benchmarks = [
        SyntheticBenchmarkRecord(
            "fake-benchmark-record",
            "Synthetic Prompt",
            "Synthetic Answer",
            "fake-benchmark",
            "synthetic-v1",
            v03_fingerprint({"benchmark": "fake"}),
        )
    ]
    result = scan_leakage_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=rows,
        benchmark_records=benchmarks,
        secret=SECRET,
    )
    for category in (
        "normalized_duplicate",
        "train_validation_overlap",
        "prompt_overlap",
        "answer_overlap",
        "duplicate_prompt",
        "duplicate_answer",
        "duplicate_qa_pair",
        "prior_evaluation_overlap",
    ):
        assert result.category_counts[category] > 0
    assert "fake-benchmark-record" not in repr(result)


def test_leakage_near_threshold_no_overlap_and_config_fingerprint() -> None:
    rows = [
        record("a", "alpha beta gamma delta", "one two three four"),
        record("b", "alpha beta gamma epsilon", "one two three five"),
    ]
    high = scan_leakage_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=rows,
        benchmark_records=[],
        secret=SECRET,
        config=LeakageScannerConfig(near_duplicate_threshold=0.9),
    )
    low_config = LeakageScannerConfig(near_duplicate_threshold=0.5)
    low = scan_leakage_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=rows,
        benchmark_records=[],
        secret=SECRET,
        config=low_config,
    )
    assert high.category_counts["near_duplicate"] == 0
    assert low.category_counts["near_duplicate"] == 1
    assert high.config_fingerprint != low.config_fingerprint
    none = scan_leakage_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[record("single", "unrelated", "unique")],
        benchmark_records=[],
        secret=SECRET,
    )
    assert not none.findings


def test_review_decisions_policy_duplicate_identity_incomplete_and_determinism() -> (
    None
):
    scan = scan_pii_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[record("r", "[synthetic-pii:user_identifier] [synthetic-pii:email]")],
        secret=SECRET,
    )
    decisions = [
        make_finding_review(
            finding=scan.findings[0],
            reviewer_id=REVIEWER,
            decision="dismiss",
            reason_code="SYNTHETIC_FALSE_POSITIVE",
        ),
        make_finding_review(
            finding=scan.findings[1],
            reviewer_id=REVIEWER,
            decision="exclude",
            reason_code="SYNTHETIC_EXCLUDE",
        ),
    ]
    result = finalize_scan_reviews(
        scan_result=scan, reviews=decisions, policy=ReviewPolicy()
    )
    assert (result.excluded_count, result.dismissed_count, result.review_decision) == (
        1,
        1,
        "passed",
    )
    assert (
        result.review_fingerprint
        == finalize_scan_reviews(
            scan_result=scan,
            reviews=list(reversed(decisions)),
            policy=ReviewPolicy(),
        ).review_fingerprint
    )
    assert (
        finalize_scan_reviews(
            scan_result=scan, reviews=decisions[:1], policy=ReviewPolicy()
        ).review_decision
        == "incomplete"
    )
    with pytest.raises(V03ReviewError, match="^V03_REVIEW_INVALID$"):
        finalize_scan_reviews(
            scan_result=scan,
            reviews=[decisions[0], decisions[0]],
            policy=ReviewPolicy(),
        )
    with pytest.raises(V03ReviewError, match="^V03_REVIEW_INVALID$"):
        finalize_scan_reviews(
            scan_result=scan,
            reviews=[
                replace(decisions[0], opaque_record_reference="opaque:v1:" + "0" * 64)
            ],
            policy=ReviewPolicy(),
        )


def test_review_retain_policy_and_unresolved() -> None:
    critical = scan_pii_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[record("critical", "[synthetic-pii:card_number]")],
        secret=SECRET,
    )
    with pytest.raises(V03ReviewError, match="^V03_REVIEW_POLICY_VIOLATION$"):
        finalize_scan_reviews(
            scan_result=critical,
            reviews=reviews_for(critical, "retain_with_review"),
            policy=ReviewPolicy(allow_high_retain=True),
        )
    high = scan_safety_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[record("high", "[synthetic-safety:prompt_injection]")],
        secret=SECRET,
    )
    with pytest.raises(V03ReviewError, match="^V03_REVIEW_POLICY_VIOLATION$"):
        finalize_scan_reviews(
            scan_result=high,
            reviews=reviews_for(high, "retain_with_review"),
            policy=ReviewPolicy(),
        )
    retained = finalize_scan_reviews(
        scan_result=high,
        reviews=reviews_for(high, "retain_with_review"),
        policy=ReviewPolicy(allow_high_retain=True),
    )
    assert retained.review_decision == "passed_with_conditions"
    unresolved = finalize_scan_reviews(
        scan_result=high, reviews=reviews_for(high, "unresolved"), policy=ReviewPolicy()
    )
    assert unresolved.review_decision == "blocked" and unresolved.high_unresolved == 1


def test_exclusion_deduplicates_sorts_aggregates_and_blocks_unresolved() -> None:
    scan = scan_pii_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[
            record("z", "[synthetic-pii:email] [synthetic-pii:phone_number]"),
            record("a", "[synthetic-pii:user_identifier]"),
        ],
        secret=SECRET,
    )
    result = finalize_scan_reviews(
        scan_result=scan, reviews=reviews_for(scan), policy=ReviewPolicy()
    )
    manifest = build_exclusion_manifest(
        canonical_dataset_fingerprint=DATASET_FP,
        scanner_reviews=[(scan, result), (scan, result)],
        policy=ReviewPolicy(),
    )
    assert manifest.excluded_record_count == 2
    assert manifest.opaque_record_references == tuple(
        sorted(manifest.opaque_record_references)
    )
    assert manifest.exclusion_reason_counts["SYNTHETIC_POLICY_DECISION"] == 2
    assert manifest.effective_dataset_fingerprint != DATASET_FP
    incomplete = finalize_scan_reviews(
        scan_result=scan, reviews=[], policy=ReviewPolicy()
    )
    with pytest.raises(V03ExclusionError, match="^V03_REVIEW_INCOMPLETE$"):
        build_exclusion_manifest(
            canonical_dataset_fingerprint=DATASET_FP,
            scanner_reviews=[(scan, incomplete)],
            policy=ReviewPolicy(),
        )
    with pytest.raises(V03ExclusionError, match="^V03_EXCLUSION_INVALID$"):
        build_exclusion_manifest(
            canonical_dataset_fingerprint="bad",
            scanner_reviews=[],
            policy=ReviewPolicy(),
        )


def _artifact(
    artifact_type: str,
    payload: dict[str, object],
    input_fingerprint: str,
    decision: str = "passed",
):
    return make_v03_evidence_artifact(
        artifact_type=artifact_type,
        artifact_id=f"synthetic-{artifact_type}",
        run_id="synthetic-run",
        dataset_id=DATASET_ID,
        source_commit="a" * 40,
        created_at="1970-01-01T00:00:00Z",
        writer_name="synthetic-writer",
        writer_version="v1",
        input_fingerprint=input_fingerprint,
        payload=payload,
        approval_status="not_approved",
        reviewer=(
            "synthetic-reviewer-not_for_runtime"
            if artifact_type in {"pii_review_evidence", "safety_review_evidence"}
            else None
        ),
        decision=decision,
    )


def test_all_r1_payload_adapters_pass_strict_schema_and_mismatch_fails() -> None:
    pii = scan_pii_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[record("pii", "[synthetic-pii:email]")],
        secret=SECRET,
    )
    safety = scan_safety_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[record("safety", "[synthetic-safety:privacy]")],
        secret=SECRET,
    )
    leakage = scan_leakage_records(
        dataset_id=DATASET_ID,
        input_dataset_fingerprint=DATASET_FP,
        records=[record("only", "unique prompt", "unique output")],
        benchmark_records=[],
        secret=SECRET,
    )
    pii_review = finalize_scan_reviews(
        scan_result=pii, reviews=reviews_for(pii), policy=ReviewPolicy()
    )
    safety_review = finalize_scan_reviews(
        scan_result=safety, reviews=reviews_for(safety), policy=ReviewPolicy()
    )
    leakage_review = finalize_scan_reviews(
        scan_result=leakage, reviews=[], policy=ReviewPolicy()
    )
    manifest = build_exclusion_manifest(
        canonical_dataset_fingerprint=DATASET_FP,
        scanner_reviews=[
            (pii, pii_review),
            (safety, safety_review),
            (leakage, leakage_review),
        ],
        policy=ReviewPolicy(),
    )
    benchmark_fp = v03_fingerprint({"synthetic": "benchmark"})
    payloads = {
        "pii_scan_summary": (
            build_pii_scan_summary_payload(scan_result=pii, review_result=pii_review),
            DATASET_FP,
        ),
        "pii_review_evidence": (
            build_pii_review_evidence_payload(
                scan_result=pii, review_result=pii_review
            ),
            pii.findings_fingerprint,
        ),
        "safety_scan_summary": (
            build_safety_scan_summary_payload(
                scan_result=safety, review_result=safety_review
            ),
            DATASET_FP,
        ),
        "safety_review_evidence": (
            build_safety_review_evidence_payload(
                scan_result=safety, review_result=safety_review
            ),
            safety.findings_fingerprint,
        ),
        "leakage_scan_summary": (
            build_leakage_scan_summary_payload(
                scan_result=leakage,
                review_result=leakage_review,
                benchmark_identity="synthetic-benchmark",
                benchmark_version="v1",
                benchmark_fingerprint=benchmark_fp,
            ),
            DATASET_FP,
        ),
        "evaluation_exclusion_manifest": (
            build_evaluation_exclusion_manifest_payload(manifest=manifest),
            DATASET_FP,
        ),
    }
    for artifact_type, (payload, input_fp) in payloads.items():
        assert (
            _artifact(artifact_type, payload, input_fp).artifact_type == artifact_type
        )
    with pytest.raises(V03ExclusionError, match="^V03_EVIDENCE_PAYLOAD_INCONSISTENT$"):
        build_pii_scan_summary_payload(
            scan_result=pii,
            review_result=replace(
                pii_review, findings_fingerprint="sha256:" + "0" * 64
            ),
        )
