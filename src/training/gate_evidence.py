"""Fail-closed Gate 4-6 evidence validation for ignored training artifacts."""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.data.checksums import canonical_json_bytes, checksum_value, file_checksum

from .checkpoint import CheckpointManager
from .errors import TrainingError


EVIDENCE_SCHEMA_VERSION = "1.0"
EXPECTED_PARAMETER_COUNT = 16_889_856
MINIMUM_TEST_COUNT = 502

REQUIRED_RUN_ARTIFACTS = (
    "run-summary.json",
    "throughput.json",
    "memory.json",
    "training-metrics.jsonl",
    "resume-validation.json",
    "sampler-state.json",
    "validation-manifest.json",
)

TEST_CONTRACTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "component_config": ("tests/test_model_components.py", ("test_tiny_config_defaults_match_approved_architecture",)),
    "component_causal_mask": ("tests/test_model_components.py", ("test_attention_actual_output_cannot_observe_future_tokens",)),
    "component_backward": ("tests/test_model_components.py", ("test_attention_backward_gradients_are_finite", "test_transformer_block_shape_parameter_count_and_finite_backward")),
    "component_dtype_device": ("tests/test_model_components.py", ("test_token_embedding_shape_dtype_device_and_parameter_count",)),
    "component_weight_tying": ("tests/test_model_components.py", ("test_lm_head_shape_has_no_bias_and_ties_same_parameter_storage",)),
    "component_parameter_count": ("tests/test_model_components.py", ("test_parameter_counter_matches_approved_tiny_total_and_excludes_tied_weight",)),
    "component_cuda_smoke": ("tests/test_model_components.py", ("test_cuda_fp16_component_forward_backward_is_finite",)),
    "integrated_forward": ("tests/test_model_integration.py", ("test_forward_returns_explicit_output_logits_shape_dtype_and_device",)),
    "integrated_causal_mask": ("tests/test_model_integration.py", ("test_integrated_causal_logits_cannot_observe_future_tokens",)),
    "integrated_backward": ("tests/test_model_integration.py", ("test_training_forward_loss_backward_has_finite_gradients",)),
    "integrated_cuda": ("tests/test_model_integration.py", ("test_cuda_autocast_fp16_loss_and_gradients_are_finite",)),
    "shifted_loss": ("tests/test_model_loss.py", ("test_shifted_loss_matches_manual_cross_entropy",)),
    "greedy_generation": ("tests/test_model_generation.py", ("test_greedy_generation_is_deterministic_and_preserves_prefix",)),
    "state_round_trip": ("tests/test_model_state_dict.py", ("test_state_bundle_round_trip_preserves_logits_and_tying",)),
    "integrated_parameter_count": ("tests/test_model_parameter_count_integration.py", ("test_integrated_default_model_parameter_count_is_exact",)),
    "training_amp": ("tests/test_training_amp.py", ("test_cuda_fp16_amp_updates_with_finite_metrics",)),
    "training_resume": ("tests/test_training_resume_continuity.py", ("test_resume_model_checksum_matches_uninterrupted", "test_resume_sampler_state_and_next_batch")),
    "training_overfit": ("tests/test_training_overfit.py", ("test_repeated_single_batch_loss_decreases",)),
    "training_memory": ("tests/test_training_memory_probe.py", ("test_cuda_probe_calls_reset_and_synchronize",)),
    "training_throughput": ("tests/test_training_throughput.py", ("test_throughput_counts_tokens_records_and_steps",)),
}

DOCUMENT_CONTRACTS = {
    "gate4": ("docs/architecture/model-components.md", "docs/quality/model-component-testing.md"),
    "gate5": ("docs/architecture/model-integration.md", "docs/quality/model-integration-testing.md"),
    "gate6": ("docs/training/trainer-foundation.md", "docs/training/tiny-training-validation.md", "docs/quality/tiny-training-testing.md"),
}


def _error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _error("EVIDENCE_ARTIFACT_INVALID", f"{path.name}을 읽을 수 없습니다.") from exc
    if not isinstance(value, dict):
        raise _error("EVIDENCE_ARTIFACT_INVALID", f"{path.name}의 최상위 값은 object여야 합니다.")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _check(code: str, passed: bool, evidence: Any = None) -> dict[str, Any]:
    return {"code": code, "passed": bool(passed), "evidence": evidence}


def _all_finite(value: Any) -> bool:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_all_finite(item) for item in value.values())
    if isinstance(value, list):
        return all(_all_finite(item) for item in value)
    return False


