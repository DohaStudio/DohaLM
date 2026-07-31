"""Execute the approved, fail-closed DohaLM v0.1 QLoRA stages."""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml

from src.training.qlora_training import (
    ALLOCATION_SMOKE_RUN_ID,
    BACKWARD_DIAGNOSTIC_LENGTHS,
    BACKWARD_DIAGNOSTIC_RUN_ID,
    RUN_ID,
    TRAINING_SMOKE_RUN_ID,
    WSL_ALLOCATION_SMOKE_RUN_ID,
    WSL_BACKWARD_DIAGNOSTIC_RUN_ID,
    WSL_RUN_ID,
    WSL_STABILITY_RUN_ID,
    WSL_TRAINING_SMOKE_STAGE1_RUN_ID,
    WSL_TRAINING_SMOKE_STAGE2_RUN_ID,
    QLoRATrainingError,
    StageReporter,
    artifact_paths,
    attach_lora,
    ensure_unused_output,
    environment_snapshot,
    finalize_stability_failure,
    load_tokenizer_and_model,
    model_statistics,
    publish_result_artifact,
    release_cuda,
    require_execution_approval,
    run_allocation_smoke,
    run_backward_diagnostic,
    run_full_training,
    run_stability_smoke,
    run_training_smoke,
    set_reproducible_seeds,
    sha256_file,
    smoke_is_valid,
    validate_backward_diagnostic,
    validate_backward_diagnostics,
    validate_environment,
    validate_result_artifact,
    validate_runtime_config,
    validate_stability_failure,
    validate_stability_result,
    validate_tokenized_dataset,
    validate_training_smoke_stage,
    verify_git_identity,
)
from src.training.sft_tokenization import SFTTokenizationError

