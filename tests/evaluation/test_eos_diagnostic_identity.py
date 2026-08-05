from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from src.evaluation.eos_diagnostic_artifacts import EXACT_ARTIFACT_FILENAMES
from src.evaluation.eos_diagnostic_identity import (
    BackendIdentity,
    CandidateBEvaluationBinding,
    CheckpointIdentity,
    DependencyEntry,
    DependencyIdentity,
    EOSDiagnosticIdentityError,
    PromptSetIdentity,
    TokenizerIdentity,
    build_r1_management_artifacts,
    evaluate_eos_diag_1,
    evaluate_eos_diag_2,
    freeze_checkpoint_identity,
    freeze_prompt_set_identity,
    freeze_tokenizer_identity,
)
from src.evaluation.eos_generation_matrix import (
    EOSDiagnosticGenerationError,
    GenerationMatrix,
    supported_generation_profiles,
)

FP = lambda character: "sha256:" + character * 64
SHA = "1" * 40


def _checkpoint(**overrides: object) -> CheckpointIdentity:
    values: dict[str, object] = {
        "checkpoint_id": "synthetic-not-for-runtime-candidate-b-final",
        "checkpoint_step": 12208,
        "checkpoint_checksum": FP("2"),
        "checkpoint_manifest_fingerprint": FP("3"),
        "model_config_fingerprint": FP("4"),
        "training_run_id": "SYNTHETIC-FULL-PRETRAIN-CANDIDATE-B-20990101-0001",
        "training_source_commit": SHA,
        "evaluation_id": "synthetic-candidate-b-final-full-20990101-01",
        "evaluation_fingerprint": FP("5"),
        "architecture_id": "DohaLM-Tiny",
        "parameter_count": 16889856,
        "dtype_contract": "cuda-fp16-evaluation-only",
        "immutable": True,
    }
    values.update(overrides)
    return CheckpointIdentity.create(**values)


def _tokenizer(**overrides: object) -> TokenizerIdentity:
    values: dict[str, object] = {
        "tokenizer_id": "synthetic-operating-16k-v2:unigram-16k",
        "tokenizer_version": "operating-16k-v2",
        "tokenizer_fingerprint": FP("6"),
        "tokenizer_manifest_checksum": FP("7"),
        "model_checksum": FP("8"),
        "vocab_checksum": FP("9"),
        "vocabulary_size": 16000,
        "pad_token_id": 0,
        "bos_token_id": 2,
        "eos_token_id": 3,
        "unk_token_id": 1,
        "tokenizer_type": "unigram",
        "normalization_policy": "identity",
        "round_trip_status": "exact_roundtrip_verified",
        "unknown_rate_status": "zero_on_declared_sample",
        "source_commit": SHA,
        "compatibility_fingerprint": FP("a"),
    }
    values.update(overrides)
    return TokenizerIdentity.create(**values)


def _prompt(**overrides: object) -> PromptSetIdentity:
    values: dict[str, object] = {
        "prompt_set_id": "synthetic-not-for-runtime-candidate-b-prompts",
        "prompt_set_version": "v1",
        "prompt_fingerprint": FP("b"),
        "prompt_count": 15,
        "category_counts": {f"category-{index:02d}": 1 for index in range(15)},
        "context_class_counts": {"minimal": 1, "short": 12, "medium": 1, "long": 1},
        "token_length_distribution": {"1-32": 8, "33-64": 5, "65-128": 2},
        "normalization_policy": "identity",
        "pii_status": "synthetic_pii_free",
        "leakage_status": "synthetic_no_dataset_source",
        "source_evidence_id": "synthetic-prompt-evidence-v1",
        "source_evidence_fingerprint": FP("c"),
        "immutable": True,
    }
    values.update(overrides)
    return PromptSetIdentity.create(**values)


def _binding(
    checkpoint: CheckpointIdentity,
    tokenizer: TokenizerIdentity,
    prompt: PromptSetIdentity,
    **overrides: object,
) -> CandidateBEvaluationBinding:
    values: dict[str, object] = {
        "training_run_id": checkpoint.training_run_id,
        "checkpoint_checksum": checkpoint.checkpoint_checksum,
        "model_config_fingerprint": checkpoint.model_config_fingerprint,
        "evaluation_id": checkpoint.evaluation_id,
        "evaluation_fingerprint": checkpoint.evaluation_fingerprint,
        "architecture_id": checkpoint.architecture_id,
        "parameter_count": checkpoint.parameter_count,
        "tokenizer_fingerprint": tokenizer.tokenizer_fingerprint,
        "tokenizer_compatibility_fingerprint": tokenizer.compatibility_fingerprint,
        "prompt_fingerprint": prompt.prompt_fingerprint,
        "training_source_commit": checkpoint.training_source_commit,
    }
    values.update(overrides)
    return CandidateBEvaluationBinding(**values)  # type: ignore[arg-type]