def _read_metrics(path: Path) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number}")
            metrics.append(value)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise _error("EVIDENCE_METRICS_INVALID", "training-metrics.jsonl이 유효하지 않습니다.") from exc
    if not metrics:
        raise _error("EVIDENCE_METRICS_INVALID", "training metric이 비어 있습니다.")
    return metrics


def _require_run(path: Path) -> dict[str, Any]:
    if not path.is_dir():
        raise _error("EVIDENCE_RUN_MISSING", "evidence run 디렉터리가 없습니다.")
    missing = [name for name in REQUIRED_RUN_ARTIFACTS if not (path / name).is_file()]
    if missing:
        raise _error("EVIDENCE_ARTIFACT_MISSING", f"필수 artifact가 없습니다: {', '.join(missing)}")
    documents = {name: _read_json(path / name) for name in REQUIRED_RUN_ARTIFACTS if name.endswith(".json")}
    documents["training-metrics.jsonl"] = _read_metrics(path / "training-metrics.jsonl")
    documents["artifact_checksums"] = {name: file_checksum(path / name) for name in REQUIRED_RUN_ARTIFACTS}
    return documents


def _checkpoint_evidence(run_dir: Path, expected_steps: Iterable[int]) -> tuple[list[dict[str, Any]], list[str]]:
    inspections: list[dict[str, Any]] = []
    failures: list[str] = []
    for step in expected_steps:
        checkpoint = run_dir / f"checkpoint-{step}"
        try:
            inspection = CheckpointManager.inspect(checkpoint).to_dict()
            metadata = CheckpointManager.metadata(checkpoint)
            inspections.append({
                "path_name": inspection["path_name"],
                "global_step": inspection["global_step"],
                "format_version": inspection["format_version"],
                "checksums_fingerprint": file_checksum(checkpoint / "checksums.json"),
                "optimizer_type": metadata.get("optimizer_type"),
                "scheduler_type": metadata.get("scheduler_type"),
                "synthetic_dataset_kind": metadata.get("synthetic_dataset", {}).get("kind") if isinstance(metadata.get("synthetic_dataset"), dict) else None,
            })
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            failures.append(f"checkpoint-{step}:{getattr(exc, 'code', type(exc).__name__)}")
    return inspections, failures


def _approved_tiny_config(value: Any) -> bool:
    expected = {
        "vocab_size": 16_000,
        "context_length": 256,
        "num_layers": 6,
        "hidden_size": 384,
        "num_heads": 6,
        "head_dim": 64,
        "ffn_size": 1_536,
        "linear_bias": True,
        "lm_head_bias": False,
        "tie_word_embeddings": True,
    }
    return isinstance(value, dict) and all(value.get(key) == item for key, item in expected.items())


def collect_test_suite_evidence(repository: Path) -> dict[str, Any]:
    """Run the whole suite and bind named contracts to that successful run."""

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--ignore=tests/output"],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    match = re.search(r"(\d+) passed", combined)
    passed_count = int(match.group(1)) if match else 0
    contracts: dict[str, bool] = {}
    for name, (relative_path, symbols) in TEST_CONTRACTS.items():
        path = repository / relative_path
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            contracts[name] = False
        else:
            contracts[name] = all(f"def {symbol}" in source for symbol in symbols)
    documents = {
        gate: all((repository / relative_path).is_file() for relative_path in relative_paths)
        for gate, relative_paths in DOCUMENT_CONTRACTS.items()
    }
    return {
        "exit_code": result.returncode,
        "passed": result.returncode == 0 and passed_count > 0,
        "passed_count": passed_count,
        "minimum_required": MINIMUM_TEST_COUNT,
        "contracts": contracts,
        "documents": documents,
    }


def _gate_document(gate: int, checks: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    blockers = [item["code"] for item in checks if not item["passed"]]
    eligible = not blockers
    body = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "gate": gate,
        "current_status": "planned",
        "proposed_status": "eligible_for_user_approval" if eligible else ("review_required" if any(item["passed"] for item in checks) else "blocked"),
        "eligible": eligible,
        "checks": checks,
        "blocking_reasons": blockers,
        "summary": summary,
        "user_approval_required": True,
        "approved_by": None,
        "approved_at": None,
    }
    body["evidence_fingerprint"] = checksum_value(body)
    return body


