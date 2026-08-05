from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from src.evaluation.eos_diagnostic_artifacts import (
    ARTIFACT_FILENAMES,
    EXACT_ARTIFACT_FILENAMES,
    EOSDiagnosticArtifactError,
    canonical_diagnostic_json_bytes,
    load_diagnostic_artifact,
    new_artifact_inventory,
    new_completion_evidence,
    new_diagnostic_artifact,
    serialize_diagnostic_artifact,
    validate_completed_bundle,
    write_diagnostic_artifact,
)

RUN_ID = "SYNTHETIC-DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-20990101-0001"
STAMP = "2099-01-01T00:00:00Z"
SOURCE_COMMIT = "1" * 40
CHECKPOINT_IDENTITY = "sha256:" + "2" * 64
TOKENIZER_IDENTITY = "sha256:" + "3" * 64
PROMPT_SET = "sha256:" + "4" * 64
GENERATION_MATRIX = "sha256:" + "5" * 64


@pytest.fixture
def synthetic_workspace() -> Path:
    path = Path(__file__).parent / ("r1_workspace_" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def _common(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "diagnostic_run_id": RUN_ID,
        "checkpoint_identity_fingerprint": CHECKPOINT_IDENTITY,
        "tokenizer_identity_fingerprint": TOKENIZER_IDENTITY,
        "prompt_set_fingerprint": PROMPT_SET,
        "generation_matrix_fingerprint": GENERATION_MATRIX,
        "source_commit": SOURCE_COMMIT,
        "created_at": STAMP,
    }
    value.update(overrides)
    return value


def _analysis_payload() -> dict[str, object]:
    return {
        "analysis_status": "schema_only",
        "record_schema_version": 1,
        "records": [],
        "summary": {},
        "limitations": ["SYNTHETIC_FIXTURE_ONLY"],
    }


def _payload(artifact_type: str) -> tuple[int, dict[str, object]]:
    if artifact_type == "diagnostic_run_manifest":
        return 1, {
            "purpose": "Synthetic schema rehearsal without model or payload access",
            "execution_mode": "synthetic_schema_rehearsal",
            "permissions": {
                "checkpoint_load": False,
                "tokenizer_load": False,
                "gpu": False,
                "generation": False,
                "checkpoint_write": False,
                "training": False,
            },
            "exact_artifact_set": list(EXACT_ARTIFACT_FILENAMES),
            "predecessor_diagnostic_run_id": None,
        }
    if artifact_type == "checkpoint_identity":
        return 1, {
            "checkpoint_id": "candidate-b-final",
            "checkpoint_checksum": "sha256:" + "6" * 64,
            "checkpoint_manifest_fingerprint": "sha256:" + "7" * 64,
            "model_config_fingerprint": "sha256:" + "8" * 64,
            "training_run_id": "FULL-PRETRAIN-CANDIDATE-B-20990101-0001",
            "training_source_commit": "9" * 40,
            "full_evaluation_id": "candidate-b-final-full-20990101-01",
            "read_only": True,
        }
    if artifact_type == "tokenizer_identity":
        return 1, {
            "tokenizer_id": "synthetic-tokenizer-v1",
            "bundle_checksum": "sha256:" + "a" * 64,
            "model_checksum": "sha256:" + "b" * 64,
            "vocab_checksum": "sha256:" + "c" * 64,
            "tokenizer_fingerprint": TOKENIZER_IDENTITY,
            "vocab_size": 16000,
            "special_token_ids": {"pad": 0, "unk": 1, "bos": 2, "eos": 3},
            "loaded": False,
        }
    if artifact_type == "prompt_set_identity":
        return 2, {
            "prompt_set_id": "synthetic-prompts",
            "version": "v1",
            "checksum": PROMPT_SET,
            "prompt_count": 2,
            "category_distribution": {"complete": 1, "incomplete": 1},
            "length_distribution": {"short": 2},
            "normalization_policy": "identity",
            "pii_status": "synthetic_pii_free",
            "leakage_status": "synthetic_no_dataset_source",
            "source_evidence": "sha256:" + "d" * 64,
            "prompt_text_stored": False,
        }
    if artifact_type == "generation_matrix":
        return 1, {
            "matrix_id": "synthetic-matrix-v1",
            "device": "cpu",
            "dtype": "float32",
            "seed": 17,
            "prompt_repetitions": 1,
            "lengths": [16, 32, 64, 128],
            "profiles": [
                {
                    "name": "greedy",
                    "mode": "pure_greedy",
                    "parameters": {
                        "do_sample": False,
                        "forced_eos": False,
                        "logit_bias": False,
                        "heuristic_stop": False,
                    },
                }
            ],
            "stop_policy": {
                "eos": True,
                "maximum_new_tokens": True,
                "external_heuristic": False,
            },
            "privacy": {"raw_text_storage": False, "raw_token_sequence_storage": False},
        }
    if artifact_type in {
        "eos_rank_trajectory",
        "eos_probability_summary",
        "teacher_autoregressive_gap",
        "loop_analysis",
        "boundary_analysis",
        "prompt_category_position_analysis",
        "length_matrix",
        "decoding_ablation",
        "budget_proxy_analysis",
        "hypothesis_assessment",
    }:
        return 0, _analysis_payload()
    if artifact_type == "output_manifest":
        return len(EXACT_ARTIFACT_FILENAMES), {
            "status": "writing",
            "output_root_logical_id": "analysis/evaluation/diagnostics/synthetic",
            "writer_name": "dohalm-eos-diagnostic-artifact-writer",
            "writer_version": "1",
            "exact_artifact_set": list(EXACT_ARTIFACT_FILENAMES),
            "optional_artifact_set": [],
        }
    raise AssertionError(f"unexpected artifact type: {artifact_type}")


def _artifact(artifact_type: str, **overrides: object):
    record_count, payload = _payload(artifact_type)
    arguments = _common()
    arguments.update(overrides)
    return new_diagnostic_artifact(
        artifact_type=artifact_type,
        record_count=record_count,
        payload=payload,
        **arguments,
    )


def _write_content_bundle(directory: Path) -> None:
    for artifact_type in ARTIFACT_FILENAMES:
        if artifact_type in {"artifact_inventory", "completion_evidence"}:
            continue
        artifact = _artifact(artifact_type)
        write_diagnostic_artifact(
            destination=directory / ARTIFACT_FILENAMES[artifact_type], artifact=artifact
        )


def _write_completed_synthetic_bundle(directory: Path) -> None:
    _write_content_bundle(directory)
    inventory = new_artifact_inventory(directory, created_at=STAMP)
    write_diagnostic_artifact(
        destination=directory / ARTIFACT_FILENAMES["artifact_inventory"],
        artifact=inventory,
    )
    completion = new_completion_evidence(
        directory, created_at=STAMP, completion_scope="synthetic_schema_rehearsal"
    )
    write_diagnostic_artifact(
        destination=directory / ARTIFACT_FILENAMES["completion_evidence"],
        artifact=completion,
    )


def test_canonical_serialization_and_fingerprint_are_deterministic() -> None:
    left = {"z": 1, "한글": {"b": False, "a": [3, 2, 1]}}
    right = {"한글": {"a": [3, 2, 1], "b": False}, "z": 1}
    assert canonical_diagnostic_json_bytes(left) == canonical_diagnostic_json_bytes(
        right
    )
    assert canonical_diagnostic_json_bytes(left).endswith(b"\n")
    artifact = _artifact("checkpoint_identity")
    later = _artifact("checkpoint_identity", created_at="2099-01-01T00:00:01Z")
    assert artifact.artifact_fingerprint == later.artifact_fingerprint
    assert artifact.checksum != later.checksum


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"source_commit": "not-a-git-sha"}, "EOS_DIAGNOSTIC_ARTIFACT_INVALID"),
        (
            {"created_at": "2099-01-01T00:00:00+00:00"},
            "EOS_DIAGNOSTIC_ARTIFACT_INVALID",
        ),
        (
            {"diagnostic_run_id": "DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-20991301-0001"},
            "EOS_DIAGNOSTIC_ARTIFACT_INVALID",
        ),
    ],
)
def test_git_sha_timestamp_and_run_id_are_strict(
    overrides: dict[str, object], error: str
) -> None:
    with pytest.raises(EOSDiagnosticArtifactError, match=f"^{error}$"):
        _artifact("checkpoint_identity", **overrides)


