from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_adr_009_approves_exactly_one_current_base_baseline() -> None:
    decision = _read("docs/decisions/ADR-009-candidate-b-official-reassessment.md")
    status = _read("docs/project/current-project-status.md")

    assert "문서 상태: `approved`" in decision
    assert "결정일: 2026-07-28" in decision
    assert "candidate_b_adr008_reassessment: approved_as_base_baseline" in decision
    assert "official_base_baseline: candidate_b" in decision
    assert "candidate_a_historical_base_baseline: true" in decision
    assert "Current official Base baseline" in status
    assert "`candidate_b`" in status


def test_historical_and_current_candidate_b_states_are_separate() -> None:
    decision = _read("docs/decisions/ADR-009-candidate-b-official-reassessment.md")
    result = _read("docs/evaluation/candidate-b-final-full-result.md")
    leaderboard = _read("docs/evaluation/model-evaluation-leaderboard.md")

    for document in (decision, result, leaderboard):
        assert "evaluated_contract_not_passed" in document
        assert "approved_as_base_baseline" in document
    assert "historical_result_mutation: forbidden" in decision
    assert "Candidate A Final Full | `completed` | `not_applicable` | `false` | `true`" in leaderboard
    assert "Candidate B Final Full | `evaluated_contract_not_passed` | `approved_as_base_baseline` | `true`" in leaderboard


def test_derivative_parent_does_not_approve_training_or_publication() -> None:
    decision = _read("docs/decisions/ADR-009-candidate-b-official-reassessment.md")
    status = _read("docs/project/current-project-status.md")

    assert "candidate_b_derivative_parent_eligibility: approved_experimental" in decision
    assert "Instruct·Chat·Domain CPT·SFT" in decision
    assert "실행 승인이 아니다" in decision
    assert "Model publication: `not_approved`" in decision
    assert "Checkpoint publication: `not_approved`" in decision
    assert "파생 학습·publication은 `not_approved`" in status


def test_service_decoding_and_additional_training_remain_closed() -> None:
    decision = _read("docs/decisions/ADR-009-candidate-b-official-reassessment.md")

    assert "service_decoding: deferred_to_instruct_chat_stage" in decision
    assert "service_decoding_implementation: not_approved" in decision
    assert "additional_base_pretraining: not_required" in decision
    assert "candidate_c: not_required" in decision
    assert "No-repeat bigram은 연구 후보로만 유지" in decision


def test_reassessment_preserves_all_pinned_artifact_identities() -> None:
    candidate_a = _read("docs/evaluation/candidate-a-final-full-result.md")
    candidate_b = _read("docs/evaluation/candidate-b-final-full-result.md")
    diagnostic = _read("docs/evaluation/eos-generation-decoding-diagnostic-result.md")
    readiness = _read("docs/training/candidate-b-readiness.manifest.yaml")

    assert "sha256:1ec526e2dc6b1792f2d071fc788cd384ad3a22a0c2750df7437158153ca2d78d" in candidate_a
    assert "sha256:80f2aee72605ffcfeea13e158cbf7a132682591cf4295cd01c16f514686338f8" in candidate_a
    assert "sha256:7b796f3abed0d6bd7a2426f9dff619f0609f59a4e1d04bf232545548d25d9df0" in candidate_b
    assert "sha256:f3edc978db9d88e9de8e2e423a28291e9f35e2e163f0413c0e27e95facc55395" in candidate_b
    assert "sha256:db58082b055f36728d1abac1b9eeeb159daa08bd25b3fb870a7a66afc9a96026" in diagnostic
    assert "sha256:0265e2d4b2ab94cd4f3df3afba14e671a58cc76b8e11434ebd64db36506f8790" in readiness
    assert "sha256:a0677dc18dbc98371d349aef0f83ea610ab4a984657412bd1518b883a66bd3c6" in readiness
    assert "sha256:dd71433c11a69345fed217620ba84b4ebc8b969b25400db07af9bc5ef0f4696f" in readiness
    assert "sha256:e7ad635dafa3f18a77a243ec17b2bcb9d5f29c72e081ad161bd63b2218e0680b" in readiness
    assert "sha256:9ce19a118a893fd69bad3124f94cea78f804d450a2ff6a9c4149b3064312f0ff" in readiness
    assert "sha256:a7a4d109c6d9f385bc65f33a0c5b9a0e9af218764b2e0648ea0c81b317fed106" in readiness
