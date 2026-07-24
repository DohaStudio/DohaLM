from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.data.checksums import canonical_json_bytes, file_checksum
from src.training.checkpoint import CONTENT_FILES
from src.training.gate_evidence import TEST_CONTRACTS, build_gate_evidence, publish_evidence_bundle


TINY_CONFIG = {
    "vocab_size": 16_000, "context_length": 256, "num_layers": 6, "hidden_size": 384,
    "num_heads": 6, "head_dim": 64, "ffn_size": 1_536, "dropout": 0.0,
    "layer_norm_eps": 1e-5, "linear_bias": True, "lm_head_bias": False,
    "tie_word_embeddings": True, "initialization": None,
}


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _checkpoint(run_dir: Path, step: int) -> None:
    checkpoint = run_dir / f"checkpoint-{step}"
    checkpoint.mkdir()
    for name in ("model.pt", "optimizer.pt", "scheduler.pt", "scaler.pt"):
        (checkpoint / name).write_bytes(f"{name}-{step}".encode())
    manifest = {
        "format_version": "1.0", "global_step": step,
        "model_config_fingerprint": "model", "training_config_fingerprint": "training",
        "dataset_fingerprint": "dataset", "tokenizer_fingerprint": "tokenizer",
        "files": [*CONTENT_FILES, "checksums.json"],
    }
    _write_json(checkpoint / "manifest.json", manifest)
    _write_json(checkpoint / "config.json", {
        "optimizer_type": "AdamW", "scheduler_type": "cosine",
        "synthetic_dataset": {"kind": "synthetic-repeated-pattern-v1"},
    })
    _write_json(checkpoint / "training-state.json", {"state": {"global_step": step}, "rng_state": {"python": "present"}})
    checksums = {name: file_checksum(checkpoint / name) for name in CONTENT_FILES}
    _write_json(checkpoint / "checksums.json", {"algorithm": "sha256", "files": checksums})


def _run(root: Path, name: str, *, overfit: bool = False) -> Path:
    run = root / name
    run.mkdir()
    initial_loss, final_loss = (10.0, 0.1) if overfit else (10.0, 5.0)
    final_step, save_step = (100, 50) if overfit else (10, 5)
    summary = {
        "actual_pretraining": False, "amp_enabled": True, "device": "cuda",
        "global_step": final_step, "initial_loss": initial_loss, "final_loss": final_loss,
        "model_parameter_count": 16_889_856, "status": "passed", "synthetic_only": True,
        "gate_6": "planned", "gate_7": "planned",
    }
    resume = {
        "resumed_from_step": save_step, "final_global_step": final_step, "scheduler_step": final_step,
        "learning_rate_continuous": True, "scaler_state_present": True,
        "sampler_state_equal_at_load": True, "next_batch_fingerprint_equal": True,
        "weight_tying_preserved": True, "bitwise_model_equal": True, "logits_allclose": True,
        "reference_model_parameter_checksum": "same", "resumed_model_parameter_checksum": "same",
    }
    manifest = {
        "schema_version": "1.0", "synthetic_only": True, "contains_source_text": False,
        "tokenizer_fingerprint": "sha256:c709bcaaf20935c748df0bfc130a55e676e3b9827e8904b43099ef7b338e1435",
        "model_config": TINY_CONFIG,
        "training_config": {
            "device": "cuda", "amp_dtype": "float16", "scheduler_type": "cosine",
            "gradient_accumulation_steps": 1, "max_grad_norm": 1.0,
        },
    }
    for filename, value in (
        ("run-summary.json", summary), ("throughput.json", {"tokens_per_second": 1.0, "measured_optimizer_steps": 1}),
        ("memory.json", {"supported": True, "peak_allocated_bytes": 1, "peak_reserved_bytes": 2}),
        ("resume-validation.json", resume), ("sampler-state.json", {"sample_offset": 1}),
        ("validation-manifest.json", manifest),
    ):
        _write_json(run / filename, value)
    metrics = "".join(
        json.dumps({
            "global_step": step, "loss": 1.0, "gradient_norm": 1.0,
            "learning_rate": 0.1, "step_time": 0.1, "tokens_seen": step,
        }) + "\n"
        for step in range(1, 11)
    )
    (run / "training-metrics.jsonl").write_text(metrics, encoding="utf-8")
    _checkpoint(run, save_step)
    _checkpoint(run, final_step)
    return run


def _fixture(tmp_path: Path):
    validation = _run(tmp_path, "validation")
    overfit = _run(tmp_path, "overfit", overfit=True)
    probe = tmp_path / "probe"
    probe.mkdir()
    _write_json(probe / "batch-probe.json", {
        "synthetic_only": True,
        "candidates": [{"finite_loss": True, "finite_gradient": True}],
    })
    tests = {
        "passed": True, "passed_count": 502,
        "contracts": {name: True for name in TEST_CONTRACTS},
        "documents": {"gate4": True, "gate5": True, "gate6": True},
    }
    return validation, overfit, probe, tests


def _build(tmp_path: Path):
    validation, overfit, probe, tests = _fixture(tmp_path)
    return build_gate_evidence(
        tiny_validation_dir=validation, tiny_overfit_dir=overfit,
        batch_probe_dir=probe, test_evidence=tests,
    )