def test_loader_rejects_unknown_duplicate_nonfinite_and_noncanonical_json(
    synthetic_workspace: Path,
) -> None:
    artifact = _artifact("checkpoint_identity")
    path = synthetic_workspace / ARTIFACT_FILENAMES["checkpoint_identity"]
    value = artifact.as_dict()
    value["unknown"] = True
    path.write_bytes(canonical_diagnostic_json_bytes(value))
    with pytest.raises(EOSDiagnosticArtifactError):
        load_diagnostic_artifact(path)

    raw = serialize_diagnostic_artifact(artifact)
    path.write_bytes(b'{"schema_version":1,' + raw[1:])
    with pytest.raises(
        EOSDiagnosticArtifactError, match="^EOS_DIAGNOSTIC_DUPLICATE_KEY$"
    ):
        load_diagnostic_artifact(path)

    path.write_bytes(raw.replace(b'"record_count":1', b'"record_count":NaN'))
    with pytest.raises(
        EOSDiagnosticArtifactError, match="^EOS_DIAGNOSTIC_NONFINITE_NUMBER$"
    ):
        load_diagnostic_artifact(path)

    path.write_text(json.dumps(artifact.as_dict(), indent=2), encoding="utf-8")
    with pytest.raises(
        EOSDiagnosticArtifactError, match="^EOS_DIAGNOSTIC_ARTIFACT_NONCANONICAL$"
    ):
        load_diagnostic_artifact(path)