def _backend(**overrides: object) -> BackendIdentity:
    values: dict[str, object] = {
        "backend_name": "synthetic-eos-diagnostic-backend",
        "backend_version": "r2",
        "source_commit": SHA,
        "module_fingerprints": {
            "eos_diagnostic_identity.py": FP("d"),
            "eos_generation_matrix.py": FP("e"),
        },
        "config_schema_version": "2",
        "artifact_schema_version": "1",
    }
    values.update(overrides)
    return BackendIdentity.create(**values)


def _dependency(**overrides: object) -> DependencyIdentity:
    values: dict[str, object] = {
        "python_version": "3.11.9",
        "torch_version": "2.7.1+cu128",
        "cuda_build": "12.8",
        "cudnn_version": "9.7",
        "platform": "synthetic-windows-x86_64",
        "dependency_entries": [
            {
                "name": "python",
                "version": "3.11.9",
                "required": True,
                "source": "synthetic-explicit-input",
            },
            {
                "name": "torch",
                "version": "2.7.1+cu128",
                "required": True,
                "source": "synthetic-explicit-input",
            },
        ],
    }
    values.update(overrides)
    return DependencyIdentity.create(**values)


def _matrix() -> GenerationMatrix:
    return GenerationMatrix.create(
        matrix_id="synthetic-not-for-runtime-candidate-b-matrix-v1",
        profiles=supported_generation_profiles(),
    )


def test_complete_identities_are_frozen_immutable_and_deterministic() -> None:
    checkpoint, tokenizer, prompt = _checkpoint(), _tokenizer(), _prompt()
    assert freeze_checkpoint_identity(checkpoint).status == "frozen"
    assert freeze_tokenizer_identity(tokenizer).status == "frozen"
    assert freeze_prompt_set_identity(prompt).status == "frozen"
    assert checkpoint.identity_fingerprint == _checkpoint().identity_fingerprint
    assert tokenizer.identity_fingerprint == _tokenizer().identity_fingerprint
    assert prompt.identity_fingerprint == _prompt().identity_fingerprint
    with pytest.raises(FrozenInstanceError):
        checkpoint.checkpoint_step = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    ("factory", "overrides", "code"),
    [
        (
            _checkpoint,
            {"checkpoint_checksum": "bad"},
            "EOS_DIAG_CHECKPOINT_IDENTITY_INVALID",
        ),
        (_checkpoint, {"checkpoint_step": 0}, "EOS_DIAG_CHECKPOINT_IDENTITY_INVALID"),
        (
            _tokenizer,
            {"tokenizer_fingerprint": "bad"},
            "EOS_DIAG_TOKENIZER_IDENTITY_INVALID",
        ),
        (_tokenizer, {"vocabulary_size": 0}, "EOS_DIAG_TOKENIZER_IDENTITY_INVALID"),
    ],
)
def test_identity_constructors_reject_invalid_values(
    factory, overrides, code: str
) -> None:
    with pytest.raises(EOSDiagnosticIdentityError, match=f"^{code}$"):
        factory(**overrides)


def test_incomplete_manifest_and_prompt_fields_fail_closed() -> None:
    assert (
        freeze_checkpoint_identity(
            _checkpoint(checkpoint_manifest_fingerprint=None)
        ).status
        == "incomplete"
    )
    assert (
        freeze_prompt_set_identity(_prompt(prompt_set_id=None)).status == "incomplete"
    )
    assert (
        freeze_prompt_set_identity(_prompt(token_length_distribution=None)).status
        == "incomplete"
    )


def test_tokenizer_special_contract_and_prompt_counts_are_incompatible() -> None:
    assert (
        freeze_tokenizer_identity(_tokenizer(eos_token_id=4)).status == "incompatible"
    )
    assert (
        freeze_prompt_set_identity(_prompt(category_counts={"only": 1})).status
        == "incompatible"
    )
    assert (
        freeze_prompt_set_identity(_prompt(context_class_counts={"short": 14})).status
        == "incompatible"
    )