def build_gate_evidence(
    *,
    tiny_validation_dir: Path,
    tiny_overfit_dir: Path,
    batch_probe_dir: Path,
    test_evidence: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    validation = _require_run(tiny_validation_dir)
    overfit = _require_run(tiny_overfit_dir)
    probe_file = batch_probe_dir / "batch-probe.json"
    if not probe_file.is_file():
        raise _error("EVIDENCE_ARTIFACT_MISSING", "batch-probe.json이 없습니다.")
    probe = _read_json(probe_file)

    validation_summary = validation["run-summary.json"]
    validation_manifest = validation["validation-manifest.json"]
    validation_resume = validation["resume-validation.json"]
    overfit_summary = overfit["run-summary.json"]
    overfit_manifest = overfit["validation-manifest.json"]
    overfit_resume = overfit["resume-validation.json"]
    memory = validation["memory.json"]
    throughput = validation["throughput.json"]
    metrics = validation["training-metrics.jsonl"]

    checkpoint_steps = (5, 10)
    validation_checkpoints, validation_checkpoint_failures = _checkpoint_evidence(tiny_validation_dir, checkpoint_steps)
    overfit_save_step = int(overfit_resume.get("resumed_from_step", -1))
    overfit_final_step = int(overfit_summary.get("global_step", -1))
    overfit_checkpoints, overfit_checkpoint_failures = _checkpoint_evidence(tiny_overfit_dir, (overfit_save_step, overfit_final_step))

    contracts = test_evidence.get("contracts", {}) if isinstance(test_evidence, dict) else {}
    documents = test_evidence.get("documents", {}) if isinstance(test_evidence, dict) else {}
    suite_passed = test_evidence.get("passed") is True
    test_count = test_evidence.get("passed_count")
    base_checks = [
        _check("TEST_SUITE_PASSED", suite_passed, test_count),
        _check("TEST_COUNT_BASELINE_MET", isinstance(test_count, int) and test_count >= MINIMUM_TEST_COUNT, {"actual": test_count, "minimum": MINIMUM_TEST_COUNT}),
    ]

    gate4_contracts = (
        "component_config", "component_causal_mask", "component_backward", "component_dtype_device",
        "component_weight_tying", "component_parameter_count", "component_cuda_smoke",
    )
    gate4_checks = [*base_checks, *[_check(f"TEST_CONTRACT_{name.upper()}", contracts.get(name) is True) for name in gate4_contracts]]
    gate4_checks.extend([
        _check("DOCUMENTATION_PRESENT", documents.get("gate4") is True),
        _check("TINY_CONFIG_MATCH", _approved_tiny_config(validation_manifest.get("model_config"))),
        _check("CUDA_FP16_EVIDENCE", validation_summary.get("device") == "cuda" and validation_summary.get("amp_enabled") is True and validation_manifest.get("training_config", {}).get("amp_dtype") == "float16"),
        _check("PARAMETER_COUNT_MATCH", validation_summary.get("model_parameter_count") == EXPECTED_PARAMETER_COUNT, validation_summary.get("model_parameter_count")),
    ])
    gate4 = _gate_document(4, gate4_checks, {"test_count": test_count, "parameter_count": validation_summary.get("model_parameter_count")})

    gate5_contracts = (
        "integrated_forward", "integrated_causal_mask", "integrated_backward", "integrated_cuda",
        "shifted_loss", "greedy_generation", "state_round_trip", "integrated_parameter_count",
    )
    gate5_checks = [*base_checks, *[_check(f"TEST_CONTRACT_{name.upper()}", contracts.get(name) is True) for name in gate5_contracts]]
    gate5_checks.extend([
        _check("DOCUMENTATION_PRESENT", documents.get("gate5") is True),
        _check("PARAMETER_COUNT_MATCH", validation_summary.get("model_parameter_count") == EXPECTED_PARAMETER_COUNT, validation_summary.get("model_parameter_count")),
        _check("WEIGHT_TYING_PRESERVED", validation_resume.get("weight_tying_preserved") is True),
        _check("FINITE_INTEGRATED_METRICS", _all_finite(metrics)),
    ])
    gate5 = _gate_document(5, gate5_checks, {"test_count": test_count, "parameter_count": validation_summary.get("model_parameter_count")})

    sources_synthetic = all((
        validation_summary.get("synthetic_only") is True,
        validation_summary.get("actual_pretraining") is False,
        validation_manifest.get("synthetic_only") is True,
        validation_manifest.get("contains_source_text") is False,
        isinstance(validation_manifest.get("tokenizer_fingerprint"), str),
        overfit_summary.get("synthetic_only") is True,
        overfit_summary.get("actual_pretraining") is False,
        overfit_manifest.get("synthetic_only") is True,
        overfit_manifest.get("contains_source_text") is False,
        probe.get("synthetic_only") is True,
    ))
    checkpoint_state = _read_json(tiny_validation_dir / "checkpoint-5" / "training-state.json") if not validation_checkpoint_failures else {}
    rng_present = isinstance(checkpoint_state.get("rng_state"), dict) and bool(checkpoint_state.get("rng_state"))
    probe_candidates = probe.get("candidates", [])
    expected_metric_steps = list(range(1, 11))
    structured_metrics = (
        [item.get("global_step") for item in metrics] == expected_metric_steps
        and all({"loss", "gradient_norm", "learning_rate", "step_time", "tokens_seen"}.issubset(item) for item in metrics)
    )
    checkpoint_contract = bool(validation_checkpoints) and all(
        item.get("optimizer_type") == "AdamW" and item.get("scheduler_type") == "cosine"
        for item in validation_checkpoints
    )
    gate6_checks = [*base_checks]
    gate6_checks.extend([_check(f"TEST_CONTRACT_{name.upper()}", contracts.get(name) is True) for name in ("training_amp", "training_resume", "training_overfit", "training_memory", "training_throughput")])
    gate6_checks.extend([
        _check("DOCUMENTATION_PRESENT", documents.get("gate6") is True),
        _check("TINY_CONFIG_MATCH", _approved_tiny_config(validation_manifest.get("model_config")) and validation_manifest.get("model_config") == overfit_manifest.get("model_config")),
        _check("PARAMETER_COUNT_MATCH", validation_summary.get("model_parameter_count") == EXPECTED_PARAMETER_COUNT and overfit_summary.get("model_parameter_count") == EXPECTED_PARAMETER_COUNT),
        _check("CUDA_FP16_10_STEP", validation_summary.get("device") == "cuda" and validation_summary.get("amp_enabled") is True and validation_summary.get("global_step") == 10 and validation_manifest.get("training_config", {}).get("amp_dtype") == "float16"),
        _check("OPTIMIZER_SCHEDULER_ACCUMULATION_CLIPPING", checkpoint_contract and validation_manifest.get("training_config", {}).get("scheduler_type") == "cosine" and validation_manifest.get("training_config", {}).get("gradient_accumulation_steps", 0) > 0 and validation_manifest.get("training_config", {}).get("max_grad_norm", 0) > 0),
        _check("FINITE_LOSS_GRADIENT", _all_finite(metrics) and all(item.get("loss") is not None and item.get("gradient_norm") is not None for item in metrics)),
        _check("STRUCTURED_METRICS_COMPLETE", structured_metrics),
        _check("CHECKPOINT_5_10_VALID", not validation_checkpoint_failures and [item["global_step"] for item in validation_checkpoints] == [5, 10], validation_checkpoint_failures),
        _check("OVERFIT_CHECKPOINTS_VALID", not overfit_checkpoint_failures, overfit_checkpoint_failures),
        _check("RESUME_GLOBAL_STEP_CONTINUOUS", validation_resume.get("resumed_from_step") == 5 and validation_resume.get("final_global_step") == 10 and validation_resume.get("scheduler_step") == 10 and validation_resume.get("learning_rate_continuous") is True),
        _check("SCALER_STATE_RESTORED", validation_resume.get("scaler_state_present") is True),
        _check("RNG_STATE_PRESENT", rng_present),
        _check("SAMPLER_STATE_RESTORED", validation_resume.get("sampler_state_equal_at_load") is True and validation_resume.get("next_batch_fingerprint_equal") is True),
        _check("UNINTERRUPTED_RESUME_MATCH", validation_resume.get("bitwise_model_equal") is True and validation_resume.get("reference_model_parameter_checksum") == validation_resume.get("resumed_model_parameter_checksum") and validation_resume.get("logits_allclose") is True),
        _check("SYNTHETIC_OVERFIT_DECREASE", isinstance(overfit_summary.get("initial_loss"), (int, float)) and isinstance(overfit_summary.get("final_loss"), (int, float)) and overfit_summary["final_loss"] < overfit_summary["initial_loss"]),
        _check("VRAM_RECORDED", memory.get("supported") is True and memory.get("peak_allocated_bytes", 0) > 0 and memory.get("peak_reserved_bytes", 0) > 0),
        _check("THROUGHPUT_RECORDED", throughput.get("tokens_per_second", 0) > 0 and throughput.get("measured_optimizer_steps", 0) > 0),
        _check("BATCH_PROBE_FINITE", bool(probe_candidates) and all(item.get("finite_loss") is True and item.get("finite_gradient") is True for item in probe_candidates)),
        _check("SYNTHETIC_SOURCE_ONLY", sources_synthetic),
        _check("SOURCE_MUTATION_NOT_APPLICABLE", validation_manifest.get("contains_source_text") is False and overfit_manifest.get("contains_source_text") is False),
        _check("GATE_STATUS_UNCHANGED", validation_summary.get("gate_6") == "planned" and validation_summary.get("gate_7") == "planned"),
    ])
    gate6 = _gate_document(6, gate6_checks, {
        "test_count": test_count,
        "parameter_count": validation_summary.get("model_parameter_count"),
        "validation_steps": validation_summary.get("global_step"),
        "overfit_steps": overfit_summary.get("global_step"),
        "initial_loss": validation_summary.get("initial_loss"),
        "final_loss": validation_summary.get("final_loss"),
        "overfit_initial_loss": overfit_summary.get("initial_loss"),
        "overfit_final_loss": overfit_summary.get("final_loss"),
        "peak_allocated_bytes": memory.get("peak_allocated_bytes"),
        "peak_reserved_bytes": memory.get("peak_reserved_bytes"),
        "tokens_per_second": throughput.get("tokens_per_second"),
        "validation_run_id": tiny_validation_dir.name,
        "overfit_run_id": tiny_overfit_dir.name,
        "batch_probe_run_id": batch_probe_dir.name,
        "input_fingerprint": checksum_value({
            "validation": validation["artifact_checksums"],
            "validation_checkpoints": validation_checkpoints,
            "overfit": overfit["artifact_checksums"],
            "overfit_checkpoints": overfit_checkpoints,
            "batch_probe": file_checksum(probe_file),
            "tests": test_evidence,
        }),
    })
    return {"gate4": gate4, "gate5": gate5, "gate6": gate6}


def _run_id(fingerprint: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"gate-{stamp}-{fingerprint.removeprefix('sha256:')[:12]}"


def publish_evidence_bundle(
    *,
    output_root: Path,
    gates: dict[str, dict[str, Any]],
    pilot_readiness: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    evidence_fingerprint = checksum_value({"gates": gates, "pilot_readiness": pilot_readiness})
    selected_run_id = run_id or _run_id(evidence_fingerprint)
    run_dir = output_root / selected_run_id
    if run_dir.exists():
        raise _error("EVIDENCE_OUTPUT_EXISTS", "evidence output run이 이미 존재합니다.")
    run_dir.mkdir(parents=True)

    proposal = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "current_status": {name: value["current_status"] for name, value in gates.items()},
        "proposed_status": {name: value["proposed_status"] for name, value in gates.items()},
        "eligible": all(value["eligible"] for value in gates.values()),
        "evidence_fingerprint": evidence_fingerprint,
        "blocking_reasons": {name: value["blocking_reasons"] for name, value in gates.items()},
        "user_approval_required": True,
        "approved_by": None,
        "approved_at": None,
    }
    documents = {
        "gate4-evidence.json": gates["gate4"],
        "gate5-evidence.json": gates["gate5"],
        "gate6-evidence.json": gates["gate6"],
        "pilot-readiness.json": pilot_readiness,
        "status-proposal.json": proposal,
    }
    for name, document in documents.items():
        _write_json(run_dir / name, document)
    checklist = (
        "# Gate 4·5·6 사용자 검토 체크리스트\n\n"
        f"- Evidence fingerprint: `{evidence_fingerprint}`\n"
        "- [ ] Gate 4 구성요소 증거와 차단 사유 검토\n"
        "- [ ] Gate 5 통합 모델 증거와 차단 사유 검토\n"
        "- [ ] Gate 6 합성 학습·checkpoint/resume 증거와 차단 사유 검토\n"
        "- [ ] 합성 학습이 실제 사전학습 승인을 뜻하지 않음을 확인\n"
        "- [ ] approved_by와 approved_at은 사용자 승인 전 null 유지\n"
    )
    (run_dir / "review-checklist.md").write_text(checklist, encoding="utf-8", newline="\n")
    checksum_names = (*documents.keys(), "review-checklist.md")
    checksums = {name: file_checksum(run_dir / name) for name in checksum_names}
    _write_json(run_dir / "evidence-checksums.json", {"algorithm": "sha256", "files": checksums})
    return {
        "status": "evidence_bundle_created",
        "run_directory_name": selected_run_id,
        "evidence_fingerprint": evidence_fingerprint,
        "eligible": proposal["eligible"],
        "proposed_status": proposal["proposed_status"],
        "pilot_readiness": pilot_readiness.get("status"),
    }
