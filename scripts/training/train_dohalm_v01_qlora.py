"""Execute approved DohaLM v0.1 QLoRA smoke or full training."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from src.training.qlora_training import (
    RUN_ID,
    SMOKE_RUN_ID,
    QLoRATrainingError,
    attach_lora,
    ensure_unused_output,
    environment_snapshot,
    load_tokenizer_and_model,
    model_statistics,
    release_cuda,
    require_execution_approval,
    run_allocation_smoke,
    run_full_training,
    run_training_smoke,
    set_reproducible_seeds,
    smoke_is_valid,
    validate_environment,
    validate_runtime_config,
    validate_tokenized_dataset,
    verify_git_identity,
)
from src.training.sft_tokenization import SFTTokenizationError


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--mode", required=True, choices=("smoke", "full"))
    value.add_argument("--approved-run-id", required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--repository", type=Path, default=Path.cwd())
    value.add_argument("--config", type=Path, default=Path("configs/training/dohalm-v0.1-qlora.yaml"))
    value.add_argument("--tokenized-root", type=Path, required=True)
    value.add_argument("--model-cache-root", type=Path, required=True)
    value.add_argument("--training-root", type=Path, required=True)
    return value


def run(arguments: argparse.Namespace) -> dict[str, object]:
    expected_run = SMOKE_RUN_ID if arguments.mode == "smoke" else RUN_ID
    require_execution_approval(
        expected_run_id=expected_run,
        approved_run_id=arguments.approved_run_id,
    )
    git_identity = verify_git_identity(
        arguments.repository, expected_head=arguments.expected_head,
    )
    config = validate_runtime_config(arguments.config)
    environment = environment_snapshot()
    environment["execution_command"] = [sys.executable, *sys.argv]
    validate_environment(environment)
    dataset = validate_tokenized_dataset(arguments.tokenized_root)
    set_reproducible_seeds(42)
    if arguments.mode == "smoke":
        smoke_root = (
            arguments.training_root / "smoke" / SMOKE_RUN_ID
        )
        paths = ensure_unused_output(smoke_root)
        try:
            from datasets import load_from_disk

            tokenizer, base_model = load_tokenizer_and_model(
                config, cache_dir=arguments.model_cache_root,
            )
            model = attach_lora(base_model, config)
            statistics_value = model_statistics(model, tokenizer)
            train = load_from_disk(arguments.tokenized_root / "train")
            allocation = run_allocation_smoke(
                model=model,
                tokenizer=tokenizer,
                train_dataset=train,
                config=config,
            )
            del model, base_model
            release_cuda()
            result = run_training_smoke(
                paths=paths,
                config=config,
                cache_dir=arguments.model_cache_root,
                tokenized_root=arguments.tokenized_root,
                environment=environment,
                git_identity=git_identity,
                allocation_result=allocation,
                model_statistics_value=statistics_value.__dict__,
            )
            result["dataset"] = dataset
            return result
        except Exception:
            from src.training.qlora_training import quarantine_staging

            quarantine_staging(paths)
            raise
    smoke_root = arguments.training_root / "smoke" / SMOKE_RUN_ID
    smoke_is_valid(smoke_root, expected_head=arguments.expected_head)
    full_root = arguments.training_root / "DohaLM-v0.1" / RUN_ID
    paths = ensure_unused_output(full_root)
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
    )


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        result = run(arguments)
    except (QLoRATrainingError, SFTTokenizationError, OSError, RuntimeError, ValueError) as error:
        import torch

        message = str(error)
        if "out of memory" in message.lower():
            code = "CUDA_OOM"
        else:
            code = message if message.isupper() else "QLORA_EXECUTION_FAILED"
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
