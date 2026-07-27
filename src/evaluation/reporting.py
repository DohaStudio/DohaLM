"""Fingerprint-aware comparison and leaderboard rows."""

from __future__ import annotations

from typing import Any

import json

from .config import EvaluationConfig, EvaluationError


def comparison_status(left: dict[str, Any], right: dict[str, Any]) -> str:
    left_manifest, right_manifest = left["manifest"], right["manifest"]
    if left_manifest["dataset_identity"] != right_manifest["dataset_identity"]:
        return "incomparable_dataset"
    if left_manifest["config_fingerprint"] != right_manifest["config_fingerprint"]:
        return "incomparable_config"
    if left_manifest.get("status") != "completed" or right_manifest.get("status") != "completed":
        return "incomplete"
    return "comparable"


def leaderboard_row(manifest: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    next_token = metrics["next_token"]
    position = metrics["position"]
    generation = metrics["generation"]
    checkpoint = manifest.get("checkpoint_identity") or {}
    return {
        "artifact": manifest["artifact_id"], "training_stage": checkpoint.get("global_step", 0),
        "evaluation_dataset_fingerprint": manifest["dataset_identity"]["evaluation_fingerprint"],
        "eval_loss": metrics["perplexity"]["loss"], "perplexity": metrics["perplexity"]["perplexity"],
        "top1": next_token["top1_accuracy"], "top5": next_token["top5_accuracy"],
        "packed_top1": position["packed_top1"], "rebased_top1": position["rebased"].get("top1_accuracy"),
        "repetition": generation.get("repetition_rate"), "eos_rate": generation.get("eos_rate"),
        "evaluation_status": manifest["status"], "result_fingerprint": manifest["result_fingerprint"],
    }


def load_completed_result(config: EvaluationConfig, reference: str) -> dict[str, Any]:
    """Load one ``artifact-id:evaluation-id`` result without exposing its local path."""
    parts = reference.split(":", 1)
    if len(parts) != 2 or not all(parts):
        raise EvaluationError("EVALUATION_REFERENCE_INVALID", "result reference must be artifact-id:evaluation-id")
    artifact_id, evaluation_id = parts
    base = config.external_path(f"{config.output_root}/{artifact_id}/{evaluation_id}")
    try:
        manifest = json.loads((base / "manifests/execution.json").read_text(encoding="utf-8"))
        metrics = json.loads((base / "metrics/aggregate.json").read_text(encoding="utf-8"))
        resource = json.loads((base / "metrics/resources.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationError("EVALUATION_RESULT_INCOMPLETE", "completed evaluation result could not be read") from exc
    if manifest.get("status") != "completed" or manifest.get("artifact_id") != artifact_id:
        raise EvaluationError("EVALUATION_RESULT_INCOMPLETE", "evaluation manifest identity/status mismatch")
    return {"manifest": manifest, "metrics": metrics, "resource": resource}


def compare_completed_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if len(results) < 2:
        raise EvaluationError("EVALUATION_COMPARISON_INCOMPLETE", "comparison needs at least two completed results")
    baseline = results[0]
    statuses = [comparison_status(baseline, result) for result in results[1:]]
    return {
        "status": "comparable" if all(item == "comparable" for item in statuses) else "incomparable",
        "pair_statuses": statuses, "rows": [leaderboard_row(item["manifest"], item["metrics"]) for item in results],
        "composite_score_used": False,
    }


def compare_full_candidate_results(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Compare two completed Full results without using either Quick result as a baseline."""
    manifests = (baseline["manifest"], candidate["manifest"])
    if any(item.get("status") != "completed" or item.get("profile") != "full" for item in manifests):
        raise EvaluationError("BASELINE_REFERENCE_INVALID", "Candidate comparison requires two completed Full results")
    if manifests[0].get("artifact_id") == manifests[1].get("artifact_id"):
        raise EvaluationError("BASELINE_REFERENCE_INVALID", "Baseline and candidate artifacts must differ")
    if (
        manifests[0].get("dataset_identity") != manifests[1].get("dataset_identity")
        or manifests[0].get("tokenizer_fingerprint") != manifests[1].get("tokenizer_fingerprint")
        or manifests[0].get("model_fingerprint") != manifests[1].get("model_fingerprint")
    ):
        raise EvaluationError("BASELINE_REFERENCE_INVALID", "Full baseline identity is not comparable")

    left, right = baseline["metrics"], candidate["metrics"]
    left_next, right_next = left["next_token"], right["next_token"]
    left_position, right_position = left["position"], right["position"]
    scalar_deltas = {
        "loss": right["perplexity"]["loss"] - left["perplexity"]["loss"],
        "perplexity_ratio": right["perplexity"]["perplexity"] / left["perplexity"]["perplexity"],
        "top1": right_next["top1_accuracy"] - left_next["top1_accuracy"],
        "top5": right_next["top5_accuracy"] - left_next["top5_accuracy"],
        "top10": right_next["top10_accuracy"] - left_next["top10_accuracy"],
        "packed_top1": right_position["packed_top1"] - left_position["packed_top1"],
        "rebased_top1": right_position["rebased"]["top1_accuracy"] - left_position["rebased"]["top1_accuracy"],
        "position_gap": right_position["position_gap"] - left_position["position_gap"],
    }
    category_deltas: dict[str, Any] = {}
    for key in left_next.get("token_type_accuracy", {}):
        if key not in right_next.get("token_type_accuracy", {}):
            continue
        left_value, right_value = left_next["token_type_accuracy"][key], right_next["token_type_accuracy"][key]
        category_deltas[key] = {
            metric: right_value[metric] - left_value[metric]
            for metric in ("top1_accuracy", "top5_accuracy", "top10_accuracy", "mean_loss")
            if metric in left_value and metric in right_value
        }
    generation_comparable = manifests[0].get("prompt_set_fingerprint") == manifests[1].get("prompt_set_fingerprint")
    return {
        "status": "completed" if generation_comparable else "completed_with_incomparable_generation_reference",
        "baseline_artifact_id": manifests[0]["artifact_id"],
        "candidate_artifact_id": manifests[1]["artifact_id"],
        "teacher_forced_metrics": "comparable",
        "generation_metrics": "comparable" if generation_comparable else "incomparable_prompt_identity",
        "generation_prompt_error_code": None if generation_comparable else "GENERATION_PROMPT_INCOMPARABLE",
        "scalar_deltas": scalar_deltas,
        "token_category_deltas": category_deltas,
        "position_bucket_top1_deltas": {
            key: right_position["buckets"][key]["top1_accuracy"] - left_position["buckets"][key]["top1_accuracy"]
            for key in left_position.get("buckets", {}) if key in right_position.get("buckets", {})
        },
        "resource_deltas": {
            key: candidate["resource"][key] - baseline["resource"][key]
            for key in ("evaluation_seconds", "tokens_per_second", "peak_gpu_reserved_bytes", "cpu_working_set_bytes")
            if baseline["resource"].get(key) is not None and candidate["resource"].get(key) is not None
        },
        "baseline_result_fingerprint": manifests[0]["result_fingerprint"],
        "candidate_result_fingerprint": manifests[1]["result_fingerprint"],
        "composite_score_used": False,
    }