MODES = (
    "allocation",
    "backward",
    "training-smoke-1",
    "training-smoke-2",
    "stability",
    "full",
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--mode", required=True, choices=MODES)
    value.add_argument("--profile", choices=("windows", "wsl"), default="windows")
    value.add_argument("--approved-run-id", required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--backward-length", type=int, choices=BACKWARD_DIAGNOSTIC_LENGTHS)
    value.add_argument("--repository", type=Path, default=Path.cwd())
    value.add_argument("--config", type=Path, default=Path("configs/training/dohalm-v0.1-qlora.yaml"))
    value.add_argument("--tokenized-root", type=Path, required=True)
    value.add_argument("--model-cache-root", type=Path, required=True)
    value.add_argument("--training-root", type=Path, required=True)
    value.add_argument("--stage-worker", action="store_true", help=argparse.SUPPRESS)
    return value


def _runtime_ids(profile: str) -> dict[str, str]:
    if profile == "wsl":
        return {
            "allocation": WSL_ALLOCATION_SMOKE_RUN_ID,
            "backward": WSL_BACKWARD_DIAGNOSTIC_RUN_ID,
            "training_stage_1": WSL_TRAINING_SMOKE_STAGE1_RUN_ID,
            "training_stage_2": WSL_TRAINING_SMOKE_STAGE2_RUN_ID,
            "stability": WSL_STABILITY_RUN_ID,
            "full": WSL_RUN_ID,
        }
    return {
        "allocation": ALLOCATION_SMOKE_RUN_ID,
        "backward": BACKWARD_DIAGNOSTIC_RUN_ID,
        "training_stage_1": TRAINING_SMOKE_RUN_ID,
        "training_stage_2": TRAINING_SMOKE_RUN_ID,
        "stability": "NOT-AVAILABLE-WINDOWS",
        "full": RUN_ID,
    }


def _expected_run_id(mode: str, profile: str) -> str:
    ids = _runtime_ids(profile)
    if mode == "allocation":
        return ids["allocation"]
    if mode == "backward":
        return ids["backward"]
    if mode == "training-smoke-1":
        return ids["training_stage_1"]
    if mode == "training-smoke-2":
        return ids["training_stage_2"]
    return ids[mode]


def _roots(training_root: Path, profile: str) -> dict[str, Path]:
    ids = _runtime_ids(profile)
    return {
        "allocation": training_root / "smoke" / ids["allocation"],
        "backward": training_root / "diagnostics" / ids["backward"],
        "training_stage_1": (
            training_root / "smoke" / ids["training_stage_1"] / "stage-1"
        ),
        "training_stage_2": (
            training_root / "smoke" / ids["training_stage_2"] / "stage-2"
        ),
        "stability": training_root / "stability" / ids["stability"],
    }


def _validate_allocation(
    root: Path,
    *,
    expected_head: str,
    expected_run_id: str,
) -> dict[str, object]:
    result = validate_result_artifact(
        root,
        filename="allocation-result.yaml",
        expected_run_id=expected_run_id,
    )
    git = result.get("git")
    if (
        result.get("backward_calls") != 0
        or result.get("optimizer_creations") != 0
        or result.get("optimizer_steps") != 0
        or len(result.get("batches", [])) != 2
        or not isinstance(git, dict)
        or git.get("head") != expected_head
    ):
        raise QLoRATrainingError("ALLOCATION_RESULT_INVALID")
    return result


def _load_runtime(
    arguments: argparse.Namespace,
    reporter: StageReporter,
) -> tuple[dict[str, object], dict[str, object]]:
    with reporter.stage("environment_validation", timeout_seconds=120):
        git_identity = verify_git_identity(
            arguments.repository, expected_head=arguments.expected_head,
        )
        config = validate_runtime_config(arguments.config)
        environment = environment_snapshot()
        environment["execution_command"] = [sys.executable, *sys.argv]
        environment["config_fingerprint"] = sha256_file(arguments.config)
        environment["model_revision"] = config["model"]["revision"]  # type: ignore[index]
        validate_environment(environment)
    return git_identity, {"config": config, "environment": environment}


def _load_model_and_data(
    arguments: argparse.Namespace,
    config: dict[str, object],
    reporter: StageReporter,
) -> tuple[object, ...]:
    from bitsandbytes.nn import Linear4bit
    from datasets import load_from_disk

    with reporter.stage("model_loading", timeout_seconds=900):
        tokenizer, base_model = load_tokenizer_and_model(
            config, cache_dir=arguments.model_cache_root,
        )
    with reporter.stage("quantization_validation", timeout_seconds=120):
        if not any(isinstance(module, Linear4bit) for module in base_model.modules()):
            raise QLoRATrainingError("MODEL_NOT_QUANTIZED_4BIT")
    with reporter.stage("lora_injection", timeout_seconds=120):
        model = attach_lora(base_model, config)
    with reporter.stage("device_validation", timeout_seconds=120):
        statistics = model_statistics(model, tokenizer)
    with reporter.stage("dataset_loading", timeout_seconds=120):
        train = load_from_disk(arguments.tokenized_root / "train")
        validation = load_from_disk(arguments.tokenized_root / "validation")
    return tokenizer, base_model, model, train, validation, statistics


def run(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.mode == "stability" and arguments.profile != "wsl":
        raise QLoRATrainingError("STABILITY_REQUIRES_WSL_PROFILE")
    ids = _runtime_ids(arguments.profile)
    expected_run = _expected_run_id(arguments.mode, arguments.profile)
    require_execution_approval(expected_run_id=expected_run, approved_run_id=arguments.approved_run_id)
    if arguments.mode == "backward" and arguments.backward_length is None:
        raise QLoRATrainingError("BACKWARD_DIAGNOSTIC_LENGTH_REQUIRED")
    if arguments.mode != "backward" and arguments.backward_length is not None:
        raise QLoRATrainingError("BACKWARD_DIAGNOSTIC_LENGTH_NOT_ALLOWED")

    reporter = StageReporter()
    git_identity, runtime = _load_runtime(arguments, reporter)
    config = runtime["config"]
    environment = runtime["environment"]
    assert isinstance(config, dict) and isinstance(environment, dict)
    with reporter.stage("dataset_validation", timeout_seconds=120):
        dataset = validate_tokenized_dataset(arguments.tokenized_root)
    set_reproducible_seeds(42)
    roots = _roots(arguments.training_root, arguments.profile)

    if arguments.mode == "allocation":
        paths = ensure_unused_output(roots["allocation"])
        try:
            tokenizer, base_model, model, train, validation, statistics = _load_model_and_data(
                arguments, config, reporter,
            )
            result = run_allocation_smoke(
                model=model,
                tokenizer=tokenizer,
                train_dataset=train,
                validation_dataset=validation,
                reporter=reporter,
                run_id=ids["allocation"],
            )
            result.update({
                "git": git_identity,
                "dataset": dataset,
                "model_statistics": statistics.__dict__,
            })
            publish_result_artifact(
                paths,
                filename="allocation-result.yaml",
                result=result,
                environment=environment,
            )
            del model, base_model
            release_cuda()
            return result
        except Exception:
            from src.training.qlora_training import quarantine_staging

            quarantine_staging(paths)
            raise

    allocation = _validate_allocation(
        roots["allocation"],
        expected_head=arguments.expected_head,
        expected_run_id=ids["allocation"],
    )
    if arguments.mode == "backward":
        assert arguments.backward_length is not None
        position = BACKWARD_DIAGNOSTIC_LENGTHS.index(arguments.backward_length)
        for prior_length in BACKWARD_DIAGNOSTIC_LENGTHS[:position]:
            validate_backward_diagnostic(
                roots["backward"] / f"length-{prior_length}",
                target_length=prior_length,
                expected_head=arguments.expected_head,
                expected_run_id=ids["backward"],
            )
        paths = ensure_unused_output(roots["backward"] / f"length-{arguments.backward_length}")
        try:
            tokenizer, base_model, model, train, validation, _ = _load_model_and_data(
                arguments, config, reporter,
            )
            result = run_backward_diagnostic(
                model=model,
                tokenizer=tokenizer,
                train_dataset=train,
                validation_dataset=validation,
                target_length=arguments.backward_length,
                reporter=reporter,
                run_id=ids["backward"],
                timeout_seconds=300 if arguments.profile == "wsl" else 600,
            )
            result.update({"git": git_identity, "dataset": dataset})
            publish_result_artifact(
                paths,
                filename="backward-result.yaml",
                result=result,
                environment=environment,
            )
            del model, base_model
            release_cuda()
            return result
        except Exception:
            from src.training.qlora_training import quarantine_staging

            quarantine_staging(paths)
            raise

    validate_backward_diagnostics(
        roots["backward"],
        expected_head=arguments.expected_head,
        expected_run_id=ids["backward"],
    )
    stage_one_root = roots["training_stage_1"]
    stage_two_root = roots["training_stage_2"]
    if arguments.mode == "training-smoke-1":
        paths = ensure_unused_output(stage_one_root)
        stage_number, micro_batches, validation_batches = 1, 2, 1
    elif arguments.mode == "training-smoke-2":
        validate_training_smoke_stage(
            stage_one_root,
            stage_number=1,
            expected_head=arguments.expected_head,
            expected_run_id=ids["training_stage_1"],
        )
        paths = ensure_unused_output(stage_two_root)
        stage_number, micro_batches, validation_batches = 2, 16, 2
    elif arguments.mode == "stability":
        stage_two_result = validate_training_smoke_stage(
            stage_two_root,
            stage_number=2,
            expected_head=arguments.expected_head,
            expected_run_id=ids["training_stage_2"],
        )
        paths = ensure_unused_output(roots["stability"])
        tokenizer, base_model, model, train, _, statistics = _load_model_and_data(
            arguments, config, reporter,
        )
        try:
            result = run_stability_smoke(
                paths=paths,
                model=model,
                tokenizer=tokenizer,
                train_dataset=train,
                config=config,
                environment=environment,
                git_identity=git_identity,
                dataset_identity=dataset,
                model_statistics_value=statistics.__dict__,
                training_smoke_result=stage_two_result,
                reporter=reporter,
                run_id=ids["stability"],
                supervisor_managed_failure=True,
            )
            del model, base_model
            release_cuda()
            return result
        except Exception:
            del model, base_model
            release_cuda()
            raise
    else:
        result = smoke_is_valid(
            stage_two_root,
            expected_head=arguments.expected_head,
            expected_run_id=ids["training_stage_2"],
        )
        if arguments.profile == "wsl":
            stability = validate_stability_result(
                roots["stability"],
                expected_head=arguments.expected_head,
                expected_run_id=ids["stability"],
                expected_config_fingerprint=sha256_file(arguments.config),
            )
            estimate = stability.get("runtime_estimate")
        else:
            estimate = result.get("runtime_estimate")
        if not isinstance(estimate, dict) or estimate.get("acceptable") is not True:
            raise QLoRATrainingError("FULL_RUNTIME_ESTIMATE_NOT_ACCEPTABLE")
        full_root = arguments.training_root / "DohaLM-v0.1" / ids["full"]
        paths = ensure_unused_output(full_root)
        with reporter.stage("full_training", timeout_seconds=72 * 3600):
            return run_full_training(
                paths=paths,
                config=config,
                config_path=arguments.config,
                cache_dir=arguments.model_cache_root,
                tokenized_root=arguments.tokenized_root,
                repository=arguments.repository,
                expected_head=arguments.expected_head,
                environment=environment,
                git_identity=git_identity,
                run_id=ids["full"],
                reporter=reporter,
            )

    tokenizer, base_model, model, _, _, statistics = _load_model_and_data(
        arguments, config, reporter,
    )
    del model, base_model
    release_cuda()
    return run_training_smoke(
        paths=paths,
        config=config,
        cache_dir=arguments.model_cache_root,
        tokenized_root=arguments.tokenized_root,
        environment=environment,
        git_identity=git_identity,
        allocation_result=allocation,
        model_statistics_value=statistics.__dict__,
        micro_batches=micro_batches,
        validation_batches=validation_batches,
        stage_number=stage_number,
        reporter=reporter,
        run_id=(
            ids["training_stage_1"]
            if stage_number == 1
            else ids["training_stage_2"]
        ),
        micro_batch_timeout_seconds=300 if arguments.profile == "wsl" else 1800,
    )


def _read_pipe(
    name: str,
    stream: object,
    messages: queue.Queue[tuple[str, str]],
) -> None:
    for line in stream:  # type: ignore[union-attr]
        messages.put((name, line))


def _gpu_timeout_snapshot() -> dict[str, object]:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        utilization, used, total = completed.stdout.strip().splitlines()[0].split(", ")
        return {
            "gpu_utilization_percent": int(utilization),
            "gpu_memory_used_mib": int(used),
            "gpu_memory_total_mib": int(total),
        }
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {"gpu_snapshot": "unavailable"}


def _finalize_supervised_stability_failure(
    argv: list[str],
    *,
    worker_exit_code: int,
    failure_code: str,
    active_stage: dict[str, object] | None,
) -> dict[str, object] | None:
    arguments = parser().parse_args(argv)
    if arguments.mode != "stability":
        return None
    stability_root = _roots(arguments.training_root, arguments.profile)["stability"]
    paths = artifact_paths(stability_root)
    if paths.failed.is_dir():
        return validate_stability_failure(
            paths.failed,
            expected_head=arguments.expected_head,
            expected_run_id=arguments.approved_run_id,
        )
    if not paths.staging.is_dir() or paths.final.exists():
        raise QLoRATrainingError("STABILITY_FAILURE_SOURCE_INVALID")
    try:
        last_state = json.loads(
            (paths.staging / "stage-state.json").read_text(encoding="utf-8"),
        )
    except (OSError, UnicodeError, ValueError):
        raise QLoRATrainingError("STABILITY_FAILURE_SOURCE_INVALID") from None
    stage = (
        str(active_stage.get("stage", "worker_exit"))
        if active_stage
        else str(last_state.get("current_stage", "worker_exit"))
    )
    timeout = (
        float(active_stage.get("timeout_seconds", 0.0))
        if active_stage
        else 300.0
    )
    return finalize_stability_failure(
        paths,
        failure_code=failure_code,
        failed_stage=stage,
        worker_exit_code=worker_exit_code,
        watchdog_seconds=timeout,
        failed_microbatch_index=(
            int(active_stage["micro_batch"])
            if active_stage and active_stage.get("micro_batch") is not None
            else None
        ),
        sequence_length=(
            int(active_stage["sequence_length"])
            if active_stage and active_stage.get("sequence_length") is not None
            else None
        ),
        allocated_vram_bytes=(
            int(active_stage["allocated_bytes"])
            if active_stage and active_stage.get("allocated_bytes") is not None
            else None
        ),
        reserved_vram_bytes=(
            int(active_stage["reserved_bytes"])
            if active_stage and active_stage.get("reserved_bytes") is not None
            else None
        ),
    )


def supervise(argv: list[str]) -> int:
    command = [sys.executable, str(Path(__file__).resolve()), *argv, "--stage-worker"]
    process = subprocess.Popen(
        command,
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    assert process.stdout is not None and process.stderr is not None
    messages: queue.Queue[tuple[str, str]] = queue.Queue()
    threads = [
        threading.Thread(target=_read_pipe, args=("stdout", process.stdout, messages), daemon=True),
        threading.Thread(target=_read_pipe, args=("stderr", process.stderr, messages), daemon=True),
    ]
    for thread in threads:
        thread.start()
    stdout_lines: list[str] = []
    active_stage: dict[str, object] | None = None
    deadline: float | None = None
    while process.poll() is None:
        try:
            name, line = messages.get(timeout=0.1)
        except queue.Empty:
            name, line = "", ""
        if name == "stdout":
            stdout_lines.append(line)
        elif name == "stderr":
            print(line, end="", file=sys.stderr, flush=True)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = None
            if isinstance(event, dict) and event.get("status") == "started":
                active_stage = event
                deadline = time.monotonic() + float(event["timeout_seconds"])
            elif isinstance(event, dict) and event.get("status") in {"passed", "failed", "timeout"}:
                if active_stage and event.get("stage") == active_stage.get("stage"):
                    active_stage, deadline = None, None
        if deadline is not None and time.monotonic() > deadline:
            process.kill()
            process.wait(timeout=30)
            timed_out_stage = active_stage.get("stage") if active_stage else "unknown"
            failure_code = (
                "STABILITY_RESULT_PUBLISH_TIMEOUT"
                if timed_out_stage == "stability_result_publish"
                else "STAGE_HARD_TIMEOUT"
            )
            try:
                finalized = _finalize_supervised_stability_failure(
                    argv,
                    worker_exit_code=int(process.returncode or -9),
                    failure_code=failure_code,
                    active_stage=active_stage,
                )
            except (OSError, QLoRATrainingError, ValueError) as error:
                finalized = None
                failure_code = f"STABILITY_FAILURE_ARTIFACT_FAILED:{error}"
            failure = {
                "status": "blocked",
                "error_code": failure_code,
                "stage": timed_out_stage,
                "sequence_length": active_stage.get("sequence_length") if active_stage else None,
                "child_pid": process.pid,
                "allocated_bytes": active_stage.get("allocated_bytes") if active_stage else None,
                "reserved_bytes": active_stage.get("reserved_bytes") if active_stage else None,
                "peak_allocated_bytes": (
                    active_stage.get("peak_allocated_bytes") if active_stage else None
                ),
                "failure_artifact_validated": finalized is not None,
                **_gpu_timeout_snapshot(),
            }
            print(json.dumps(failure, sort_keys=True))
            return 2
    for thread in threads:
        thread.join(timeout=5)
    while not messages.empty():
        name, line = messages.get_nowait()
        if name == "stdout":
            stdout_lines.append(line)
        else:
            print(line, end="", file=sys.stderr, flush=True)
    print("".join(stdout_lines), end="")
    return_code = int(process.returncode or 0)
    if return_code != 0:
        try:
            finalized = _finalize_supervised_stability_failure(
                argv,
                worker_exit_code=return_code,
                failure_code=("WORKER_EXIT_124" if return_code == 124 else "WORKER_ABNORMAL_EXIT"),
                active_stage=active_stage,
            )
        except (OSError, QLoRATrainingError, ValueError) as error:
            print(json.dumps({
                "status": "blocked",
                "error_code": f"STABILITY_FAILURE_ARTIFACT_FAILED:{error}",
                "worker_exit_code": return_code,
                "failure_artifact_validated": False,
            }, sort_keys=True))
            return 2
        if finalized is not None:
            print(json.dumps({
                "status": "blocked",
                "error_code": str(finalized["failure_code"]),
                "worker_exit_code": return_code,
                "failure_artifact_validated": True,
            }, sort_keys=True))
    return return_code


def main(argv: list[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    arguments = parser().parse_args(raw_arguments)
    if not arguments.stage_worker:
        return supervise(raw_arguments)
    try:
        result = run(arguments)
    except (QLoRATrainingError, SFTTokenizationError, OSError, RuntimeError, ValueError) as error:
        import torch

        message = str(error)
        code = "CUDA_OOM" if "out of memory" in message.lower() else (
            message if message.isupper() else "QLORA_EXECUTION_FAILED"
        )
        failure: dict[str, object] = {"status": "blocked", "error_code": code}
        if torch.cuda.is_available():
            failure["cuda_memory"] = {
                "allocated_bytes": torch.cuda.memory_allocated(),
                "reserved_bytes": torch.cuda.memory_reserved(),
                "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            }
        print(json.dumps(failure, sort_keys=True))
        return 2
    print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
