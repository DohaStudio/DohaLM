"""Execute the approved DohaLM v0.2 weighted QLoRA stages exactly once."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.training import qlora_training as common
from src.training.v02_qlora_training import (
    V02QLoRAError,
    full_training_preflight,
    load_weighted_context,
    output_roots,
    run_allocation,
    run_backward,
    run_full_training,
    run_ids,
    run_micro_training,
    runtime_estimate,
    validate_config,
    validate_prerequisite,
    validate_stage_result,
)

MODES = tuple(run_ids())
FILES = {
    "allocation": "allocation-result.yaml",
    "backward": "backward-result.yaml",
    "training-smoke-1": "training-smoke-stage1-result.yaml",
    "training-smoke-2": "training-smoke-stage2-result.yaml",
    "stability": "stability-result.yaml",
}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--mode", choices=MODES, required=True)
    value.add_argument("--approved-run-id", required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--physical-confirmed", action="store_true")
    value.add_argument("--repository", type=Path, default=Path.cwd())
    value.add_argument("--config", type=Path, default=Path("configs/training/dohalm-v0.2-qlora.yaml"))
    value.add_argument("--tokenized-root", type=Path, required=True)
    value.add_argument("--sidecar-root", type=Path, required=True)
    value.add_argument("--simulation-root", type=Path, required=True)
    value.add_argument("--model-cache-root", type=Path, required=True)
    value.add_argument("--training-root", type=Path, required=True)
    return value


def _load_stage(roots: dict[str, Path], mode: str, head: str) -> dict[str, object]:
    return validate_prerequisite(roots[mode], FILES[mode], run_ids()[mode], head)


def run(arguments: argparse.Namespace) -> dict[str, object]:
    expected = run_ids()[arguments.mode]
    if arguments.approved_run_id != expected:
        raise V02QLoRAError("RUN_ID_NOT_APPROVED")
    if not arguments.physical_confirmed:
        raise V02QLoRAError("PHYSICAL_CONFIRMATION_REQUIRED")
    git = common.verify_git_identity(arguments.repository, expected_head=arguments.expected_head)
    config = validate_config(arguments.config)
    environment = common.environment_snapshot()
    environment["execution_command"] = [sys.executable, *sys.argv]
    environment["config_fingerprint"] = common.sha256_file(arguments.config)
    environment["physical_preflight"] = {"ac": "confirmed", "cooling_and_ventilation": "confirmed"}
    common.validate_environment(environment)
    context = load_weighted_context(arguments.tokenized_root, arguments.sidecar_root)
    roots = output_roots(arguments.training_root)

    if arguments.mode == "allocation":
        result = run_allocation(config=config, cache_root=arguments.model_cache_root, context=context)
    elif arguments.mode == "backward":
        _load_stage(roots, "allocation", arguments.expected_head)
        result = run_backward(config=config, cache_root=arguments.model_cache_root, context=context)
    elif arguments.mode == "training-smoke-1":
        _load_stage(roots, "allocation", arguments.expected_head)
        _load_stage(roots, "backward", arguments.expected_head)
        result = run_micro_training(
            mode="stage1", config=config, cache_root=arguments.model_cache_root,
            context=context, micro_batches=2, accumulation=2,
            validation_batches=1, save_checkpoint=True,
        )
    elif arguments.mode == "training-smoke-2":
        _load_stage(roots, "training-smoke-1", arguments.expected_head)
        result = run_micro_training(
            mode="stage2", config=config, cache_root=arguments.model_cache_root,
            context=context, micro_batches=32, accumulation=16,
            validation_batches=2, save_checkpoint=True,
        )
    elif arguments.mode == "stability":
        _load_stage(roots, "training-smoke-2", arguments.expected_head)
        result = run_micro_training(
            mode="stability", config=config, cache_root=arguments.model_cache_root,
            context=context, micro_batches=256, accumulation=16,
            validation_batches=0, save_checkpoint=False,
        )
        result["runtime_estimate"] = runtime_estimate(result, arguments.simulation_root)
    else:
        stages = {mode: _load_stage(roots, mode, arguments.expected_head) for mode in FILES}
        estimate = stages["stability"].get("runtime_estimate")
        if not isinstance(estimate, dict):
            raise V02QLoRAError("RUNTIME_ESTIMATE_REQUIRED")
        full_training_preflight(stage_results=stages, estimate=estimate)
        paths = common.ensure_unused_output(roots["full"])
        return run_full_training(
            paths=paths, config=config, config_path=arguments.config,
            cache_root=arguments.model_cache_root, context=context,
            sidecar_root=arguments.sidecar_root, repository=arguments.repository,
            expected_head=arguments.expected_head, environment=environment,
            git_identity=git,
        )
    result["git"] = dict(git)
    if arguments.mode != "backward":
        validate_stage_result(result, mode=arguments.mode)
    common_paths = common.ensure_unused_output(roots[arguments.mode])
    common.publish_result_artifact(
        common_paths, filename=FILES[arguments.mode], result=result, environment=environment,
    )
    common.validate_result_artifact(
        roots[arguments.mode], filename=FILES[arguments.mode], expected_run_id=expected,
    )
    return result


def main() -> int:
    try:
        result = run(parser().parse_args())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"status": result["status"], "run_id": result["run_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
