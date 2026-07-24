from __future__ import annotations

from src.training.pilot_readiness import evaluate_pilot_readiness


FINGERPRINT = "sha256:" + "a" * 64


def test_readiness_reports_tokenizer_and_corpus_blockers() -> None:
    report = evaluate_pilot_readiness({})
    codes = {item["code"] for item in report["blocking_reasons"]}
    assert report["status"] == "blocked"
    assert {"TOKENIZER_NOT_APPROVED", "TOKENIZER_FINGERPRINT_MISSING", "CORPUS_NOT_APPROVED"}.issubset(codes)


def test_readiness_reports_license_pii_split_and_evaluation_blockers() -> None:
    report = evaluate_pilot_readiness({"corpus": {"approval_status": "approved_tokenizer_development"}})
    codes = {item["code"] for item in report["blocking_reasons"]}
    assert {"LICENSE_NOT_APPROVED", "PII_NOT_CLEARED", "SPLIT_NOT_VERIFIED", "EVALUATION_EXCLUSION_MISSING"}.issubset(codes)


def test_full_fixture_is_ready_for_user_approval() -> None:
    report = evaluate_pilot_readiness({
        "gates": {"3": "passed", "4": "passed", "5": "passed", "6": "passed", "7": "passed"},
        "tokenizer": {
            "approval_status": "approved", "fingerprint": FINGERPRINT,
            "vocab_size": 16_000, "special_token_ids": list(range(8)),
        },
        "corpus": {
            "approval_status": "approved_tokenizer_development", "license_status": "approved",
            "pii_status": "clear", "manifest_checksum": FINGERPRINT,
            "split_verified": True, "evaluation_exclusion_verified": True,
            "dataset_fingerprint": FINGERPRINT,
        },
        "training": {
            "checkpoint_retention_approved": True, "config_approved": True,
            "scheduler_approved": True, "batch_policy_approved": True,
            "estimate_verified": True, "resume_procedure_documented": True,
        },
        "storage": {"verified": True},
    })
    assert report["status"] == "ready_for_user_approval"
    assert report["eligible"] is True and report["blocking_reasons"] == []
    assert report["approved_by"] is None and report["approved_at"] is None
