"""Fail-closed, text-free EOS generation and decoding diagnostics."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Sequence

import torch
import yaml

from src.data.checksums import checksum_value, file_checksum
from src.runtime.environment import collect_environment
from src.runtime.paths import repository_root
from src.tokenizer.tokenizer import DohaTokenizer, SPECIAL_TOKEN_IDS

from .artifacts import ArtifactRegistry
from .config import EvaluationConfig, EvaluationError
from .metrics import generation_statistics, quantiles
from .reporting import load_completed_result
from .runner import _model_digest, _prepare_model, _publish


EOS_ID = SPECIAL_TOKEN_IDS["<eos>"]
REQUIRED_LENGTHS = (16, 32, 64, 128)
REQUIRED_CATEGORIES = (
    "incomplete_general", "pre_completion", "period_complete", "paragraph_newline",
    "short_explanation", "long_explanation", "question", "dialogue", "list",
    "code_block_end", "sql_statement_end", "explicit_response_end", "minimal",
    "long_context", "repetition_probe",
)
REQUIRED_PROFILES = (
    "greedy", "temperature-0.7", "temperature-1.0", "top-k-20", "top-k-50",
    "top-p-0.9", "top-p-0.95", "repetition-1.05", "repetition-1.10",
    "no-repeat-bigram", "no-repeat-trigram",
)


def _logical_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvaluationError("EOS_DIAGNOSTIC_CONFIG_INVALID", f"{field} must be a logical path")
    if PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute() or ".." in PureWindowsPath(value).parts:
        raise EvaluationError("ABSOLUTE_PATH_BLOCKED", f"{field} must not be absolute or escape its root")
    return value.replace("\\", "/")


@dataclass(frozen=True)
class GenerationDiagnosticConfig:
    path: Path
    evaluation_config: str
    prompt_set: str
    output_root: str
    seed: int
    maximum_prompt_tokens: int
    generation_lengths: tuple[int, ...]
    artifacts: tuple[dict[str, str], ...]
    profiles: tuple[dict[str, Any], ...]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "GenerationDiagnosticConfig":
        source = Path(path).resolve()
        try:
            value = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise EvaluationError("EOS_DIAGNOSTIC_CONFIG_INVALID", "diagnostic config could not be read") from exc
        if not isinstance(value, dict) or value.get("status") != "proposed":
            raise EvaluationError("EOS_DIAGNOSTIC_CONFIG_INVALID", "diagnostic policy must remain proposed")
        if value.get("raw_text_storage") is not False or value.get("token_id_storage") is not False:
            raise EvaluationError("EVALUATION_PRIVACY_POLICY", "raw text and token ID storage must remain disabled")
        if value.get("overwrite") is not False:
            raise EvaluationError("EVALUATION_OVERWRITE_BLOCKED", "diagnostic outputs are immutable")
        lengths = tuple(value.get("generation_lengths", ()))
        artifacts = tuple(value.get("artifacts", ()))
        profiles = tuple(value.get("profiles", ()))
        if lengths != REQUIRED_LENGTHS:
            raise EvaluationError("EOS_DIAGNOSTIC_CONFIG_INVALID", "generation lengths must be 16, 32, 64, and 128")
        if tuple(row.get("name") for row in profiles if isinstance(row, dict)) != REQUIRED_PROFILES:
            raise EvaluationError("EOS_DIAGNOSTIC_CONFIG_INVALID", "decoding profile contract mismatch")
        if tuple(row.get("artifact_id") for row in artifacts if isinstance(row, dict)) != ("candidate-a-final", "candidate-b-final"):
            raise EvaluationError("EOS_DIAGNOSTIC_CONFIG_INVALID", "Candidate A/B artifact order mismatch")
        for profile in profiles:
            if profile.get("strategy") not in {"greedy", "sample"}:
                raise EvaluationError("EOS_DIAGNOSTIC_CONFIG_INVALID", "unsupported decoding strategy")
            if float(profile.get("repetition_penalty", 1.0)) < 1.0 or int(profile.get("no_repeat_ngram", 0)) not in {0, 2, 3}:
                raise EvaluationError("EOS_DIAGNOSTIC_CONFIG_INVALID", "invalid repetition control")
        maximum_prompt_tokens = int(value.get("maximum_prompt_tokens", 0))
        if maximum_prompt_tokens != 128:
            raise EvaluationError("EOS_DIAGNOSTIC_CONFIG_INVALID", "maximum prompt tokens must be 128")
        return cls(
            path=source,
            evaluation_config=_logical_path(value.get("evaluation_config"), "evaluation_config"),
            prompt_set=_logical_path(value.get("prompt_set"), "prompt_set"),
            output_root=_logical_path(value.get("output_root"), "output_root"),
            seed=int(value.get("seed")), maximum_prompt_tokens=maximum_prompt_tokens,
            generation_lengths=lengths, artifacts=artifacts, profiles=profiles,
        )

    @property
    def fingerprint(self) -> str:
        return file_checksum(self.path)


def load_generation_prompts(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        root = yaml.safe_load(path.read_text(encoding="utf-8"))
        prompts = root["prompts"]
    except (OSError, UnicodeDecodeError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise EvaluationError("PROMPT_SET_INVALID", "synthetic prompt set could not be read") from exc
    if root.get("source") != "synthetic" or root.get("pii_free") is not True or not isinstance(prompts, list):
        raise EvaluationError("PROMPT_SET_INVALID", "prompt set must be synthetic and PII-free")
    expected_fields = {"prompt_id", "category", "completion_shape", "context_class", "discourse_type", "domain_like", "text"}
    ids: set[str] = set()
    categories: list[str] = []
    for prompt in prompts:
        if not isinstance(prompt, dict) or set(prompt) != expected_fields or not isinstance(prompt["text"], str) or not prompt["text"]:
            raise EvaluationError("PROMPT_SET_INVALID", "prompt schema mismatch")
        if prompt["prompt_id"] in ids:
            raise EvaluationError("PROMPT_SET_INVALID", "duplicate prompt ID")
        ids.add(prompt["prompt_id"])
        categories.append(prompt["category"])
    if tuple(categories) != REQUIRED_CATEGORIES or len(prompts) != len(REQUIRED_CATEGORIES):
        raise EvaluationError("PROMPT_CATEGORY_MISMATCH", "required prompt categories must occur exactly once in order")
    return prompts, file_checksum(path)


def _seed(base: int, profile: str, prompt_id: str) -> int:
    payload = f"{base}:{profile}:{prompt_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**63 - 1)


def _apply_repetition_controls(logits: torch.Tensor, generated: Sequence[int], profile: dict[str, Any]) -> torch.Tensor:
    adjusted = logits.clone()
    penalty = float(profile.get("repetition_penalty", 1.0))
    if penalty != 1.0:
        for token_id in set(generated):
            adjusted[token_id] = adjusted[token_id] / penalty if adjusted[token_id] > 0 else adjusted[token_id] * penalty
    n = int(profile.get("no_repeat_ngram", 0))
    if n and len(generated) >= n - 1:
        prefix = tuple(generated[-(n - 1):]) if n > 1 else ()
        blocked = {generated[index + n - 1] for index in range(len(generated) - n + 1) if tuple(generated[index:index + n - 1]) == prefix}
        if blocked:
            adjusted[list(blocked)] = float("-inf")
    return adjusted


def _select_token(logits: torch.Tensor, profile: dict[str, Any], generator: torch.Generator) -> int:
    if profile["strategy"] == "greedy":
        return int(logits.argmax().item())
    adjusted = logits / float(profile["temperature"])
    top_k = profile.get("top_k")
    if top_k:
        threshold = torch.topk(adjusted, int(top_k)).values[-1]
        adjusted = adjusted.masked_fill(adjusted < threshold, float("-inf"))
    probabilities = torch.softmax(adjusted, dim=-1)
    top_p = profile.get("top_p")
    if top_p:
        sorted_probs, sorted_indices = torch.sort(probabilities, descending=True)
        remove = torch.cumsum(sorted_probs, dim=-1) - sorted_probs > float(top_p)
        sorted_probs = sorted_probs.masked_fill(remove, 0.0)
        sorted_probs /= sorted_probs.sum()
        index = torch.multinomial(sorted_probs, 1, generator=generator)
        return int(sorted_indices[index].item())
    return int(torch.multinomial(probabilities, 1, generator=generator).item())


def _loop_start(tokens: Sequence[int]) -> int | None:
    for end in range(8, len(tokens) + 1):
        window = tuple(tokens[end - 4:end])
        if any(tuple(tokens[index:index + 4]) == window for index in range(end - 7)):
            return end
    return None


def _trajectory(
    model: Any,
    tokenizer: DohaTokenizer,
    prompt: dict[str, Any],
    profile: dict[str, Any],
    device: torch.device,
    *,
    seed: int,
    maximum_prompt_tokens: int,
    maximum_new_tokens: int,
) -> dict[str, Any]:
    encoded = tokenizer.encode(prompt["text"])
    if len(encoded.ids) > maximum_prompt_tokens:
        raise EvaluationError("PROMPT_LENGTH_EXCEEDED", f"prompt exceeds limit: {prompt['prompt_id']}")
    sequence = torch.tensor([encoded.ids], dtype=torch.long, device=device)
    generator = torch.Generator(device=device).manual_seed(_seed(seed, profile["name"], prompt["prompt_id"]))
    generated: list[int] = []
    steps: list[dict[str, Any]] = []
    for step in range(1, maximum_new_tokens + 1):
        with torch.inference_mode():
            logits = model(sequence, attention_mask=torch.ones_like(sequence, dtype=torch.bool)).logits[0, -1].float()
        logits = _apply_repetition_controls(logits, generated, profile)
        eos_logit = logits[EOS_ID]
        logsum = torch.logsumexp(logits, dim=0)
        eos_probability = torch.exp(eos_logit - logsum)
        top_index = int(logits.argmax().item())
        top_probability = torch.exp(logits[top_index] - logsum)
        token = _select_token(logits, profile, generator)
        generated.append(token)
        loop = _loop_start(generated)
        steps.append({
            "step": step, "position": len(encoded.ids) + step - 1,
            "eos_logit": float(eos_logit.item()), "eos_probability": float(eos_probability.item()),
            "eos_rank": int((logits > eos_logit).sum().item()) + 1,
            "top1_logit": float(logits[top_index].item()), "top1_probability": float(top_probability.item()),
            "top1_minus_eos_logit_margin": float((logits[top_index] - eos_logit).item()),
            "top1_minus_eos_probability_margin": float((top_probability - eos_probability).item()),
            "eos_top5": int((logits > eos_logit).sum().item()) < 5,
            "eos_top10": int((logits > eos_logit).sum().item()) < 10,
            "loop_started": loop is not None, "selected_eos": token == EOS_ID,
            "termination_reason": "eos" if token == EOS_ID else (
                "maximum_length" if step == maximum_new_tokens else "continuing"
            ),
        })
        sequence = torch.cat((sequence, torch.tensor([[token]], dtype=torch.long, device=device)), dim=1)
        if token == EOS_ID:
            break
    return {"tokens": generated, "steps": steps, "input_token_length": len(encoded.ids)}


def _repeated_ngram_rate(tokens: Sequence[int], n: int) -> float:
    grams = [tuple(tokens[index:index + n]) for index in range(max(0, len(tokens) - n + 1))]
    repeated = sum(count - 1 for count in Counter(grams).values() if count > 1)
    return repeated / len(grams) if grams else 0.0


def _one_sample(
    trajectory: dict[str, Any], prompt: dict[str, Any], length: int, *, unk_id: int,
    special_ids: set[int], byte_ids: set[int],
) -> dict[str, Any]:
    tokens = list(trajectory["tokens"][:length])
    if EOS_ID in tokens:
        tokens = tokens[:tokens.index(EOS_ID) + 1]
    steps = trajectory["steps"][:len(tokens)]
    stats = generation_statistics(tokens, eos_id=EOS_ID, unk_id=unk_id, special_ids=special_ids, byte_ids=byte_ids)
    eos_step = next((index + 1 for index, token in enumerate(tokens) if token == EOS_ID), None)
    loop_step = _loop_start(tokens)
    return {
        "prompt_id": prompt["prompt_id"], "category": prompt["category"],
        "completion_shape": prompt["completion_shape"], "context_class": prompt["context_class"],
        "discourse_type": prompt["discourse_type"], "domain_like": prompt["domain_like"],
        "input_token_length": trajectory["input_token_length"], "generated_token_length": len(tokens),
        "eos_reached": eos_step is not None, "eos_step": eos_step,
        "maximum_length_reached": eos_step is None and len(tokens) == length,
        "empty_generation": len(tokens) == 0, "loop_start_step": loop_step,
        "loop_before_eos": loop_step is not None and (eos_step is None or loop_step < eos_step),
        "best_eos_rank": min(row["eos_rank"] for row in steps),
        "mean_eos_rank": sum(row["eos_rank"] for row in steps) / len(steps),
        "final_eos_rank": steps[-1]["eos_rank"],
        "maximum_eos_probability": max(row["eos_probability"] for row in steps),
        "mean_eos_probability": sum(row["eos_probability"] for row in steps) / len(steps),
        "final_eos_probability": steps[-1]["eos_probability"],
        "mean_logit_margin": sum(row["top1_minus_eos_logit_margin"] for row in steps) / len(steps),
        "mean_probability_margin": sum(row["top1_minus_eos_probability_margin"] for row in steps) / len(steps),
        "eos_top5_step_rate": sum(row["eos_top5"] for row in steps) / len(steps),
        "eos_top10_step_rate": sum(row["eos_top10"] for row in steps) / len(steps),
        "adjacent_repetition": stats["adjacent_repetition_rate"],
        "repeated_bigram": _repeated_ngram_rate(tokens, 2), "repeated_trigram": _repeated_ngram_rate(tokens, 3),
        "distinct_1": stats["distinct_1"], "distinct_2": stats["distinct_2"], "distinct_3": stats["distinct_3"],
        "degenerate_loop": stats["degenerate_loop"], "unique_token_ratio": stats["unique_token_ratio"],
        "special_token_exposure": max(0.0, float(stats["special_token_rate"]) - (1.0 / len(tokens) if eos_step else 0.0)),
        "unk_generation": stats["unk_rate"], "byte_fallback_ratio": stats["byte_fallback_rate"],
        "termination_reason": "eos" if eos_step else "maximum_length",
        "generated_text_stored": False, "token_ids_stored": False,
    }


def _aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        raise EvaluationError("EOS_DIAGNOSTIC_EMPTY", "aggregate requires samples")
    mean = lambda key: sum(float(row[key]) for row in samples) / len(samples)
    eos_steps = [float(row["eos_step"]) for row in samples if row["eos_step"] is not None]
    lengths = [float(row["generated_token_length"]) for row in samples]
    return {
        "samples": len(samples), "eos_rate": mean("eos_reached"),
        "eos_step": quantiles(eos_steps), "maximum_length_rate": mean("maximum_length_reached"),
        "generation_length": quantiles(lengths), "empty_generation_rate": mean("empty_generation"),
        "best_eos_rank": quantiles([float(row["best_eos_rank"]) for row in samples]),
        "mean_eos_rank": mean("mean_eos_rank"), "mean_eos_probability": mean("mean_eos_probability"),
        "maximum_eos_probability": max(float(row["maximum_eos_probability"]) for row in samples),
        "mean_logit_margin": mean("mean_logit_margin"), "mean_probability_margin": mean("mean_probability_margin"),
        "eos_top5_step_rate": mean("eos_top5_step_rate"), "eos_top10_step_rate": mean("eos_top10_step_rate"),
        "special_token_exposure": mean("special_token_exposure"), "unk_generation": mean("unk_generation"),
        "byte_fallback_ratio": mean("byte_fallback_ratio"), "adjacent_repetition": mean("adjacent_repetition"),
        "repeated_bigram": mean("repeated_bigram"), "repeated_trigram": mean("repeated_trigram"),
        "distinct_1": mean("distinct_1"), "distinct_2": mean("distinct_2"), "distinct_3": mean("distinct_3"),
        "degenerate_loop_rate": mean("degenerate_loop"), "unique_token_ratio": mean("unique_token_ratio"),
        "loop_before_eos_rate": mean("loop_before_eos"), "actual_text_values_stored": False, "token_ids_stored": False,
    }


def run_model_generation_diagnostic(
    model: Any, tokenizer: DohaTokenizer, prompts: list[dict[str, Any]], profiles: Sequence[dict[str, Any]],
    lengths: Sequence[int], device: torch.device, *, seed: int, maximum_prompt_tokens: int,
) -> dict[str, Any]:
    byte_ids = {index for index in range(tokenizer.vocab_size) if tokenizer.processor.id_to_piece(index).startswith("<0x")}
    rows: list[dict[str, Any]] = []
    step_rows: list[dict[str, Any]] = []
    for profile in profiles:
        for prompt in prompts:
            trajectory = _trajectory(
                model, tokenizer, prompt, profile, device, seed=seed,
                maximum_prompt_tokens=maximum_prompt_tokens, maximum_new_tokens=max(lengths),
            )
            for step in trajectory["steps"]:
                step_rows.append({"profile": profile["name"], "prompt_id": prompt["prompt_id"], "category": prompt["category"], **step})
            for length in lengths:
                rows.append({
                    "profile": profile["name"], "maximum_new_tokens": length,
                    **_one_sample(trajectory, prompt, length, unk_id=tokenizer.unk_id,
                                  special_ids=set(SPECIAL_TOKEN_IDS.values()), byte_ids=byte_ids),
                })
    profiles_by_length: dict[str, Any] = {}
    categories_by_length: dict[str, Any] = {}
    for length in lengths:
        profiles_by_length[str(length)] = {
            profile["name"]: _aggregate([row for row in rows if row["maximum_new_tokens"] == length and row["profile"] == profile["name"]])
            for profile in profiles
        }
        categories_by_length[str(length)] = {
            category: _aggregate([row for row in rows if row["maximum_new_tokens"] == length and row["category"] == category])
            for category in REQUIRED_CATEGORIES
        }
    return {
        "profiles_by_length": profiles_by_length, "categories_by_length": categories_by_length,
        "prompt_results": rows, "step_results": step_rows,
        "generation_contract": {
            "maximum_new_tokens": list(lengths), "eos_token_id": EOS_ID, "eos_suppression": False,
            "forced_eos": False, "logit_bias": False, "heuristic_stop": False,
            "stop_condition": "EOS or configured maximum_new_tokens", "sampling_seed": seed,
        },
        "actual_text_values_stored": False, "token_ids_stored": False,
    }


def _full_identity(full: dict[str, Any], artifact: Any) -> dict[str, Any]:
    manifest = full["manifest"]
    return {
        "dataset_fingerprint": artifact.value["dataset_fingerprint"],
        "source_lineage_fingerprint": artifact.value["source_lineage_fingerprint"],
        "pii_fingerprint": artifact.value["pii_fingerprint"],
        "split_fingerprint": artifact.value["split_fingerprint"],
        "tokenizer_fingerprint": manifest.get("tokenizer_fingerprint"),
        "model_fingerprint": manifest.get("model_fingerprint"),
        "profile": manifest.get("profile"),
    }


def run_generation_diagnostic(
    diagnostic: GenerationDiagnosticConfig, evaluation: EvaluationConfig, registry: ArtifactRegistry,
    *, diagnostic_id: str,
) -> dict[str, Any]:
    if not diagnostic_id or "/" in diagnostic_id or "\\" in diagnostic_id:
        raise EvaluationError("EOS_DIAGNOSTIC_ID_INVALID", "diagnostic ID must be one path segment")
    output = evaluation.external_path(f"{diagnostic.output_root}/{diagnostic_id}")
    if output.exists():
        raise EvaluationError("EVALUATION_OUTPUT_EXISTS", "diagnostic output already exists")
    prompts, prompt_fingerprint = load_generation_prompts(evaluation.repository_path(diagnostic.prompt_set))
    tokenizer_path = evaluation.external_path(evaluation.tokenizer_model)
    tokenizer = DohaTokenizer(tokenizer_path)
    full_results: dict[str, dict[str, Any]] = {}
    identities: dict[str, dict[str, Any]] = {}
    for item in diagnostic.artifacts:
        artifact_id = item["artifact_id"]
        artifact = registry.get(artifact_id)
        inspection = registry.inspect(evaluation, artifact_id, require_eligible=True)
        if inspection["status"] != "eligible":
            raise EvaluationError("ARTIFACT_EVALUATION_BLOCKED", f"artifact is not eligible: {artifact_id}")
        full = load_completed_result(evaluation, item["full_reference"])
        if full["manifest"].get("profile") != "full" or full["manifest"].get("artifact_id") != artifact_id:
            raise EvaluationError("BASELINE_REFERENCE_INVALID", "diagnostic requires matching Full results")
        full_results[artifact_id] = full
        identities[artifact_id] = _full_identity(full, artifact)
    if identities["candidate-a-final"] != identities["candidate-b-final"]:
        raise EvaluationError("EOS_DIAGNOSTIC_IDENTITY_MISMATCH", "Candidate A/B Full evaluation identities differ")
    results: dict[str, Any] = {}
    artifact_integrity: dict[str, Any] = {}
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type != "cuda":
        raise EvaluationError("CUDA_REQUIRED", "approved EOS diagnostic requires CUDA")
    started = time.perf_counter()
    for item in diagnostic.artifacts:
        artifact_id = item["artifact_id"]
        artifact = registry.get(artifact_id)
        model, checkpoint_before = _prepare_model(evaluation, artifact, device)
        model_before = _model_digest(model)
        results[artifact_id] = run_model_generation_diagnostic(
            model, tokenizer, prompts, diagnostic.profiles, diagnostic.generation_lengths, device,
            seed=diagnostic.seed, maximum_prompt_tokens=diagnostic.maximum_prompt_tokens,
        )
        model_after = _model_digest(model)
        checkpoint_after = file_checksum(evaluation.external_path(artifact.value["logical_external_path"]) / "checksums.json")
        if model_before != model_after or checkpoint_before != checkpoint_after:
            raise EvaluationError("EVALUATION_MUTATED_ARTIFACT", "diagnostic changed model or checkpoint")
        artifact_integrity[artifact_id] = {
            "model_state_before": model_before, "model_state_after": model_after,
            "checkpoint_before": checkpoint_before, "checkpoint_after": checkpoint_after,
            "unchanged": True,
        }
        del model
        torch.cuda.empty_cache()
    comparison = {
        length: {
            profile: {
                metric: results["candidate-b-final"]["profiles_by_length"][length][profile][metric]
                - results["candidate-a-final"]["profiles_by_length"][length][profile][metric]
                for metric in ("eos_rate", "maximum_length_rate", "mean_eos_rank", "mean_eos_probability", "degenerate_loop_rate")
            }
            for profile in REQUIRED_PROFILES
        }
        for length in map(str, diagnostic.generation_lengths)
    }
    deterministic = {
        "prompt_set_fingerprint": prompt_fingerprint,
        "full_result_fingerprints": {key: value["manifest"]["result_fingerprint"] for key, value in full_results.items()},
        "identities": identities, "results": results, "comparison": comparison, "artifact_integrity": artifact_integrity,
    }
    result_fingerprint = checksum_value(deterministic)
    manifest = {
        "schema_version": "1.0", "diagnostic_id": diagnostic_id, "status": "completed",
        "policy_status": "proposed", "candidate_b_official_status": "evaluated_contract_not_passed",
        "diagnostic_config_fingerprint": diagnostic.fingerprint, "prompt_set_fingerprint": prompt_fingerprint,
        "full_result_fingerprints": deterministic["full_result_fingerprints"], "evaluation_identity": identities["candidate-a-final"],
        "artifact_integrity": artifact_integrity, "eos_token_id": EOS_ID,
        "training_operations": {"optimizer_created": False, "scheduler_created": False, "backward_called": False, "gradients_enabled": False},
        "raw_text_stored": False, "token_ids_stored": False, "result_fingerprint": result_fingerprint,
        "output_logical_path": f"{diagnostic.output_root}/{diagnostic_id}",
        "environment": collect_environment(repository_root()), "wall_clock_seconds": time.perf_counter() - started,
    }
    _publish(output, {
        "manifests/diagnostic.json": manifest,
        "metrics/candidate-a-profiles.json": {"profiles_by_length": results["candidate-a-final"]["profiles_by_length"]},
        "metrics/candidate-b-profiles.json": {"profiles_by_length": results["candidate-b-final"]["profiles_by_length"]},
        "metrics/candidate-a-categories.json": {"categories_by_length": results["candidate-a-final"]["categories_by_length"]},
        "metrics/candidate-b-categories.json": {"categories_by_length": results["candidate-b-final"]["categories_by_length"]},
        "metrics/candidate-a-prompts.json": {"rows": results["candidate-a-final"]["prompt_results"], "raw_text_stored": False, "token_ids_stored": False},
        "metrics/candidate-b-prompts.json": {"rows": results["candidate-b-final"]["prompt_results"], "raw_text_stored": False, "token_ids_stored": False},
        "metrics/candidate-a-steps.json": {"rows": results["candidate-a-final"]["step_results"], "raw_text_stored": False, "token_ids_stored": False},
        "metrics/candidate-b-steps.json": {"rows": results["candidate-b-final"]["step_results"], "raw_text_stored": False, "token_ids_stored": False},
        "metrics/candidate-a-b-comparison.json": comparison,
        "reports/summary.json": {"status": "completed", "result_fingerprint": result_fingerprint, "candidate_b_official_status": "evaluated_contract_not_passed"},
        "logs/execution.json": {"automatic_retry_count": 0, "completed": True},
        "failures/status.json": {"failure_count": 0, "failures": []},
    })
    return {"diagnostic_id": diagnostic_id, "status": "completed", "result_fingerprint": result_fingerprint, "output": manifest["output_logical_path"]}
