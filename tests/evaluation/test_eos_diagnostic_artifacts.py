from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path

import pytest

from src.evaluation.eos_diagnostic_artifacts import (
    ARTIFACT_FILENAMES,
    EXACT_ARTIFACT_FILENAMES,
    EOSDiagnosticArtifactError,
    canonical_diagnostic_json_bytes,
    diagnostic_fingerprint,
    load_diagnostic_artifact,
    new_artifact_inventory,
    new_completion_evidence,
    new_diagnostic_artifact,
    serialize_diagnostic_artifact,
    validate_completed_bundle,
    write_diagnostic_artifact,
)
from src.evaluation.eos_diagnostic_backend import (
    AnalysisResult,
    build_diagnostic_summary,
)
from src.evaluation.eos_hypothesis_assessor import (
    AssessorInput,
    EvidenceSignal,
    assess_hypotheses,
    attach_hypothesis_assessment_to_summary,
    build_r1_hypothesis_payload,
)
from src.evaluation.eos_hypothesis_policy import (
    DIAGNOSTIC_ARTIFACT_TYPES,
    HYPOTHESIS_DIAGNOSTICS,
    HYPOTHESIS_IDS,
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


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
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


def _r4_analysis_payload(artifact_type: str) -> dict[str, object]:
    records = (
        [
            {
                "opaque_prompt_id": "synthetic-prompt-01",
                "step_index": 0,
                "artifact_role": artifact_type,
            }
        ]
        if artifact_type == "eos_rank_trajectory"
        else []
    )
    return {
        "analysis_status": "complete",
        "record_schema_version": 4,
        "records": records,
        "summary": {"evidence_status": "complete"},
        "limitations": [],
    }


def _r4_summary() -> dict[str, object]:
    semantic: dict[str, object] = {
        "diagnostic_run_id": RUN_ID,
        "run_mode": "synthetic_only",
        "completed_diagnostics": [f"D{index}" for index in range(1, 9)],
        "limited_diagnostics": [],
        "insufficient_diagnostics": [],
        "incompatible_diagnostics": [],
        "pure_greedy_summary": {},
        "repetition_summary": {},
        "eos_summary": {},
        "evidence_coverage": {"complete_or_limited": 8, "required": 8},
        "unresolved_questions": [],
        "hypothesis_selection_allowed": True,
        "actual_candidate_b_status_changed": False,
    }
    semantic["summary_fingerprint"] = diagnostic_fingerprint(semantic)
    return semantic


def _r5_bundle_values() -> tuple[
    tuple[AnalysisResult, ...], dict[str, object], dict[str, object]
]:
    results: list[AnalysisResult] = []
    for diagnostic_id, artifact_types in DIAGNOSTIC_ARTIFACT_TYPES.items():
        for artifact_type in artifact_types:
            summary: dict[str, object] = {"synthetic_metric_count": 1}
            if diagnostic_id == "D2":
                summary["paired_observation_count"] = 1
            elif diagnostic_id == "D4":
                summary["packed_comparison_available"] = True
            elif diagnostic_id == "D7":
                summary["pure_greedy_summary"] = {"trace_count": 1}
            semantic = {
                "diagnostic_id": diagnostic_id,
                "artifact_type": artifact_type,
                "evidence_status": "complete",
                "records": [],
                "summary": summary,
                "limitations": [],
            }
            results.append(
                AnalysisResult(
                    diagnostic_id=diagnostic_id,
                    artifact_type=artifact_type,
                    evidence_status="complete",
                    records=(),
                    summary=summary,
                    limitations=(),
                    result_fingerprint=diagnostic_fingerprint(semantic),
                )
            )
    values = tuple(results)
    signals = []
    for hypothesis_id in HYPOTHESIS_IDS:
        diagnostic_id = HYPOTHESIS_DIAGNOSTICS[hypothesis_id][0]
        artifact_fingerprint = next(
            item.result_fingerprint
            for item in values
            if item.diagnostic_id == diagnostic_id
        )
        semantic_signal: dict[str, object] = {
            "signal_id": f"SYNTHETIC-{hypothesis_id}-neutral-review",
            "hypothesis_id": hypothesis_id,
            "direction": "neutral",
            "diagnostic_id": diagnostic_id,
            "artifact_fingerprint": artifact_fingerprint,
            "metric_name": "synthetic_metric_delta",
            "comparison_scope": "synthetic_fixture",
            "observation": {"sample_count": 4},
            "evidence_strength": "indeterminate",
            "limitation_codes": [],
            "approval_required": False,
        }
        semantic_signal["signal_fingerprint"] = diagnostic_fingerprint(semantic_signal)
        signals.append(EvidenceSignal.from_mapping(semantic_signal))
    base_summary = build_diagnostic_summary(RUN_ID, values)
    assessor_input = AssessorInput.create(
        diagnostic_run_id=RUN_ID,
        policy_version="candidate-c-hypothesis-selection-v1",
        candidate_b_identity_fingerprint=CHECKPOINT_IDENTITY,
        generation_matrix_fingerprint=GENERATION_MATRIX,
        results=values,
        diagnostic_summary=base_summary,
        signals=tuple(signals),
    )
    bundle = assess_hypotheses(assessor_input)
    return (
        values,
        _plain(build_r1_hypothesis_payload(bundle)),
        _plain(attach_hypothesis_assessment_to_summary(base_summary, bundle)),
    )


def _resign_hypothesis_payload(payload: dict[str, object]) -> None:
    payload.pop("assessment_fingerprint", None)
    payload["assessment_fingerprint"] = diagnostic_fingerprint(payload)


def _new_r5_hypothesis_artifact(payload: dict[str, object], **overrides: object):
    common = _common(**overrides)
    return new_diagnostic_artifact(
        artifact_type="hypothesis_assessment",
        record_count=7,
        payload=payload,
        **common,
    )


def _write_r5_precompletion_bundle(
    destination: Path,
    results: tuple[AnalysisResult, ...],
    hypothesis_payload: dict[str, object],
    hypothesis_summary: dict[str, object],
) -> None:
    results_by_type = {item.artifact_type: item for item in results}
    for artifact_type in ARTIFACT_FILENAMES:
        if artifact_type in {"artifact_inventory", "completion_evidence"}:
            continue
        record_count, payload = _payload(artifact_type)
        if artifact_type == "diagnostic_run_manifest":
            payload["execution_mode"] = "synthetic_diagnostic_rehearsal"
        elif artifact_type in results_by_type:
            payload = results_by_type[artifact_type].artifact_payload()
            record_count = len(payload["records"])
        elif artifact_type == "hypothesis_assessment":
            payload = hypothesis_payload
            record_count = 7
        elif artifact_type == "output_manifest":
            payload["status"] = "validating"
            payload["diagnostic_summary"] = hypothesis_summary
        artifact = new_diagnostic_artifact(
            artifact_type=artifact_type,
            record_count=record_count,
            payload=payload,
            **_common(),
        )
        write_diagnostic_artifact(
            destination=destination / ARTIFACT_FILENAMES[artifact_type],
            artifact=artifact,
        )
    inventory = new_artifact_inventory(destination, created_at=STAMP)
    write_diagnostic_artifact(
        destination=destination / ARTIFACT_FILENAMES["artifact_inventory"],
        artifact=inventory,
    )


def test_r4_jsonl_and_synthetic_diagnostic_completion_rehearsal(
    synthetic_workspace: Path,
) -> None:
    analysis_types = {
        "eos_rank_trajectory",
        "eos_probability_summary",
        "teacher_autoregressive_gap",
        "loop_analysis",
        "boundary_analysis",
        "prompt_category_position_analysis",
        "length_matrix",
        "decoding_ablation",
        "budget_proxy_analysis",
    }
    for artifact_type in ARTIFACT_FILENAMES:
        if artifact_type in {"artifact_inventory", "completion_evidence"}:
            continue
        record_count, payload = _payload(artifact_type)
        if artifact_type == "diagnostic_run_manifest":
            payload["execution_mode"] = "synthetic_diagnostic_rehearsal"
        elif artifact_type in analysis_types:
            payload = _r4_analysis_payload(artifact_type)
            record_count = len(payload["records"])
        elif artifact_type == "output_manifest":
            payload["status"] = "validating"
            payload["diagnostic_summary"] = _r4_summary()
        artifact = new_diagnostic_artifact(
            artifact_type=artifact_type,
            record_count=record_count,
            payload=payload,
            **_common(),
        )
        write_diagnostic_artifact(
            destination=synthetic_workspace / ARTIFACT_FILENAMES[artifact_type],
            artifact=artifact,
        )

    trajectory_path = synthetic_workspace / ARTIFACT_FILENAMES["eos_rank_trajectory"]
    assert len(trajectory_path.read_text(encoding="utf-8").splitlines()) == 2
    assert load_diagnostic_artifact(trajectory_path).record_count == 1

    inventory = new_artifact_inventory(synthetic_workspace, created_at=STAMP)
    write_diagnostic_artifact(
        destination=synthetic_workspace / ARTIFACT_FILENAMES["artifact_inventory"],
        artifact=inventory,
    )
    completion = new_completion_evidence(
        synthetic_workspace,
        created_at=STAMP,
        completion_scope="synthetic_diagnostic_rehearsal",
    )
    write_diagnostic_artifact(
        destination=synthetic_workspace / ARTIFACT_FILENAMES["completion_evidence"],
        artifact=completion,
    )
    result = validate_completed_bundle(synthetic_workspace)
    assert result.completion_scope == "synthetic_diagnostic_rehearsal"
    assert result.artifact_count == 18


def test_r4_jsonl_rejects_partial_line(synthetic_workspace: Path) -> None:
    payload = _r4_analysis_payload("eos_rank_trajectory")
    artifact = new_diagnostic_artifact(
        artifact_type="eos_rank_trajectory",
        record_count=1,
        payload=payload,
        **_common(),
    )
    path = synthetic_workspace / ARTIFACT_FILENAMES["eos_rank_trajectory"]
    path.write_bytes(serialize_diagnostic_artifact(artifact).removesuffix(b"\n"))
    with pytest.raises(EOSDiagnosticArtifactError, match="^EOS_DIAG_JSONL_INVALID$"):
        load_diagnostic_artifact(path)


def test_r4_payload_cannot_authorize_production_diagnostic_completion() -> None:
    with pytest.raises(
        EOSDiagnosticArtifactError,
        match="^EOS_DIAGNOSTIC_PRODUCTION_PAYLOAD_NOT_AUTHORIZED$",
    ):
        new_diagnostic_artifact(
            artifact_type="eos_rank_trajectory",
            diagnostic_run_id="DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-20990101-0004",
            record_count=1,
            payload=_r4_analysis_payload("eos_rank_trajectory"),
            **{
                key: value
                for key, value in _common().items()
                if key != "diagnostic_run_id"
            },
        )


def test_r5_hypothesis_payload_and_summary_complete_synthetic_bundle(
    synthetic_workspace: Path,
) -> None:
    results, hypothesis_payload, hypothesis_summary = _r5_bundle_values()
    _write_r5_precompletion_bundle(
        synthetic_workspace, results, hypothesis_payload, hypothesis_summary
    )
    completion = new_completion_evidence(
        synthetic_workspace,
        created_at=STAMP,
        completion_scope="synthetic_diagnostic_rehearsal",
    )
    write_diagnostic_artifact(
        destination=synthetic_workspace / ARTIFACT_FILENAMES["completion_evidence"],
        artifact=completion,
    )
    assert validate_completed_bundle(synthetic_workspace).artifact_count == 18


def test_r5_production_hypothesis_payload_is_not_authorized() -> None:
    production_run_id = "DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-20990101-0005"
    _, payload, _ = _r5_bundle_values()
    payload["diagnostic_run_id"] = production_run_id
    payload.pop("assessment_fingerprint")
    payload["assessment_fingerprint"] = diagnostic_fingerprint(payload)
    with pytest.raises(
        EOSDiagnosticArtifactError,
        match="^EOS_HYPOTHESIS_PRODUCTION_NOT_AUTHORIZED$",
    ):
        new_diagnostic_artifact(
            artifact_type="hypothesis_assessment",
            diagnostic_run_id=production_run_id,
            record_count=7,
            payload=payload,
            **{
                key: value
                for key, value in _common().items()
                if key != "diagnostic_run_id"
            },
        )


@pytest.mark.parametrize(
    ("field", "envelope_override"),
    [
        (
            "candidate_b_identity_fingerprint",
            {"checkpoint_identity_fingerprint": "sha256:" + "f" * 64},
        ),
        (
            "generation_matrix_fingerprint",
            {"generation_matrix_fingerprint": "sha256:" + "f" * 64},
        ),
    ],
)
def test_r5_payload_identity_must_match_artifact_envelope(
    field: str, envelope_override: dict[str, object]
) -> None:
    _, payload, _ = _r5_bundle_values()
    assert payload[field] != next(iter(envelope_override.values()))
    with pytest.raises(
        EOSDiagnosticArtifactError,
        match="^EOS_DIAGNOSTIC_ARTIFACT_IDENTITY_MISMATCH$",
    ):
        _new_r5_hypothesis_artifact(payload, **envelope_override)


@pytest.mark.parametrize("mutation", ["wrong_mapping", "forbidden_text", "duplicate"])
def test_r5_loader_rejects_detached_or_unsafe_signals(mutation: str) -> None:
    _, payload, _ = _r5_bundle_values()
    signals = payload["evidence_signals"]
    assert isinstance(signals, list)
    signal = signals[0]
    assert isinstance(signal, dict)
    if mutation == "wrong_mapping":
        signal["diagnostic_id"] = "D8"
        signal["artifact_fingerprint"] = payload["diagnostic_artifact_fingerprints"][
            "D8"
        ][0]
    elif mutation == "forbidden_text":
        signal["observation"] = {"prompt": "must-not-be-serialized"}
    else:
        signals.append(dict(signal))
        _resign_hypothesis_payload(payload)
        with pytest.raises(EOSDiagnosticArtifactError):
            _new_r5_hypothesis_artifact(payload)
        return
    signal.pop("signal_fingerprint")
    signal["signal_fingerprint"] = diagnostic_fingerprint(signal)
    _resign_hypothesis_payload(payload)
    with pytest.raises(EOSDiagnosticArtifactError):
        _new_r5_hypothesis_artifact(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_direction_reference",
        "missing_signal",
        "duplicate_reference",
        "wrong_intervention",
        "impossible_status",
        "unauthorized_high",
        "selection_mismatch",
    ],
)
def test_r5_loader_rejects_semantically_impossible_payloads(mutation: str) -> None:
    _, payload, _ = _r5_bundle_values()
    assessment = payload["hypothesis_assessments"][0]
    if mutation == "wrong_direction_reference":
        assessment["supporting_signals"] = [payload["evidence_signals"][0]["signal_id"]]
    elif mutation == "missing_signal":
        assessment["insufficient_signals"] = ["SYNTHETIC-MISSING-SIGNAL"]
    elif mutation == "duplicate_reference":
        signal_id = payload["evidence_signals"][0]["signal_id"]
        assessment["insufficient_signals"] = [signal_id, signal_id]
    elif mutation == "wrong_intervention":
        assessment["intervention_category"] = "training_budget"
    elif mutation == "impossible_status":
        assessment["status"] = "supported"
    elif mutation == "unauthorized_high":
        assessment["confidence"] = "high"
    else:
        selection = payload["selection_result"]
        selection["selection_status"] = "selected"
        selection["proposed_hypothesis"] = "H1_EOS_LOGIT_CALIBRATION"
        selection["conditions"] = []
        selection.pop("selection_fingerprint")
        selection["selection_fingerprint"] = diagnostic_fingerprint(selection)
        _resign_hypothesis_payload(payload)
        with pytest.raises(EOSDiagnosticArtifactError):
            _new_r5_hypothesis_artifact(payload)
        return
    assessment.pop("assessment_fingerprint")
    assessment["assessment_fingerprint"] = diagnostic_fingerprint(assessment)
    _resign_hypothesis_payload(payload)
    with pytest.raises(EOSDiagnosticArtifactError):
        _new_r5_hypothesis_artifact(payload)


