from __future__ import annotations

from pathlib import Path

import pytest

from scripts.training.train_dohalm_v02_qlora import parser
from src.training.v02_qlora_training import (
    ALLOCATION_ID,
    BACKWARD_ID,
    FULL_ID,
    SIMULATION_EPOCH0_FINGERPRINT,
    STABILITY_ID,
    STAGE1_ID,
    STAGE2_ID,
    V02QLoRAError,
    full_training_preflight,
    generation_verdict,
    expected_checkpoint_steps,
    output_roots,
    run_ids,
    validate_config,
    validate_stage_result,
)

CONFIG = Path("configs/training/dohalm-v0.2-qlora.yaml")


def _stage(mode: str) -> dict[str, object]:
    shapes = {
        "training-smoke-1": (2, 1, 1),
        "training-smoke-2": (32, 2, 2),
        "stability": (256, 16, 0),
    }
    value: dict[str, object] = {
        "status": "passed", "run_id": run_ids()[mode],
        "simulation_fingerprint_valid": True,
    }
    if mode == "allocation":
        value.update(forward_records=4, backward_calls=0, optimizer_creations=0, optimizer_steps=0)
    elif mode == "backward":
        value.update(optimizer_steps=0, lora_gradient_tensors=392, base_gradient_tensors=0)
    else:
        micro, steps, validation = shapes[mode]
        value.update(
            micro_batches=micro, optimizer_steps=steps, validation_batches=validation,
            stalled_batches=0, nonfinite_losses=0, nonfinite_gradients=0,
            cuda_oom=False, base_weights_changed=False, lora_weights_changed=True,
        )
    return value


def test_fixed_run_ids_and_no_automatic_id() -> None:
    assert run_ids() == {
        "allocation": ALLOCATION_ID, "backward": BACKWARD_ID,
        "training-smoke-1": STAGE1_ID, "training-smoke-2": STAGE2_ID,
        "stability": STABILITY_ID, "full": FULL_ID,
    }


def test_output_roots_are_disjoint(tmp_path: Path) -> None:
    roots = output_roots(tmp_path)
    assert len(set(roots.values())) == 6
    assert roots["full"] == tmp_path / "DohaLM-v0.2" / FULL_ID


def test_approved_config_is_exact() -> None:
    config = validate_config(CONFIG)
    assert config["training_allowed"] is True
    assert config["execution_allowed"] is True
    assert config["sampling"]["replacement"] is True
    assert config["sampling"]["validation_sampler"] == "sequential"


def test_readiness_config_is_not_executable() -> None:
    with pytest.raises(V02QLoRAError, match="V02_CONFIG_INVALID"):
        validate_config(Path("configs/training/dohalm-v0.2-qlora-readiness.yaml"))


@pytest.mark.parametrize("mode", ["allocation", "training-smoke-1", "training-smoke-2", "stability"])
def test_stage_contract_accepts_exact_result(mode: str) -> None:
    validate_stage_result(_stage(mode), mode=mode)


def test_stage_contract_rejects_optimizer_drift() -> None:
    result = _stage("training-smoke-2")
    result["optimizer_steps"] = 1
    with pytest.raises(V02QLoRAError, match="TRAINING_STAGE_RESULT_INVALID"):
        validate_stage_result(result, mode="training-smoke-2")


def test_full_preflight_requires_all_exact_stages() -> None:
    stages = {mode: _stage(mode) for mode in (
        "allocation", "backward", "training-smoke-1", "training-smoke-2", "stability",
    )}
    result = full_training_preflight(stage_results=stages, estimate={"acceptable": True, "total_hours": 40.0})
    assert result["expected_total_optimizer_steps"] == 1298
    assert result["automatic_retry"] is False
    assert result["automatic_resume"] is False


def test_full_preflight_rejects_runtime_over_48_hours() -> None:
    stages = {mode: _stage(mode) for mode in (
        "allocation", "backward", "training-smoke-1", "training-smoke-2", "stability",
    )}
    with pytest.raises(V02QLoRAError, match="RUNTIME_ESTIMATE_EXCEEDED"):
        full_training_preflight(stage_results=stages, estimate={"acceptable": False, "total_hours": 48.1})


def test_generation_hard_blockers_and_targets_are_separate() -> None:
    verdict = generation_verdict({
        "samples": 20, "character_f1": .49, "rouge_l": .33,
        "empty": 0, "special_token_exposure": 0, "repetition": 2,
        "maximum_length_reached": 1, "eos_terminated": 17,
    })
    assert verdict["hard_blocker_clear"] is True
    assert verdict["all_targets_met"] is False  # incomplete is exactly 15%


def test_generation_rejects_v01_regression() -> None:
    verdict = generation_verdict({
        "samples": 20, "character_f1": .40, "rouge_l": .30,
        "empty": 0, "special_token_exposure": 0, "repetition": 0,
        "maximum_length_reached": 0, "eos_terminated": 20,
    })
    assert verdict["hard_blockers"]["character_f1_below_v01_base"] is True
    assert verdict["hard_blocker_clear"] is False


def test_cli_requires_explicit_physical_flag() -> None:
    arguments = parser().parse_args([
        "--mode", "allocation", "--approved-run-id", ALLOCATION_ID,
        "--expected-head", "a" * 40, "--tokenized-root", "t",
        "--sidecar-root", "s", "--simulation-root", "m",
        "--model-cache-root", "c", "--training-root", "o",
    ])
    assert arguments.physical_confirmed is False


def test_simulation_epoch0_identity_is_immutable() -> None:
    assert SIMULATION_EPOCH0_FINGERPRINT == "sha256:b8157713c04bf2cdb7fd178031de1b8cb3f19287246577d14663940fb12998d3"


def test_full_checkpoint_schedule_includes_terminal_step() -> None:
    assert expected_checkpoint_steps(save_steps=250, total_optimizer_steps=1298) == (
        250, 500, 750, 1000, 1250, 1298,
    )