def test_gate4_evidence_complete_and_missing(tmp_path: Path) -> None:
    validation, overfit, probe, tests = _fixture(tmp_path)
    complete = build_gate_evidence(tiny_validation_dir=validation, tiny_overfit_dir=overfit, batch_probe_dir=probe, test_evidence=tests)
    assert complete["gate4"]["eligible"] is True
    tests["contracts"]["component_causal_mask"] = False
    missing = build_gate_evidence(tiny_validation_dir=validation, tiny_overfit_dir=overfit, batch_probe_dir=probe, test_evidence=tests)
    assert "TEST_CONTRACT_COMPONENT_CAUSAL_MASK" in missing["gate4"]["blocking_reasons"]


def test_gate5_parameter_mismatch_and_tying_failure(tmp_path: Path) -> None:
    validation, overfit, probe, tests = _fixture(tmp_path)
    summary_path = validation / "run-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")); summary["model_parameter_count"] = 1; _write_json(summary_path, summary)
    resume_path = validation / "resume-validation.json"
    resume = json.loads(resume_path.read_text(encoding="utf-8")); resume["weight_tying_preserved"] = False; _write_json(resume_path, resume)
    gates = build_gate_evidence(tiny_validation_dir=validation, tiny_overfit_dir=overfit, batch_probe_dir=probe, test_evidence=tests)
    assert {"PARAMETER_COUNT_MATCH", "WEIGHT_TYING_PRESERVED"}.issubset(gates["gate5"]["blocking_reasons"])


def test_gate6_checkpoint_checksum_mismatch_is_blocked(tmp_path: Path) -> None:
    validation, overfit, probe, tests = _fixture(tmp_path)
    (validation / "checkpoint-5" / "model.pt").write_bytes(b"tampered")
    gates = build_gate_evidence(tiny_validation_dir=validation, tiny_overfit_dir=overfit, batch_probe_dir=probe, test_evidence=tests)
    assert "CHECKPOINT_5_10_VALID" in gates["gate6"]["blocking_reasons"]


@pytest.mark.parametrize(("field", "code"), [
    ("learning_rate_continuous", "RESUME_GLOBAL_STEP_CONTINUOUS"),
    ("sampler_state_equal_at_load", "SAMPLER_STATE_RESTORED"),
])
def test_gate6_resume_and_sampler_mismatch(tmp_path: Path, field: str, code: str) -> None:
    validation, overfit, probe, tests = _fixture(tmp_path)
    path = validation / "resume-validation.json"
    value = json.loads(path.read_text(encoding="utf-8")); value[field] = False; _write_json(path, value)
    gates = build_gate_evidence(tiny_validation_dir=validation, tiny_overfit_dir=overfit, batch_probe_dir=probe, test_evidence=tests)
    assert code in gates["gate6"]["blocking_reasons"]


def test_gate6_nonfinite_metric_and_non_decreasing_overfit(tmp_path: Path) -> None:
    validation, overfit, probe, tests = _fixture(tmp_path)
    lines = (validation / "training-metrics.jsonl").read_text(encoding="utf-8").splitlines()
    metric = json.loads(lines[0]); metric["loss"] = float("nan"); lines[0] = json.dumps(metric)
    (validation / "training-metrics.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary_path = overfit / "run-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")); summary["final_loss"] = summary["initial_loss"]; _write_json(summary_path, summary)
    gates = build_gate_evidence(tiny_validation_dir=validation, tiny_overfit_dir=overfit, batch_probe_dir=probe, test_evidence=tests)
    assert {"FINITE_LOSS_GRADIENT", "SYNTHETIC_OVERFIT_DECREASE"}.issubset(gates["gate6"]["blocking_reasons"])


def test_gate6_non_synthetic_source_is_blocked(tmp_path: Path) -> None:
    validation, overfit, probe, tests = _fixture(tmp_path)
    path = overfit / "validation-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")); manifest["synthetic_only"] = False; _write_json(path, manifest)
    gates = build_gate_evidence(tiny_validation_dir=validation, tiny_overfit_dir=overfit, batch_probe_dir=probe, test_evidence=tests)
    assert "SYNTHETIC_SOURCE_ONLY" in gates["gate6"]["blocking_reasons"]


def test_eligible_proposal_does_not_change_status_and_exposes_no_absolute_path(tmp_path: Path) -> None:
    gates = _build(tmp_path)
    pilot = {"status": "blocked", "eligible": False, "blocking_reasons": []}
    report = publish_evidence_bundle(output_root=tmp_path / "output", gates=gates, pilot_readiness=pilot, run_id="gate-test")
    proposal = json.loads((tmp_path / "output/gate-test/status-proposal.json").read_text(encoding="utf-8"))
    assert report["eligible"] is True and proposal["eligible"] is True, proposal["blocking_reasons"]
    assert proposal["current_status"] == {"gate4": "planned", "gate5": "planned", "gate6": "planned"}
    assert proposal["approved_by"] is None and proposal["approved_at"] is None
    assert str(tmp_path.resolve()) not in json.dumps(gates)


def test_evidence_fingerprint_is_deterministic(tmp_path: Path) -> None:
    validation, overfit, probe, tests = _fixture(tmp_path)
    first = build_gate_evidence(tiny_validation_dir=validation, tiny_overfit_dir=overfit, batch_probe_dir=probe, test_evidence=deepcopy(tests))
    second = build_gate_evidence(tiny_validation_dir=validation, tiny_overfit_dir=overfit, batch_probe_dir=probe, test_evidence=deepcopy(tests))
    assert {name: value["evidence_fingerprint"] for name, value in first.items()} == {name: value["evidence_fingerprint"] for name, value in second.items()}