def test_payload_unknown_field_and_checksum_tampering_are_rejected(
    synthetic_workspace: Path,
) -> None:
    artifact = _artifact("checkpoint_identity")
    path = synthetic_workspace / ARTIFACT_FILENAMES["checkpoint_identity"]
    value = artifact.as_dict()
    value["payload"]["unknown"] = True
    path.write_bytes(canonical_diagnostic_json_bytes(value))
    with pytest.raises(EOSDiagnosticArtifactError):
        load_diagnostic_artifact(path)

    value = artifact.as_dict()
    value["checksum"] = "sha256:" + "f" * 64
    path.write_bytes(canonical_diagnostic_json_bytes(value))
    with pytest.raises(
        EOSDiagnosticArtifactError, match="^EOS_DIAGNOSTIC_ARTIFACT_INTEGRITY_MISMATCH$"
    ):
        load_diagnostic_artifact(path)

    value = artifact.as_dict()
    value["artifact_fingerprint"] = "sha256:" + "e" * 64
    path.write_bytes(canonical_diagnostic_json_bytes(value))
    with pytest.raises(
        EOSDiagnosticArtifactError, match="^EOS_DIAGNOSTIC_ARTIFACT_INTEGRITY_MISMATCH$"
    ):
        load_diagnostic_artifact(path)

    value = artifact.as_dict()
    value["schema_version"] = 2
    path.write_bytes(canonical_diagnostic_json_bytes(value))
    with pytest.raises(EOSDiagnosticArtifactError):
        load_diagnostic_artifact(path)