def test_identity_loaders_reject_unknown_fields_and_fingerprint_tamper() -> None:
    for identity, loader, field in (
        (_checkpoint(), CheckpointIdentity.from_mapping, "identity_fingerprint"),
        (_tokenizer(), TokenizerIdentity.from_mapping, "identity_fingerprint"),
        (_prompt(), PromptSetIdentity.from_mapping, "identity_fingerprint"),
        (_backend(), BackendIdentity.from_mapping, "backend_fingerprint"),
        (_dependency(), DependencyIdentity.from_mapping, "dependency_fingerprint"),
    ):
        value = identity.as_dict()
        value["unknown"] = True
        with pytest.raises(EOSDiagnosticIdentityError):
            loader(value)

    prompt_value = _prompt().as_dict()
    prompt_value["prompt_text"] = "must-not-be-accepted"
    with pytest.raises(
        EOSDiagnosticIdentityError, match="^EOS_DIAG_PROMPT_SET_IDENTITY_INVALID$"
    ):
        PromptSetIdentity.from_mapping(prompt_value)
        value = identity.as_dict()
        value[field] = FP("f")
        with pytest.raises(EOSDiagnosticIdentityError):
            loader(value)


def test_dependency_order_is_canonical_and_duplicates_are_rejected() -> None:
    entries = list(reversed(_dependency().as_dict()["dependency_entries"]))
    assert (
        _dependency(dependency_entries=entries).dependency_fingerprint
        == _dependency().dependency_fingerprint
    )
    duplicate = [
        DependencyEntry("python", "3.11.9", True, "synthetic-explicit-input"),
        DependencyEntry("python", "3.11.9", True, "synthetic-explicit-input"),
    ]
    with pytest.raises(
        EOSDiagnosticIdentityError, match="^EOS_DIAG_DEPENDENCY_IDENTITY_INVALID$"
    ):
        _dependency(dependency_entries=duplicate)
    with pytest.raises(
        EOSDiagnosticIdentityError, match="^EOS_DIAG_DEPENDENCY_IDENTITY_INVALID$"
    ):
        _dependency(python_version="invalid version")


def test_backend_rejects_absolute_module_paths() -> None:
    with pytest.raises(
        EOSDiagnosticIdentityError, match="^EOS_DIAG_BACKEND_IDENTITY_INVALID$"
    ):
        _backend(module_fingerprints={"C:/private/backend.py": FP("d")})


def test_eos_diag_1_synthetic_passes_but_incomplete_and_lineage_mismatch_block() -> (
    None
):
    checkpoint, tokenizer, prompt = _checkpoint(), _tokenizer(), _prompt()
    passed = evaluate_eos_diag_1(
        checkpoint, tokenizer, prompt, _binding(checkpoint, tokenizer, prompt)
    )
    assert passed.status == "passed"
    assert (
        passed.evidence_fingerprint
        == evaluate_eos_diag_1(
            checkpoint, tokenizer, prompt, _binding(checkpoint, tokenizer, prompt)
        ).evidence_fingerprint
    )
    assert (
        evaluate_eos_diag_1(
            checkpoint,
            tokenizer,
            _prompt(prompt_set_id=None),
            _binding(checkpoint, tokenizer, prompt),
        ).status
        == "blocked"
    )
    assert (
        evaluate_eos_diag_1(
            checkpoint,
            tokenizer,
            prompt,
            _binding(
                checkpoint,
                tokenizer,
                prompt,
                tokenizer_compatibility_fingerprint=FP("f"),
            ),
        ).status
        == "blocked"
    )
    assert (
        evaluate_eos_diag_1(
            checkpoint,
            tokenizer,
            prompt,
            _binding(checkpoint, tokenizer, prompt, evaluation_id="mismatch"),
        ).status
        == "blocked"
    )


def test_eos_diag_2_synthetic_passes_and_blocks_dependency_or_matrix_contract() -> None:
    matrix, backend, dependency = _matrix(), _backend(), _dependency()
    passed = evaluate_eos_diag_2(
        matrix,
        backend,
        dependency,
        artifact_set=EXACT_ARTIFACT_FILENAMES,
        source_commit=SHA,
    )
    assert passed.status == "passed"
    assert (
        evaluate_eos_diag_2(
            matrix,
            backend,
            _dependency(cudnn_version=None),
            artifact_set=EXACT_ARTIFACT_FILENAMES,
            source_commit=SHA,
        ).status
        == "blocked"
    )
    assert (
        evaluate_eos_diag_2(
            matrix,
            backend,
            dependency,
            artifact_set=EXACT_ARTIFACT_FILENAMES[:-1],
            source_commit=SHA,
        ).status
        == "blocked"
    )
    assert (
        evaluate_eos_diag_2(
            matrix,
            backend,
            dependency,
            artifact_set=EXACT_ARTIFACT_FILENAMES,
            source_commit="2" * 40,
        ).status
        == "blocked"
    )


