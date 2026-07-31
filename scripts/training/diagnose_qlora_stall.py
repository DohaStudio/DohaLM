"""Run an explicit, non-identifying QLoRA backward-stall diagnostic."""

from __future__ import annotations

import argparse
import json
import queue
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

from src.training.qlora_training import (
    DynamicSFTCollator,
    QLoRATrainingError,
    StageReporter,
    attach_lora,
    batch_statistics,
    canonical_fingerprint,
    create_optimizer,
    finite_gradients,
    load_tokenizer_and_model,
    move_batch,
    release_cuda,
    set_reproducible_seeds,
    stability_batch_identity,
    validate_runtime_config,
    validate_tokenized_dataset,
)

DIAGNOSTIC_ID = "DOHALM-V0.1-QLORA-STALL-DIAG-WSL-20260731-0001"
MODES = (
    "isolated", "sequential-no-optimizer", "sequential-accumulation",
    "sequential-cleanup", "partial-34-42", "bf16-forward",
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--diagnostic-id", required=True)
    value.add_argument("--mode", required=True, choices=MODES)
    value.add_argument("--attempt", type=int, required=True)
    value.add_argument("--config", type=Path, required=True)
    value.add_argument("--tokenized-root", type=Path, required=True)
    value.add_argument("--model-cache-root", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return value


def _resource_snapshot() -> dict[str, object]:
    import torch

    memory = torch.cuda.memory_stats()
    return {
        "allocated_vram_bytes": torch.cuda.memory_allocated(),
        "reserved_vram_bytes": torch.cuda.memory_reserved(),
        "peak_vram_bytes": torch.cuda.max_memory_allocated(),
        "inactive_split_bytes": memory.get("inactive_split_bytes.all.current", 0),
        "active_allocations": memory.get("allocation.all.current", 0),
    }


def _gradient_fingerprint(model: object) -> str:
    values = []
    for name, parameter in model.named_parameters():  # type: ignore[attr-defined]
        if parameter.grad is not None:
            values.append({
                "name": name,
                "shape": list(parameter.grad.shape),
                "norm": float(parameter.grad.detach().float().norm().item()),
            })
    return canonical_fingerprint(values)


def run_worker(arguments: argparse.Namespace) -> dict[str, object]:
    import torch
    from datasets import load_from_disk

    if arguments.diagnostic_id != DIAGNOSTIC_ID or arguments.attempt not in {1, 2, 3}:
        raise QLoRATrainingError("DIAGNOSTIC_ID_INVALID")
    if arguments.output.exists():
        raise QLoRATrainingError("DIAGNOSTIC_OUTPUT_ALREADY_EXISTS")
    config = validate_runtime_config(arguments.config)
    dataset_identity = validate_tokenized_dataset(arguments.tokenized_root)
    runtime_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    set_reproducible_seeds(42)
    reporter = StageReporter()
    with reporter.stage("model_loading", timeout_seconds=900):
        if arguments.mode == "bf16-forward":
            from peft import LoraConfig, TaskType, get_peft_model
            from transformers import AutoModelForCausalLM, AutoTokenizer

            from src.training.qlora_training import (
                MODEL_ID,
                MODEL_REVISION,
                TARGET_MODULES,
            )

            tokenizer = AutoTokenizer.from_pretrained(
                MODEL_ID, revision=MODEL_REVISION, cache_dir=arguments.model_cache_root,
                local_files_only=True, trust_remote_code=False, use_fast=True,
            )
            base_model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID, revision=MODEL_REVISION, cache_dir=arguments.model_cache_root,
                local_files_only=True, trust_remote_code=False, device_map={"": 0},
                dtype=torch.bfloat16, low_cpu_mem_usage=True,
            )
            lora = config["lora"]
            model = get_peft_model(base_model, LoraConfig(
                task_type=TaskType.CAUSAL_LM,
                inference_mode=False,
                r=int(lora["r"]),  # type: ignore[index]
                lora_alpha=int(lora["alpha"]),  # type: ignore[index]
                lora_dropout=float(lora["dropout"]),  # type: ignore[index]
                target_modules=list(TARGET_MODULES),
                bias="none",
            ))
            model.config.use_cache = False
        else:
            tokenizer, base_model = load_tokenizer_and_model(
                config, cache_dir=arguments.model_cache_root,
            )
            model = attach_lora(base_model, config)
    train = load_from_disk(arguments.tokenized_root / "train")
    indices = list(range(len(train)))
    random.Random(42).shuffle(indices)
    sampler_fingerprint = canonical_fingerprint(indices)
    first_64_hash = canonical_fingerprint(indices[:64])
    if arguments.mode in {"isolated", "bf16-forward"}:
        selected = [(42, indices[41])]
    elif arguments.mode == "partial-34-42":
        selected = list(enumerate(indices[33:42], start=34))
    else:
        selected = list(enumerate(indices[:42], start=1))
    training = config["training"]
    optimizer = None
    if arguments.mode in {"sequential-accumulation", "sequential-cleanup"}:
        optimizer = create_optimizer(
            model,
            learning_rate=float(training["learning_rate"]),  # type: ignore[index]
            weight_decay=float(training["weight_decay"]),  # type: ignore[index]
        )
        optimizer.zero_grad(set_to_none=True)
    collator = DynamicSFTCollator(pad_token_id=int(tokenizer.pad_token_id))
    model.train()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    records = []
    for microbatch, index in selected:
        source = train[index]
        batch = move_batch(collator([source]), device="cuda:0")
        statistics = batch_statistics(batch)
        identity = stability_batch_identity(
            source,
            dataset_index=index,
            padded_length=statistics["padded_length"],
            valid_label_tokens=statistics["label_tokens"],
            shuffle_seed=42,
            sampler_order_fingerprint=sampler_fingerprint,
            first_64_indices_hash=first_64_hash,
        )
        started = time.perf_counter()
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            output = model(**batch)
            loss = output.loss
        torch.cuda.synchronize()
        forward_seconds = time.perf_counter() - started
        if arguments.mode == "bf16-forward":
            records.append({
                "microbatch": microbatch,
                "identity": identity,
                "sequence_length": statistics["actual_sequence_length"],
                "forward_seconds": forward_seconds,
                "loss": float(loss.detach().item()),
                "backward_calls": 0,
                "optimizer_step": 0,
                **_resource_snapshot(),
            })
            del output, loss, batch
            continue
        backward_started = time.perf_counter()
        with reporter.stage(
            "diagnostic_backward",
            timeout_seconds=300,
            micro_batch=microbatch,
            sequence_length=statistics["actual_sequence_length"],
        ):
            (loss / 16).backward()
            torch.cuda.synchronize()
        backward_seconds = time.perf_counter() - backward_started
        finite, gradient_norm = finite_gradients(model)
        if not finite:
            raise QLoRATrainingError("DIAGNOSTIC_GRADIENT_NONFINITE")
        optimizer_step = 0
        if optimizer is not None and microbatch % 16 == 0:
            optimizer.step()
            torch.cuda.synchronize()
            optimizer.zero_grad(set_to_none=True)
            optimizer_step = microbatch // 16
        records.append({
            "microbatch": microbatch,
            "identity": identity,
            "sequence_length": statistics["actual_sequence_length"],
            "forward_seconds": forward_seconds,
            "backward_seconds": backward_seconds,
            "loss": float(loss.detach().item()),
            "gradient_norm": gradient_norm,
            "gradient_fingerprint": _gradient_fingerprint(model),
            "optimizer_step": optimizer_step,
            **_resource_snapshot(),
        })
        if optimizer is None:
            model.zero_grad(set_to_none=True)
        del output, loss, batch
        if arguments.mode == "sequential-cleanup":
            torch.cuda.empty_cache()
    result = {
        "status": "passed",
        "diagnostic_id": arguments.diagnostic_id,
        "mode": arguments.mode,
        "attempt": arguments.attempt,
        "dataset": dataset_identity,
        "runtime_head": runtime_head,
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "bitsandbytes": __import__("bitsandbytes").__version__,
        "records": records,
    }
    arguments.output.mkdir(parents=True)
    (arguments.output / "diagnostic-result.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    release_cuda()
    return result


def _read_stderr(stream: object, messages: queue.Queue[str]) -> None:
    for line in stream:  # type: ignore[union-attr]
        messages.put(line)


def supervise(argv: list[str]) -> int:
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), *argv, "--worker"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stderr is not None
    messages: queue.Queue[str] = queue.Queue()
    thread = threading.Thread(target=_read_stderr, args=(process.stderr, messages), daemon=True)
    thread.start()
    deadline = None
    active: dict[str, object] | None = None
    while process.poll() is None:
        try:
            line = messages.get(timeout=0.1)
        except queue.Empty:
            line = ""
        if line:
            print(line, end="", file=sys.stderr, flush=True)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = None
            if isinstance(event, dict) and event.get("status") == "started":
                active = event
                deadline = time.monotonic() + float(event["timeout_seconds"])
            elif isinstance(event, dict) and event.get("status") in {"passed", "failed", "timeout"}:
                if active and event.get("stage") == active.get("stage"):
                    active, deadline = None, None
        if deadline is not None and time.monotonic() > deadline:
            process.kill()
            process.wait(timeout=30)
            print(json.dumps({
                "status": "failed",
                "failure_code": "DIAGNOSTIC_BACKWARD_HARD_TIMEOUT",
                "active_stage": active,
            }, sort_keys=True))
            return 2
    stdout, _ = process.communicate(timeout=30)
    print(stdout, end="")
    return int(process.returncode or 0)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    arguments = parser().parse_args(raw)
    if not arguments.worker:
        return supervise(raw)
    try:
        print(json.dumps(run_worker(arguments), sort_keys=True))
        return 0
    except (OSError, QLoRATrainingError, RuntimeError, ValueError) as error:
        print(json.dumps({
            "status": "failed",
            "failure_code": str(error),
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
