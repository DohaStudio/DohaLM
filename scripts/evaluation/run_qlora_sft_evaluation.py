"""DohaLM v0.1 QLoRA evaluation-only CLI; never trains or writes model artifacts."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from src.data.checksums import checksum_value, file_checksum
from src.evaluation.qlora_sft import (
    EXPECTED_MODELS,
    QLoRAEvaluationError,
    aggregate_generation,
    deterministic_metric_fingerprint,
    environment_snapshot,
    evaluate_generation,
    evaluate_loss,
    load_evaluation_config,
    load_model_for_evaluation,
    load_prompt_records,
    model_mode_report,
    model_parameter_checksums,
    release_model,
    verify_checksum_manifest,
    verify_training_artifacts,
    write_evaluation_artifact,
)
from src.training.qlora_training import DynamicSFTCollator, validate_tokenized_dataset
from src.training.sft_tokenization import validate_qlora_config


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Read-only DohaLM v0.1 QLoRA evaluation")
    value.add_argument("--config", type=Path, required=True)
    value.add_argument("--qlora-config", type=Path, required=True)
    value.add_argument("--prompt-config", type=Path, required=True)
    value.add_argument("--repository", type=Path, required=True)
    value.add_argument("--training-run-root", type=Path, required=True)
    value.add_argument("--tokenized-root", type=Path, required=True)
    value.add_argument("--processed-root", type=Path, required=True)
    value.add_argument("--raw-dataset-root", type=Path, required=True)
    value.add_argument("--model-cache-root", type=Path, required=True)
    value.add_argument("--output-root", type=Path, required=True)
    value.add_argument("--evaluation-id", required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--execute", action="store_true")
    return value


def _git_identity(repository: Path, expected_head: str) -> dict[str, Any]:
    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments], check=True,
            capture_output=True, text=True,
        )
        return completed.stdout.strip()
    try:
        head = git("rev-parse", "HEAD")
        branch = git("branch", "--show-current")
        origin = git("rev-parse", "origin/develop")
        status = git("status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        raise QLoRAEvaluationError("GIT_IDENTITY_INVALID") from None
    if head != expected_head or origin != expected_head or branch != "develop" or status:
        raise QLoRAEvaluationError("GIT_IDENTITY_MISMATCH")
    return {"head": head, "branch": branch, "origin_develop": origin, "working_tree_clean": True}


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _validate_paths(arguments: argparse.Namespace) -> None:
    required_directories = (
        arguments.repository, arguments.training_run_root, arguments.tokenized_root,
        arguments.processed_root, arguments.raw_dataset_root, arguments.model_cache_root,
    )
    if any(not path.resolve().is_dir() for path in required_directories):
        raise QLoRAEvaluationError("EVALUATION_PATH_INVALID")
    output = arguments.output_root.resolve()
    if any(_inside(output, path) or _inside(path, output) for path in (
        arguments.repository, arguments.training_run_root, arguments.tokenized_root,
        arguments.processed_root, arguments.raw_dataset_root,
    )):
        raise QLoRAEvaluationError("EVALUATION_OUTPUT_OVERLAP")


def _load_qlora_config(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise QLoRAEvaluationError("QLORA_CONFIG_INVALID") from None
    if not isinstance(value, dict):
        raise QLoRAEvaluationError("QLORA_CONFIG_INVALID")
    validate_qlora_config(value, bf16_supported=True)
    return value


def _deterministic_loss(loss: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in loss.items() if key != "elapsed_seconds"}


def _evaluate_model(
    *, name: str, adapter_root: Path | None, qlora_config: Mapping[str, Any],
    cache_root: Path, dataset: Any, categories: list[str], prompts: list[Any],
    train_output_hashes: set[str], evaluation: Mapping[str, Any], generation: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import torch

    tokenizer, model, mode_before = load_model_for_evaluation(
        config=qlora_config, cache_dir=cache_root, adapter_root=adapter_root,
    )
    collator = DynamicSFTCollator(
        pad_token_id=int(tokenizer.pad_token_id),
        pad_to_multiple_of=int(evaluation["pad_to_multiple_of"]),
    )
    repeats: list[dict[str, Any]] = []
    generation_rows: list[dict[str, Any]] = []
    for repeat in range(int(evaluation["deterministic_repeats"])):
        torch.manual_seed(int(evaluation["seed"]))
        torch.cuda.manual_seed_all(int(evaluation["seed"]))
        loss = evaluate_loss(
            model, dataset, collator, categories=categories,
            comparison_batches=int(evaluation["comparison_batches"]),
        )
        generated = evaluate_generation(
            model, tokenizer, prompts,
            max_new_tokens=int(generation["max_new_tokens"]),
            repetition_penalty=float(generation["repetition_penalty"]),
            train_output_hashes=train_output_hashes,
        )
        fingerprint = deterministic_metric_fingerprint(loss, generated)
        repeats.append({
            "repeat": repeat + 1, "metric_fingerprint": fingerprint,
            "loss": _deterministic_loss(loss), "generation": aggregate_generation(generated),
        })
        if repeat == 0:
            generation_rows = generated["rows"]
    if repeats[0]["metric_fingerprint"] != repeats[1]["metric_fingerprint"]:
        raise QLoRAEvaluationError("EVALUATION_NONDETERMINISTIC")
    mode_after = model_mode_report(model)
    for key, value in mode_after.items():
        if mode_before.get(key) != value:
            raise QLoRAEvaluationError("MODEL_MODE_CHANGED")
    identity_after = model_parameter_checksums(model)
    if any(mode_before[key] != value for key, value in identity_after.items()):
        raise QLoRAEvaluationError("EVALUATION_MUTATED_MODEL")
    peak = int(torch.cuda.max_memory_allocated())
    result = {
        "model": name, "mode": mode_before, "peak_allocated_bytes": peak,
        "repeat_fingerprints": [item["metric_fingerprint"] for item in repeats],
        "deterministic": True, "loss": repeats[0]["loss"],
        "generation": repeats[0]["generation"],
    }
    release_model(model, tokenizer)
    return result, generation_rows


def _loss_comparison(models: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    rows = {}
    for name in EXPECTED_MODELS:
        loss = models[name]["loss"]
        rows[name] = {
            "token_weighted_loss": loss["token_weighted_loss"],
            "batch_mean_loss": loss["batch_mean_loss"],
            "perplexity": loss["perplexity"],
            "valid_label_tokens": loss["valid_label_tokens"],
            "rows": loss["rows"],
        }
    base = rows["base"]["token_weighted_loss"]
    for name in EXPECTED_MODELS[1:]:
        value = rows[name]["token_weighted_loss"]
        rows[name]["absolute_improvement_vs_base"] = base - value
        rows[name]["relative_improvement_vs_base"] = (base - value) / base
    rows["checkpoint-1947"]["difference_vs_final"] = (
        rows["checkpoint-1947"]["token_weighted_loss"] - rows["final-adapter"]["token_weighted_loss"]
    )
    best = min(EXPECTED_MODELS, key=lambda item: rows[item]["token_weighted_loss"])
    return {"models": rows, "best_model": best}


def _generation_comparison(models: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {
        name: {
            "overall": models[name]["generation"]["overall"],
            "by_kind": models[name]["generation"]["by_kind"],
        }
        for name in EXPECTED_MODELS
    }


def _category_metrics(models: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    categories = sorted(models["base"]["loss"]["category_metrics"])
    result: dict[str, Any] = {}
    for category in categories:
        base = models["base"]["loss"]["category_metrics"][category]
        final = models["final-adapter"]["loss"]["category_metrics"][category]
        result[category] = {
            "validation_rows": base["rows"], "valid_label_tokens": base["valid_label_tokens"],
            "base_loss": base["token_weighted_loss"], "adapter_loss": final["token_weighted_loss"],
            "loss_improvement": base["token_weighted_loss"] - final["token_weighted_loss"],
            "base_generation": models["base"]["generation"]["by_category"].get(category),
            "adapter_generation": models["final-adapter"]["generation"]["by_category"].get(category),
        }
    return result


def _length_metrics(models: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    buckets = sorted(models["base"]["loss"]["length_metrics"])
    return {
        bucket: {
            "base_loss": models["base"]["loss"]["length_metrics"][bucket],
            "adapter_loss": models["final-adapter"]["loss"]["length_metrics"][bucket],
            "base_generation": models["base"]["generation"]["by_length"].get(bucket),
            "adapter_generation": models["final-adapter"]["generation"]["by_length"].get(bucket),
        }
        for bucket in buckets
    }


def _failure_analysis(
    base_rows: list[dict[str, Any]], final_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    base = {row["sample_hash"]: row for row in base_rows}
    final = {row["sample_hash"]: row for row in final_rows}
    if set(base) != set(final):
        raise QLoRAEvaluationError("GENERATION_SAMPLE_MISMATCH")
    groups: dict[str, list[str]] = {
        "improved": [], "similar": [], "degraded": [], "reference_mismatch": [],
        "repetition": [], "incomplete": [], "format_error": [],
    }
    serious = 0
    for sample_hash in sorted(base):
        before, after = base[sample_hash], final[sample_hash]
        delta = after["character_f1"] - before["character_f1"]
        groups["improved" if delta > .02 else "degraded" if delta < -.02 else "similar"].append(sample_hash)
        if after["character_f1"] < .2:
            groups["reference_mismatch"].append(sample_hash)
        if after["repetition"]:
            groups["repetition"].append(sample_hash)
        if after["maximum_length_reached"] and not after["eos_terminated"]:
            groups["incomplete"].append(sample_hash)
        if after["special_token_exposure"] or after["prompt_echo"]:
            groups["format_error"].append(sample_hash)
        serious += int(
            delta < -.10 or after["empty"] or after["repetition"]
            or after["special_token_exposure"] or after["pii_like"]
        )
    return {
        "groups": {name: {"count": len(values), "sample_hashes": values} for name, values in groups.items()},
        "serious_regression_count": serious,
        "serious_regression_rate": serious / len(base),
        "factual_error": {"status": "not_assessed_without_approved_judge"},
        "raw_text_stored": False,
    }


def _diagnosis(
    models: Mapping[str, Mapping[str, Any]], training: Mapping[str, Any],
) -> dict[str, Any]:
    final_loss = models["final-adapter"]["loss"]
    first = final_loss["reload_style_first_record_loss"]
    trainer = float(training["trainer_final_eval_loss"])
    reload_loss = float(training["reload_validation_loss"])
    batch_checksums = []
    for index in range(10):
        identities = []
        for name in EXPECTED_MODELS:
            row = models[name]["loss"]["comparison_batches"][index]
            identities.append({key: row[key] for key in (
                "input_ids_checksum", "attention_mask_checksum", "labels_checksum",
                "sequence_length", "attention_tokens", "valid_label_tokens",
            )})
        if any(identity != identities[0] for identity in identities[1:]):
            raise QLoRAEvaluationError("EVALUATION_BATCH_MISMATCH")
        batch_checksums.append(identities[0])
    if not math.isclose(first, reload_loss, rel_tol=0, abs_tol=5e-4):
        raise QLoRAEvaluationError("RELOAD_PATH_NOT_REPRODUCED")
    if not math.isclose(float(final_loss["batch_mean_loss"]), trainer, rel_tol=0, abs_tol=5e-4):
        raise QLoRAEvaluationError("TRAINER_PATH_NOT_REPRODUCED")
    return {
        "trainer_reported_loss": trainer, "reload_reported_loss": reload_loss,
        "reproduced_trainer_batch_mean_loss": final_loss["batch_mean_loss"],
        "reproduced_reload_first_record_loss": first,
        "autocast_first_record_loss": final_loss["first_record_loss"],
        "reload_autocast_delta": first - final_loss["first_record_loss"],
        "token_weighted_loss": final_loss["token_weighted_loss"],
        "same_batch_checksums": True, "comparison_batches": batch_checksums,
        "collator": {"class": "DynamicSFTCollator", "padding": "dynamic_right", "pad_to_multiple_of": 8, "label_padding": -100},
        "loss_mask": "assistant_only_with_eos", "trainer_reduction": "batch_mean_at_batch_size_1",
        "quality_reduction": "valid_token_weighted",
        "confirmed_cause": "EVAL_DATASET_MISMATCH",
        "cause_detail": "reload validation measured validation[0] only; Trainer measured all 1,287 rows. Reload also omitted Trainer BF16 autocast, producing a small secondary delta.",
    }


def _verdict(
    loss: Mapping[str, Any], generation: Mapping[str, Any], failure: Mapping[str, Any],
    adapter_reload_consistent: bool,
) -> dict[str, Any]:
    base_loss = loss["models"]["base"]["token_weighted_loss"]
    adapter_loss = loss["models"]["final-adapter"]["token_weighted_loss"]
    base_generation = generation["base"]["overall"]
    adapter_generation = generation["final-adapter"]["overall"]
    loss_better = adapter_loss < base_loss
    generation_better = (
        adapter_generation["character_f1"] > base_generation["character_f1"]
        and adapter_generation["rouge_l"] > base_generation["rouge_l"]
    )
    regression = float(failure["serious_regression_rate"])
    if loss_better and generation_better and regression < .05 and adapter_reload_consistent:
        verdict = "PASS"
    elif loss_better and generation_better and adapter_reload_consistent:
        verdict = "CONDITIONAL_PASS"
    elif loss_better and adapter_reload_consistent:
        verdict = "NEEDS_IMPROVEMENT"
    else:
        verdict = "FAIL"
    return {
        "verdict": verdict, "adapter_loss_better_than_base": loss_better,
        "generation_metrics_improved": generation_better,
        "serious_regression_rate": regression,
        "adapter_reload_consistent": adapter_reload_consistent,
        "deployment_ready": verdict == "PASS",
        "additional_training_recommended": verdict in {"NEEDS_IMPROVEMENT", "FAIL"},
    }


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    if not arguments.execute:
        raise QLoRAEvaluationError("EXPLICIT_EXECUTE_REQUIRED")
    config = load_evaluation_config(arguments.config)
    if arguments.evaluation_id != config["evaluation_id"]:
        raise QLoRAEvaluationError("EVALUATION_ID_MISMATCH")
    _validate_paths(arguments)
    git = _git_identity(arguments.repository, arguments.expected_head)
    training = verify_training_artifacts(arguments.training_run_root, config)
    tokenized = validate_tokenized_dataset(arguments.tokenized_root)
    if tokenized["dataset_fingerprint"] != config["dataset"]["fingerprint"]:
        raise QLoRAEvaluationError("TOKENIZED_DATASET_MISMATCH")
    verify_checksum_manifest(arguments.processed_root)
    qlora_config = _load_qlora_config(arguments.qlora_config)
    prompts, prompt_identity, train_output_hashes, categories = load_prompt_records(
        processed_root=arguments.processed_root, raw_root=arguments.raw_dataset_root,
        prompt_path=arguments.prompt_config,
        expected_validation_rows=int(config["dataset"]["validation_rows"]),
    )
    from datasets import load_from_disk
    validation = load_from_disk(arguments.tokenized_root / "validation")
    if len(validation) != int(config["dataset"]["validation_rows"]):
        raise QLoRAEvaluationError("VALIDATION_ROW_COUNT_MISMATCH")
    model_roots = {
        "base": None,
        "checkpoint-1750": arguments.training_run_root / "checkpoint-1750",
        "checkpoint-1947": arguments.training_run_root / "checkpoint-1947",
        "final-adapter": arguments.training_run_root / "final-adapter",
    }
    models: dict[str, Any] = {}
    generation_rows: dict[str, list[dict[str, Any]]] = {}
    for name in EXPECTED_MODELS:
        models[name], generation_rows[name] = _evaluate_model(
            name=name, adapter_root=model_roots[name], qlora_config=qlora_config,
            cache_root=arguments.model_cache_root, dataset=validation, categories=categories,
            prompts=prompts, train_output_hashes=train_output_hashes,
            evaluation=config["evaluation"], generation=config["generation"],
        )
    base_logits = models["base"]["loss"]["first_logits_checksum"]
    if any(models[name]["loss"]["first_logits_checksum"] == base_logits for name in EXPECTED_MODELS[1:]):
        raise QLoRAEvaluationError("ADAPTER_NOT_ACTIVE")
    if models["checkpoint-1947"]["repeat_fingerprints"] != models["final-adapter"]["repeat_fingerprints"]:
        raise QLoRAEvaluationError("FINAL_ADAPTER_CHECKPOINT_MISMATCH")
    loss = _loss_comparison(models)
    generation = _generation_comparison(models)
    category = _category_metrics(models)
    length = _length_metrics(models)
    failure = _failure_analysis(generation_rows["base"], generation_rows["final-adapter"])
    diagnosis = _diagnosis(models, training)
    adapter_consistent = (
        models["checkpoint-1947"]["mode"]["lora_parameter_checksum"]
        == models["final-adapter"]["mode"]["lora_parameter_checksum"]
        and models["checkpoint-1947"]["repeat_fingerprints"]
        == models["final-adapter"]["repeat_fingerprints"]
    )
    verdict = _verdict(loss, generation, failure, adapter_consistent)
    deterministic = {
        name: models[name]["repeat_fingerprints"] for name in EXPECTED_MODELS
    }
    evaluation_fingerprint = checksum_value({
        "config": file_checksum(arguments.config), "git": git["head"],
        "prompt_identity": prompt_identity, "models": deterministic,
        "loss": loss, "generation": generation, "category": category,
        "length": length, "failure": failure, "diagnosis": diagnosis,
    })
    result = {
        "schema_version": 1, "status": "completed", "evaluation_id": arguments.evaluation_id,
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "git": git, "training_run_id": config["training_run_id"],
        "base_revision": config["model"]["revision"],
        "adapter_fingerprint": config["model"]["adapter_fingerprint"],
        "dataset_fingerprint": config["dataset"]["fingerprint"],
        "tokenizer_fingerprint": config["dataset"]["tokenizer_fingerprint"],
        "evaluation_config_fingerprint": file_checksum(arguments.config),
        "row_hash_list_fingerprint": prompt_identity["row_hash_list_fingerprint"],
        "evaluation_fingerprint": evaluation_fingerprint,
        "deterministic_repeats": deterministic, "diagnosis": diagnosis,
        "model_validation": {
            name: {
                "mode": models[name]["mode"],
                "peak_allocated_bytes": models[name]["peak_allocated_bytes"],
                "deterministic": models[name]["deterministic"],
            }
            for name in EXPECTED_MODELS
        },
        "verdict": verdict, "training_started": False, "optimizer_steps": 0,
        "checkpoint_modified": False, "adapter_modified": False,
        "raw_text_stored": False, "token_ids_stored": False,
    }
    files = {
        "evaluation-config.yaml": {**config, "config_fingerprint": file_checksum(arguments.config), "prompt_identity": prompt_identity},
        "evaluation-result.yaml": result,
        "loss-comparison.json": loss,
        "generation-metrics.json": generation,
        "category-metrics.json": category,
        "length-metrics.json": length,
        "failure-analysis.json": failure,
        "environment.json": environment_snapshot(),
    }
    final = write_evaluation_artifact(
        output_root=arguments.output_root, evaluation_id=arguments.evaluation_id, files=files,
    )
    result["artifact_path"] = str(final)
    result["checksums_manifest"] = file_checksum(final / "checksums.sha256")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        result = run(arguments)
    except (QLoRAEvaluationError, OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({
            "status": "failed", "error_code": getattr(exc, "code", type(exc).__name__),
            "training_started": False, "optimizer_steps": 0,
        }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