def test_r1_payload_builder_passes_strict_schema_and_binds_identity_fingerprints() -> (
    None
):
    checkpoint, tokenizer, prompt = _checkpoint(), _tokenizer(), _prompt()
    matrix, backend, dependency = _matrix(), _backend(), _dependency()
    gate_1 = evaluate_eos_diag_1(
        checkpoint, tokenizer, prompt, _binding(checkpoint, tokenizer, prompt)
    )
    gate_2 = evaluate_eos_diag_2(
        matrix,
        backend,
        dependency,
        artifact_set=EXACT_ARTIFACT_FILENAMES,
        source_commit=SHA,
    )
    artifacts = build_r1_management_artifacts(
        diagnostic_run_id="SYNTHETIC-DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-20990101-0002",
        created_at="2099-01-01T00:00:00Z",
        source_commit=SHA,
        checkpoint=checkpoint,
        tokenizer=tokenizer,
        prompt_set=prompt,
        matrix=matrix,
        gate_1=gate_1,
        gate_2=gate_2,
    )
    assert tuple(artifact.artifact_type for artifact in artifacts) == (
        "diagnostic_run_manifest",
        "checkpoint_identity",
        "tokenizer_identity",
        "prompt_set_identity",
        "generation_matrix",
        "output_manifest",
    )
    assert all(
        artifact.checkpoint_identity_fingerprint == checkpoint.identity_fingerprint
        for artifact in artifacts
    )
    assert all(artifact.payload.get("status") != "completed" for artifact in artifacts)


def test_r1_payload_builder_rejects_real_namespace_blocked_gate_and_fingerprint_drift() -> (
    None
):
    checkpoint, tokenizer, prompt = _checkpoint(), _tokenizer(), _prompt()
    matrix, backend, dependency = _matrix(), _backend(), _dependency()
    gate_1 = evaluate_eos_diag_1(
        checkpoint, tokenizer, prompt, _binding(checkpoint, tokenizer, prompt)
    )
    gate_2 = evaluate_eos_diag_2(
        matrix,
        backend,
        dependency,
        artifact_set=EXACT_ARTIFACT_FILENAMES,
        source_commit=SHA,
    )
    arguments = {
        "diagnostic_run_id": "DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-20990101-0002",
        "created_at": "2099-01-01T00:00:00Z",
        "source_commit": SHA,
        "checkpoint": checkpoint,
        "tokenizer": tokenizer,
        "prompt_set": prompt,
        "matrix": matrix,
        "gate_1": gate_1,
        "gate_2": gate_2,
    }
    with pytest.raises(
        EOSDiagnosticIdentityError, match="^EOS_DIAG_R1_PAYLOAD_INCOMPATIBLE$"
    ):
        build_r1_management_artifacts(**arguments)
    arguments["diagnostic_run_id"] = (
        "SYNTHETIC-DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-20990101-0002"
    )
    arguments["gate_1"] = replace(gate_1, status="blocked")
    with pytest.raises(EOSDiagnosticIdentityError, match="^EOS_DIAG_GATE_NOT_READY$"):
        build_r1_management_artifacts(**arguments)

    arguments["gate_1"] = replace(gate_1, evidence_fingerprint=FP("0"))
    with pytest.raises(
        EOSDiagnosticIdentityError, match="^EOS_DIAG_R1_PAYLOAD_INCOMPATIBLE$"
    ):
        build_r1_management_artifacts(**arguments)


def test_gate_revalidates_direct_dataclass_fingerprint_tampering() -> None:
    checkpoint, tokenizer, prompt = _checkpoint(), _tokenizer(), _prompt()
    tampered = replace(checkpoint, identity_fingerprint=FP("0"))
    with pytest.raises(
        EOSDiagnosticIdentityError, match="^EOS_DIAG_CHECKPOINT_IDENTITY_INVALID$"
    ):
        evaluate_eos_diag_1(
            tampered, tokenizer, prompt, _binding(checkpoint, tokenizer, prompt)
        )

    matrix = replace(_matrix(), matrix_fingerprint=FP("0"))
    with pytest.raises(
        EOSDiagnosticGenerationError, match="^EOS_DIAG_GENERATION_MATRIX_INVALID$"
    ):
        evaluate_eos_diag_2(
            matrix,
            _backend(),
            _dependency(),
            artifact_set=EXACT_ARTIFACT_FILENAMES,
            source_commit=SHA,
        )
