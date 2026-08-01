"""DohaLM v0.1 decoding-only grid evaluation; never trains or writes model weights."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from scripts.evaluation.run_qlora_sft_evaluation import _load_qlora_config
from src.data.checksums import checksum_value, file_checksum
from src.evaluation.decoding_evaluation import (
    DecodingPreset,
    compact_result,
    deployment_verdict,
    evaluate_decoding,
    rank_candidates,
    select_diverse_candidates,
    validate_decoding_config,
    validate_eos_contract,
)
from src.evaluation.qlora_sft import (
    QLoRAEvaluationError,
    environment_snapshot,
    load_model_for_evaluation,
    load_prompt_records,
    model_mode_report,
    model_parameter_checksums,
    release_model,
    verify_checksum_manifest,
    verify_training_artifacts,
    write_evaluation_artifact,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Read-only DohaLM v0.1 decoding grid evaluation")
    value.add_argument("--config", type=Path, required=True)
    value.add_argument("--qlora-config", type=Path, required=True)
    value.add_argument("--prompt-config", type=Path, required=True)
    value.add_argument("--repository", type=Path, required=True)
    value.add_argument("--training-run-root", type=Path, required=True)
    value.add_argument("--processed-root", type=Path, required=True)
    value.add_argument("--raw-dataset-root", type=Path, required=True)
    value.add_argument("--model-cache-root", type=Path, required=True)
    value.add_argument("--baseline-evaluation-root", type=Path, required=True)
    value.add_argument("--output-root", type=Path, required=True)
    value.add_argument("--evaluation-id", required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--execute", action="store_true")
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise QLoRAEvaluationError("DECODING_CONFIG_INVALID") from None
    if not isinstance(value, dict):
        raise QLoRAEvaluationError("DECODING_CONFIG_INVALID")
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
    required = (
        arguments.repository, arguments.training_run_root, arguments.processed_root,
        arguments.raw_dataset_root, arguments.model_cache_root, arguments.baseline_evaluation_root,
    )
    if any(not path.resolve().is_dir() for path in required):
        raise QLoRAEvaluationError("EVALUATION_PATH_INVALID")
    final_output = (arguments.output_root / arguments.evaluation_id).resolve()
    if any(_inside(final_output, path) or _inside(path, final_output) for path in (
        arguments.repository, arguments.training_run_root, arguments.processed_root,
        arguments.raw_dataset_root, arguments.baseline_evaluation_root,
    )):
        raise QLoRAEvaluationError("EVALUATION_OUTPUT_OVERLAP")
    if final_output.exists():
        raise QLoRAEvaluationError("EVALUATION_OUTPUT_CONFLICT")


def _baseline_identity(root: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    verify_checksum_manifest(root)
    result = _read_yaml(root / "evaluation-result.yaml")
    baseline = config["baseline"]
    prompts = config["prompts"]
    if (
        result.get("status") != "completed"
        or result.get("evaluation_id") != baseline.get("evaluation_id")
        or result.get("evaluation_fingerprint") != baseline.get("evaluation_fingerprint")
        or result.get("row_hash_list_fingerprint") != prompts.get("row_hash_list_fingerprint")
        or result.get("adapter_fingerprint") != config["model"].get("adapter_fingerprint")
        or result.get("base_revision") != config["model"].get("revision")
    ):
        raise QLoRAEvaluationError("BASELINE_EVALUATION_MISMATCH")
    return {
        "evaluation_id": result["evaluation_id"],
        "evaluation_fingerprint": result["evaluation_fingerprint"],
        "row_hash_list_fingerprint": result["row_hash_list_fingerprint"],
        "checksums_fingerprint": file_checksum(root / "checksums.sha256"),
        "verdict": result["verdict"],
    }


def _cache_key(model_name: str, preset: DecodingPreset) -> tuple[str, str]:
    return model_name, preset.preset_id


def _run_preset(
    *, model_name: str, model: Any, tokenizer: Any, prompts: list[Any],
    preset: DecodingPreset, train_output_hashes: set[str], seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    import torch

    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    result = evaluate_decoding(
        model, tokenizer, prompts, preset, train_output_hashes=train_output_hashes,
    )
    return compact_result(model_name, result), result


def _assert_model_unchanged(model: Any, before: Mapping[str, Any]) -> None:
    after_mode = model_mode_report(model)
    for key, value in after_mode.items():
        if before.get(key) != value:
            raise QLoRAEvaluationError("MODEL_MODE_CHANGED")
    after_identity = model_parameter_checksums(model)
    if any(before[key] != value for key, value in after_identity.items()):
        raise QLoRAEvaluationError("EVALUATION_MUTATED_MODEL")


def _phase_ab(
    *, config: Mapping[str, Any], qlora_config: Mapping[str, Any], cache_root: Path,
    training_root: Path, prompts: list[Any], train_output_hashes: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    phase_a: list[dict[str, Any]] = []
    phase_b: list[dict[str, Any]] = []
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    eos_validation: dict[str, Any] = {}
    grid = config["grid"]
    for model_name in config["model"]["candidates"]:
        adapter_root = training_root / model_name
        tokenizer, model, mode_before = load_model_for_evaluation(
            config=qlora_config, cache_dir=cache_root, adapter_root=adapter_root,
        )
        eos_validation[model_name] = validate_eos_contract(tokenizer, model)
        model_a: list[dict[str, Any]] = []
        for maximum in grid["max_new_tokens"]:
            preset = DecodingPreset(int(maximum), 1.05, 0)
            compact, raw = _run_preset(
                model_name=model_name, model=model, tokenizer=tokenizer, prompts=prompts,
                preset=preset, train_output_hashes=train_output_hashes, seed=int(grid["seed"]),
            )
            phase_a.append(compact)
            model_a.append(compact)
            cache[_cache_key(model_name, preset)] = raw
        selected_a = rank_candidates(model_a, 2)
        for candidate in selected_a:
            maximum = int(candidate["preset"]["max_new_tokens"])
            for penalty in grid["repetition_penalty"]:
                preset = DecodingPreset(maximum, float(penalty), 0)
                key = _cache_key(model_name, preset)
                if key in cache:
                    raw = cache[key]
                    compact = compact_result(model_name, raw)
                else:
                    compact, raw = _run_preset(
                        model_name=model_name, model=model, tokenizer=tokenizer, prompts=prompts,
                        preset=preset, train_output_hashes=train_output_hashes, seed=int(grid["seed"]),
                    )
                    cache[key] = raw
                phase_b.append(compact)
        _assert_model_unchanged(model, mode_before)
        release_model(model, tokenizer)
    return phase_a, phase_b, cache, eos_validation


def _phase_c(
    *, candidates: list[dict[str, Any]], config: Mapping[str, Any],
    qlora_config: Mapping[str, Any], cache_root: Path, training_root: Path,
    prompts: list[Any], train_output_hashes: set[str], cache: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    phase_c: list[dict[str, Any]] = []
    by_model = {name: [row for row in candidates if row["model"] == name] for name in config["model"]["candidates"]}
    for model_name, model_candidates in by_model.items():
        if not model_candidates:
            continue
        tokenizer, model, mode_before = load_model_for_evaluation(
            config=qlora_config, cache_dir=cache_root, adapter_root=training_root / model_name,
        )
        for candidate in model_candidates:
            for ngram in config["grid"]["no_repeat_ngram_size"]:
                preset = DecodingPreset(
                    int(candidate["preset"]["max_new_tokens"]),
                    float(candidate["preset"]["repetition_penalty"]), int(ngram),
                )
                key = _cache_key(model_name, preset)
                if key in cache:
                    raw = cache[key]
                    compact = compact_result(model_name, raw)
                else:
                    compact, raw = _run_preset(
                        model_name=model_name, model=model, tokenizer=tokenizer, prompts=prompts,
                        preset=preset, train_output_hashes=train_output_hashes,
                        seed=int(config["grid"]["seed"]),
                    )
                    cache[key] = raw
                phase_c.append(compact)
        _assert_model_unchanged(model, mode_before)
        release_model(model, tokenizer)
    return phase_c


def _phase_d(
    *, candidates: list[dict[str, Any]], qlora_config: Mapping[str, Any], cache_root: Path,
    training_root: Path, prompts: list[Any], train_output_hashes: set[str],
    seed: int,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]], dict[str, Any]]:
    final: list[dict[str, Any]] = []
    raw_repeats: dict[tuple[str, str], list[dict[str, Any]]] = {}
    validation: dict[str, Any] = {}
    by_model: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_model.setdefault(str(candidate["model"]), []).append(candidate)
    for model_name, model_candidates in by_model.items():
        tokenizer, model, mode_before = load_model_for_evaluation(
            config=qlora_config, cache_dir=cache_root, adapter_root=training_root / model_name,
        )
        validation[model_name] = {"mode": mode_before, "eos": validate_eos_contract(tokenizer, model)}
        for candidate in model_candidates:
            preset = DecodingPreset(**candidate["preset"])
            repeats: list[dict[str, Any]] = []
            compacts: list[dict[str, Any]] = []
            for _ in range(2):
                compact, raw = _run_preset(
                    model_name=model_name, model=model, tokenizer=tokenizer, prompts=prompts,
                    preset=preset, train_output_hashes=train_output_hashes, seed=seed,
                )
                repeats.append(raw)
                compacts.append(compact)
            for key in ("metric_fingerprint", "termination_reason_fingerprint", "generated_token_fingerprint"):
                if compacts[0][key] != compacts[1][key]:
                    raise QLoRAEvaluationError("DECODING_NONDETERMINISTIC")
            row = dict(compacts[0])
            row["repeat_fingerprints"] = {
                key: [item[key] for item in compacts]
                for key in ("metric_fingerprint", "termination_reason_fingerprint", "generated_token_fingerprint")
            }
            row["deterministic"] = True
            final.append(row)
            raw_repeats[_cache_key(model_name, preset)] = repeats
        _assert_model_unchanged(model, mode_before)
        release_model(model, tokenizer)
    return final, raw_repeats, validation


def _failure_analysis(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {"status": "no_selectable_candidate", "raw_text_stored": False}
    rows = raw["rows"]
    groups = {
        "repetition_any": [], "sentence_repetition": [], "ngram_repetition": [],
        "long_loop": [], "automatic_incomplete": [], "max_length_truncation": [],
        "missing_terminal_punctuation": [],
    }
    for row in rows:
        for name in groups:
            if bool(row[name]):
                groups[name].append(row["sample_hash"])
    return {
        "groups": {name: {"count": len(values), "sample_hashes": sorted(values)} for name, values in groups.items()},
        "semantic_incomplete": "not_assessed_without_approved_judge",
        "factual_error": "not_assessed_without_approved_judge",
        "reference_mismatch_is_not_classified_as_incomplete": True,
        "raw_text_stored": False,
    }


def _preset_document(selected: Mapping[str, Any] | None, verdict: Mapping[str, Any]) -> dict[str, Any]:
    if selected is None:
        return {
            "schema_version": 1, "status": "not_selected", "model_candidate": None,
            "generation": None, "deployment_ready": False, "reason": "NO_CANDIDATE_PASSED_HARD_BLOCKERS",
        }
    preset = selected["preset"]
    return {
        "schema_version": 1,
        "status": "selected" if verdict["deployment_ready"] else "evaluation_candidate_only",
        "model_candidate": selected["model"],
        "generation": {
            "do_sample": False, "num_beams": 1,
            "max_new_tokens": preset["max_new_tokens"],
            "repetition_penalty": preset["repetition_penalty"],
            "no_repeat_ngram_size": preset["no_repeat_ngram_size"],
            "temperature": None, "top_p": None, "top_k": None,
            "eos_token_id": 151645, "pad_token_id": 151643, "use_cache": True,
        },
        "deployment_ready": verdict["deployment_ready"],
        "verdict": verdict["verdict"],
    }


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    if not arguments.execute:
        raise QLoRAEvaluationError("EXPLICIT_EXECUTE_REQUIRED")
    config = validate_decoding_config(_read_yaml(arguments.config))
    if arguments.evaluation_id != config["evaluation_id"]:
        raise QLoRAEvaluationError("EVALUATION_ID_MISMATCH")
    _validate_paths(arguments)
    git = _git_identity(arguments.repository, arguments.expected_head)
    qlora_config = _load_qlora_config(arguments.qlora_config)
    training = verify_training_artifacts(arguments.training_run_root, config)
    verify_checksum_manifest(arguments.processed_root)
    baseline = _baseline_identity(arguments.baseline_evaluation_root, config)
    prompts, prompt_identity, train_output_hashes, _ = load_prompt_records(
        processed_root=arguments.processed_root, raw_root=arguments.raw_dataset_root,
        prompt_path=arguments.prompt_config,
        expected_validation_rows=int(config["dataset"]["validation_rows"]),
    )
    if prompt_identity["row_hash_list_fingerprint"] != config["prompts"]["row_hash_list_fingerprint"]:
        raise QLoRAEvaluationError("PROMPT_FINGERPRINT_MISMATCH")
    phase_a, phase_b, cache, eos_validation = _phase_ab(
        config=config, qlora_config=qlora_config, cache_root=arguments.model_cache_root,
        training_root=arguments.training_run_root, prompts=prompts,
        train_output_hashes=train_output_hashes,
    )
    phase_b_top = select_diverse_candidates(phase_b, 3)
    phase_c = _phase_c(
        candidates=phase_b_top, config=config, qlora_config=qlora_config,
        cache_root=arguments.model_cache_root, training_root=arguments.training_run_root,
        prompts=prompts, train_output_hashes=train_output_hashes, cache=cache,
    )
    phase_c_top = select_diverse_candidates(phase_c, 3)
    final, raw_repeats, model_validation = _phase_d(
        candidates=phase_c_top, qlora_config=qlora_config,
        cache_root=arguments.model_cache_root, training_root=arguments.training_run_root,
        prompts=prompts, train_output_hashes=train_output_hashes,
        seed=int(config["grid"]["seed"]),
    )
    selectable = [row for row in final if not row["score"]["hard_blocked"]]
    selectable.sort(key=lambda row: -float(row["score"]["quality_score"]))
    selected = selectable[0] if selectable else None
    verdict = (
        deployment_verdict(selected["summary"], deterministic=True)
        if selected is not None
        else {
            "verdict": "NEEDS_MODEL_IMPROVEMENT", "deployment_ready": False,
            "quality_above_base": False, "deterministic": bool(final),
            "reason": "NO_CANDIDATE_PASSED_HARD_BLOCKERS",
            "v0_2_data_or_training_improvement_recommended": True,
        }
    )
    selected_raw = None
    if selected is not None:
        key = (selected["model"], selected["preset_id"])
        selected_raw = raw_repeats[key][0]
    failure = _failure_analysis(selected_raw)
    preset = _preset_document(selected, verdict)
    final_comparison = {
        "ranked_candidates": sorted(final, key=lambda row: -float(row["score"]["quality_score"])),
        "selected_candidate": selected,
        "verdict": verdict,
        "baseline": config["baseline"],
    }
    environment = environment_snapshot()
    result_fingerprint = checksum_value({
        "git": git, "config": file_checksum(arguments.config), "baseline": baseline,
        "prompt_identity": prompt_identity, "phase_a": phase_a, "phase_b": phase_b,
        "phase_c": phase_c, "final": final_comparison, "eos": eos_validation,
    })
    files = {
        "decoding-config.yaml": {**config, "resolved_git": git, "prompt_identity": prompt_identity},
        "grid-summary.json": {
            "status": "completed", "evaluation_id": arguments.evaluation_id,
            "evaluation_fingerprint": result_fingerprint, "git": git,
            "baseline_identity": baseline, "training_identity": training,
            "eos_validation": eos_validation, "model_validation": model_validation,
            "phase_counts": {"phase_a": len(phase_a), "phase_b": len(phase_b), "phase_c": len(phase_c), "final": len(final)},
            "verdict": verdict, "training_started": False, "optimizer_steps": 0,
            "checkpoint_modified": False, "adapter_modified": False,
            "raw_text_stored": False, "token_ids_stored": False,
        },
        "phase-a-results.json": phase_a,
        "phase-b-results.json": phase_b,
        "phase-c-results.json": phase_c,
        "final-comparison.json": final_comparison,
        "inference-preset.yaml": preset,
        "failure-analysis.json": failure,
        "environment.json": environment,
    }
    final_path = write_evaluation_artifact(
        output_root=arguments.output_root, evaluation_id=arguments.evaluation_id, files=files,
    )
    return {
        "status": "completed", "evaluation_id": arguments.evaluation_id,
        "artifact_path": str(final_path), "evaluation_fingerprint": result_fingerprint,
        "checksums_manifest": file_checksum(final_path / "checksums.sha256"),
        "selected_candidate": selected, "verdict": verdict,
        "training_started": False, "optimizer_steps": 0,
    }


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