def test_r5_loader_rejects_h6_high_confidence_and_omitted_contradiction() -> None:
    _, payload, _ = _r5_bundle_values()
    h6 = payload["hypothesis_assessments"][5]
    h6["confidence"] = "high"
    h6.pop("assessment_fingerprint")
    h6["assessment_fingerprint"] = diagnostic_fingerprint(h6)
    _resign_hypothesis_payload(payload)
    with pytest.raises(EOSDiagnosticArtifactError):
        _new_r5_hypothesis_artifact(payload)

    _, payload, _ = _r5_bundle_values()
    signal = payload["evidence_signals"][0]
    signal["direction"] = "contradictory"
    signal.pop("signal_fingerprint")
    signal["signal_fingerprint"] = diagnostic_fingerprint(signal)
    h1 = payload["hypothesis_assessments"][0]
    h1["status"] = "contradicted"
    h1["confidence"] = "medium"
    h1["contradictory_signals"] = [signal["signal_id"]]
    h1.pop("assessment_fingerprint")
    h1["assessment_fingerprint"] = diagnostic_fingerprint(h1)
    payload["contradictory_evidence_summary"] = {}
    _resign_hypothesis_payload(payload)
    with pytest.raises(EOSDiagnosticArtifactError):
        _new_r5_hypothesis_artifact(payload)