def test_writer_is_canonical_reloadable_and_no_replace(
    synthetic_workspace: Path,
) -> None:
    artifact = _artifact("checkpoint_identity")
    path = synthetic_workspace / ARTIFACT_FILENAMES["checkpoint_identity"]
    result = write_diagnostic_artifact(destination=path, artifact=artifact)
    assert path.read_bytes() == serialize_diagnostic_artifact(artifact)
    assert load_diagnostic_artifact(path) == artifact
    assert result.bytes_written == len(path.read_bytes())
    assert result.file_checksum.startswith("sha256:")
    with pytest.raises(
        EOSDiagnosticArtifactError, match="^EOS_DIAGNOSTIC_ARTIFACT_ALREADY_EXISTS$"
    ):
        write_diagnostic_artifact(destination=path, artifact=artifact)


def test_writer_fsync_failure_leaves_no_final(
    monkeypatch: pytest.MonkeyPatch, synthetic_workspace: Path
) -> None:
    artifact = _artifact("checkpoint_identity")
    path = synthetic_workspace / ARTIFACT_FILENAMES["checkpoint_identity"]
    monkeypatch.setattr(
        "src.evaluation.eos_diagnostic_artifacts.os.fsync",
        lambda _descriptor: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(
        EOSDiagnosticArtifactError,
        match="^EOS_DIAGNOSTIC_ARTIFACT_ATOMIC_WRITE_FAILED$",
    ):
        write_diagnostic_artifact(destination=path, artifact=artifact)
    assert not path.exists()
    assert not path.with_name(path.name + ".tmp").exists()


def test_completion_requires_all_eighteen_artifacts(synthetic_workspace: Path) -> None:
    _write_content_bundle(synthetic_workspace)
    with pytest.raises(EOSDiagnosticArtifactError):
        new_completion_evidence(
            synthetic_workspace,
            created_at=STAMP,
            completion_scope="synthetic_schema_rehearsal",
        )
    inventory = new_artifact_inventory(synthetic_workspace, created_at=STAMP)
    write_diagnostic_artifact(
        destination=synthetic_workspace / ARTIFACT_FILENAMES["artifact_inventory"],
        artifact=inventory,
    )
    completion = new_completion_evidence(
        synthetic_workspace,
        created_at=STAMP,
        completion_scope="synthetic_schema_rehearsal",
    )
    write_diagnostic_artifact(
        destination=synthetic_workspace / ARTIFACT_FILENAMES["completion_evidence"],
        artifact=completion,
    )
    result = validate_completed_bundle(synthetic_workspace)
    assert result.status == "completed"
    assert result.completion_scope == "synthetic_schema_rehearsal"
    assert result.artifact_count == 18
    assert {item.name for item in synthetic_workspace.iterdir()} == set(
        EXACT_ARTIFACT_FILENAMES
    )


def test_completion_rejects_inventory_drift_extra_files_and_fake_execution(
    synthetic_workspace: Path,
) -> None:
    _write_completed_synthetic_bundle(synthetic_workspace)
    content = synthetic_workspace / ARTIFACT_FILENAMES["checkpoint_identity"]
    content.write_bytes(content.read_bytes() + b" ")
    with pytest.raises(EOSDiagnosticArtifactError):
        validate_completed_bundle(synthetic_workspace)

    other = synthetic_workspace / "extra.json"
    other.write_text("{}", encoding="utf-8")
    with pytest.raises(
        EOSDiagnosticArtifactError, match="^EOS_DIAGNOSTIC_ARTIFACT_SET_INCOMPLETE$"
    ):
        validate_completed_bundle(synthetic_workspace)

    clean = synthetic_workspace / "clean"
    clean.mkdir()
    _write_content_bundle(clean)
    inventory = new_artifact_inventory(clean, created_at=STAMP)
    write_diagnostic_artifact(
        destination=clean / ARTIFACT_FILENAMES["artifact_inventory"], artifact=inventory
    )
    with pytest.raises(
        EOSDiagnosticArtifactError, match="^EOS_DIAGNOSTIC_SYNTHETIC_SCOPE_INVALID$"
    ):
        new_completion_evidence(
            clean, created_at=STAMP, completion_scope="diagnostic_execution"
        )
