from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_adr_008_and_model_stage_policy_are_approved() -> None:
    adr = _read("docs/decisions/ADR-008-eos-generation-and-decoding-evaluation-policy.md")
    policy = _read("docs/evaluation/eos-success-policy.md")

    assert "상태: `approved`" in adr
    assert "결정일: 2026-07-28" in adr
    assert "승인일: 2026-07-28" in adr
    assert "정책 상태: `approved`" in policy
    assert "Teacher-forced EOS" in policy and "Generation" in policy
    assert "Pure model" in policy and "Decoding-assisted" in policy
    assert "diagnostic_required" in policy
    assert "not_sufficient_as_single_failure_condition" in policy


def test_stage_contracts_keep_unapproved_boundaries() -> None:
    policy = _read("docs/evaluation/eos-success-policy.md")

    assert "instruct_eos_contract: approved_policy_framework" in policy
    assert "chat_eos_contract: approved_policy_framework" in policy
    assert policy.count("numeric_thresholds: proposed") == 2
    assert policy.count("training: not_approved") == 2
    assert "service_decoding_policy: proposed" in policy
    assert "implementation: not_started" in policy
    assert "16/32/64/128" in policy
    assert "historical 결과 소급 적용: `forbidden`" in policy


def test_candidate_b_historical_decision_is_not_reclassified() -> None:
    contract = _read("docs/evaluation/candidate-b-evaluation-contract.md")
    result = _read("docs/evaluation/candidate-b-final-full-result.md")
    status = _read("docs/project/current-project-status.md")
    policy = _read("docs/evaluation/eos-success-policy.md")

    for document in (contract, result, status, policy):
        assert "evaluated_contract_not_passed" in document
    assert "decoding_assisted_termination_only" in policy
    assert "approved_as_base_baseline" in policy
    assert "derivative parent eligibility" in policy
    assert "approved_experimental" in policy
    assert "Candidate A Final Full" in policy
    assert "Current official Base baseline" in status
    assert "`candidate_b`" in status
    assert "historical_base_baseline: true" in status


def test_historical_fingerprints_and_checksums_remain_pinned() -> None:
    candidate_a = _read("docs/evaluation/candidate-a-final-full-result.md")
    candidate_b = _read("docs/evaluation/candidate-b-final-full-result.md")
    diagnostic = _read("docs/evaluation/eos-generation-decoding-diagnostic-result.md")

    assert "sha256:1ec526e2dc6b1792f2d071fc788cd384ad3a22a0c2750df7437158153ca2d78d" in candidate_a
    assert "sha256:80f2aee72605ffcfeea13e158cbf7a132682591cf4295cd01c16f514686338f8" in candidate_a
    assert "sha256:7b796f3abed0d6bd7a2426f9dff619f0609f59a4e1d04bf232545548d25d9df0" in candidate_b
    assert "sha256:f3edc978db9d88e9de8e2e423a28291e9f35e2e163f0413c0e27e95facc55395" in candidate_b
    assert "sha256:db58082b055f36728d1abac1b9eeeb159daa08bd25b3fb870a7a66afc9a96026" in diagnostic
