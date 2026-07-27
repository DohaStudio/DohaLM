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