def test_r5_completion_rejects_detached_diagnostic_fingerprint(
    synthetic_workspace: Path,
) -> None:
    results, payload, summary = _r5_bundle_values()
    d1_values = payload["diagnostic_artifact_fingerprints"]["D1"]
    referenced = {
        signal["artifact_fingerprint"]
        for signal in payload["evidence_signals"]
        if signal["diagnostic_id"] == "D1"
    }
    detached_index = next(
        index for index, value in enumerate(d1_values) if value not in referenced
    )
    d1_values[detached_index] = "sha256:" + "f" * 64
    d1_values.sort()
    _resign_hypothesis_payload(payload)
    summary["assessment_fingerprint"] = payload["assessment_fingerprint"]
    summary.pop("summary_fingerprint")
    summary["summary_fingerprint"] = diagnostic_fingerprint(summary)
    _write_r5_precompletion_bundle(synthetic_workspace, results, payload, summary)
    with pytest.raises(
        EOSDiagnosticArtifactError, match="^EOS_HYPOTHESIS_ARTIFACT_MISMATCH$"
    ):
        new_completion_evidence(
            synthetic_workspace,
            created_at=STAMP,
            completion_scope="synthetic_diagnostic_rehearsal",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hypothesis_selection_result", "selected"),
        ("primary_hypothesis", "H1_EOS_LOGIT_CALIBRATION"),
        ("training_intervention_allowed", True),
        ("assessment_fingerprint", "sha256:" + "f" * 64),
    ],
)
def test_r5_completion_rejects_summary_semantic_drift(
    synthetic_workspace: Path, field: str, value: object
) -> None:
    results, payload, summary = _r5_bundle_values()
    summary[field] = value
    summary.pop("summary_fingerprint")
    summary["summary_fingerprint"] = diagnostic_fingerprint(summary)
    with pytest.raises(EOSDiagnosticArtifactError):
        _write_r5_precompletion_bundle(synthetic_workspace, results, payload, summary)
        new_completion_evidence(
            synthetic_workspace,
            created_at=STAMP,
            completion_scope="synthetic_diagnostic_rehearsal",
        )
