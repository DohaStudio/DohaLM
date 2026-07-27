"""Atomic comparison package for one fixed four-stage Quick evaluation."""

from __future__ import annotations

import datetime as dt
from typing import Any

from src.data.checksums import checksum_value

from .artifacts import ArtifactRegistry
from .config import EvaluationConfig, EvaluationError
from .reporting import load_completed_result
from .runner import _publish


ARTIFACT_ORDER = ("initial-seed-17", "pilot-100", "candidate-a-mid", "candidate-a-final")


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return sum(values) / len(values) if values else None


def _continuation_summary(value: dict[str, Any]) -> dict[str, Any]:
    rows = value.get("rows", [])
    if not rows:
        return {"probes": 0, "exact_continuation_rate": None}
    return {
        "probes": len(rows), "first_token_accuracy": _mean(rows, "first_token_accuracy"),
        "first_4_accuracy": _mean(rows, "first_4_accuracy"), "first_8_accuracy": _mean(rows, "first_8_accuracy"),
        "first_16_accuracy": _mean(rows, "first_16_accuracy"), "prefix_match_length": _mean(rows, "prefix_match_length"),
        "exact_continuation_rate": _mean(rows, "exact_continuation"),
        "teacher_forced_loss": _mean(rows, "teacher_forced_loss"),
        "autoregressive_token_match": _mean(rows, "autoregressive_token_match"),
        "eos_rate": _mean(rows, "eos_reached"), "repetition_rate": _mean(rows, "repetition_rate"),
        "special_token_rate": _mean(rows, "special_token_rate"),
    }


def _row(result: dict[str, Any], registry: ArtifactRegistry) -> dict[str, Any]:
    manifest, metrics, resource = result["manifest"], result["metrics"], result["resource"]
    artifact = registry.get(manifest["artifact_id"]).value
    generation = metrics["generation"]
    position = metrics["position"]
    return {
        "artifact_id": manifest["artifact_id"], "training_stage": artifact["training_stage"],
        "checkpoint_step": artifact["checkpoint_step"], "consumed_tokens": artifact["consumed_tokens"],
        "equivalent_epoch": artifact["equivalent_epoch"], "profile": manifest["profile"],
        "source_lineage_fingerprint": artifact["source_lineage_fingerprint"],
        "checkpoint_bundle_bytes": artifact["checkpoint_bundle_bytes"],
        "loss": metrics["perplexity"]["loss"], "perplexity": metrics["perplexity"]["perplexity"],
        "perplexity_overflow": metrics["perplexity"]["perplexity_overflow"],
        "evaluated_sequences": metrics["perplexity"]["sequences"],
        "evaluated_target_tokens": metrics["perplexity"]["target_tokens"],
        "evaluated_batches": metrics["perplexity"]["batches"],
        "top1": metrics["next_token"]["top1_accuracy"], "top5": metrics["next_token"]["top5_accuracy"],
        "top10": metrics["next_token"]["top10_accuracy"],
        "sequence_top1_distribution": metrics["next_token"].get("sequence_top1_distribution", {}),
        "token_type_accuracy": metrics["next_token"].get("token_type_accuracy", {}),
        "packed_top1": position["packed_top1"], "packed_top5": position["packed_top5"],
        "rebased_top1": position["rebased"].get("top1_accuracy"),
        "rebased_top5": position["rebased"].get("top5_accuracy"),
        "packed_loss": position["packed_loss"], "rebased_loss": position["rebased"].get("loss"),
        "position_gap": position["position_gap"], "position_buckets": position["buckets"],
        "eos_rate": generation["eos_rate"], "average_generation_length": generation["average_generation_length"],
        "maximum_length_rate": generation["maximum_length_rate"], "adjacent_repetition": generation["repetition_rate"],
        "repeated_bigram_rate": generation["repeated_bigram_rate"],
        "repeated_trigram_rate": generation["repeated_trigram_rate"],
        "unique_token_ratio": generation["unique_token_ratio"],
        "distinct_1": generation["distinct_1"], "distinct_2": generation["distinct_2"], "distinct_3": generation["distinct_3"],
        "degenerate_loop_rate": generation["degenerate_loop_rate"], "empty_generation_rate": generation["empty_rate"],
        "special_token_rate": generation["special_token_rate"], "unk_rate": generation["unk_rate"],
        "byte_fallback_rate": generation["byte_fallback_rate"],
        "continuation": _continuation_summary(metrics["continuation"]), "stability": metrics["stability"],
        "evaluation_seconds": resource["evaluation_seconds"], "tokens_per_second": resource["tokens_per_second"],
        "peak_gpu_allocated_bytes": resource["peak_gpu_allocated_bytes"],
        "peak_gpu_reserved_bytes": resource["peak_gpu_reserved_bytes"],
        "cpu_working_set_bytes": resource["cpu_working_set_bytes"],
        "result_fingerprint": manifest["result_fingerprint"], "status": manifest["status"],
    }


def _delta(left: dict[str, Any], right: dict[str, Any], label: str) -> dict[str, Any]:
    fields = (
        "loss", "top1", "top5", "top10", "packed_top1", "rebased_top1", "position_gap",
        "eos_rate", "maximum_length_rate", "adjacent_repetition", "distinct_1", "distinct_2", "distinct_3",
        "evaluation_seconds", "tokens_per_second", "peak_gpu_reserved_bytes",
    )
    delta = {field: None if left.get(field) is None or right.get(field) is None else right[field] - left[field] for field in fields}
    left_ppl, right_ppl = left.get("perplexity"), right.get("perplexity")
    delta["perplexity_ratio"] = None if left_ppl in (None, 0) or right_ppl is None else right_ppl / left_ppl
    return {"transition": label, "from": left["artifact_id"], "to": right["artifact_id"], "delta": delta}


def _comparability(results: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    keys = (
        "dataset_identity", "evaluation_subset_identity", "tokenizer_fingerprint", "config_fingerprint",
        "prompt_set_fingerprint", "precision", "profile",
    )
    baseline = results[0]["manifest"]
    mismatches: dict[str, Any] = {}
    for key in keys:
        values = [result["manifest"].get(key) for result in results]
        if any(value != baseline.get(key) for value in values[1:]):
            mismatches[key] = values
    if not mismatches:
        return "comparable", {}
    if "dataset_identity" in mismatches or "evaluation_subset_identity" in mismatches:
        return "incomparable_dataset", mismatches
    return "incomparable_config", mismatches


def publish_quick_comparison(
    config: EvaluationConfig,
    registry: ArtifactRegistry,
    *,
    comparison_id: str,
    evaluation_ids: dict[str, str],
) -> dict[str, Any]:
    if tuple(evaluation_ids) != ARTIFACT_ORDER:
        raise EvaluationError("COMPARISON_ORDER_INVALID", "artifact order must be Initial, Pilot, Mid, Final")
    results = [load_completed_result(config, f"{artifact_id}:{evaluation_ids[artifact_id]}") for artifact_id in ARTIFACT_ORDER]
    status, mismatches = _comparability(results)
    if status != "comparable":
        raise EvaluationError(status.upper(), "evaluation results do not share one comparison identity")
    rows = [_row(result, registry) for result in results]
    deltas = [
        _delta(rows[0], rows[1], "initial_to_pilot"), _delta(rows[1], rows[2], "pilot_to_mid"),
        _delta(rows[2], rows[3], "mid_to_final"), _delta(rows[0], rows[3], "initial_to_final"),
    ]
    deterministic = {
        "comparison_id": comparison_id, "artifact_order": list(ARTIFACT_ORDER),
        "result_fingerprints": {row["artifact_id"]: row["result_fingerprint"] for row in rows},
        "rows": rows, "deltas": deltas,
    }
    comparison_fingerprint = checksum_value(deterministic)
    baseline = results[0]["manifest"]
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest = {
        "schema_version": "1.0", "comparison_id": comparison_id, "comparison_status": status,
        "artifact_ids": list(ARTIFACT_ORDER), "artifact_order": list(ARTIFACT_ORDER), "evaluation_profile": "quick",
        "dataset_fingerprint": baseline["dataset_identity"]["evaluation_fingerprint"],
        "subset_fingerprint": baseline["evaluation_subset_identity"]["index_fingerprint"],
        "tokenizer_fingerprint": baseline["tokenizer_fingerprint"], "config_fingerprint": baseline["config_fingerprint"],
        "prompt_set_fingerprint": baseline["prompt_set_fingerprint"], "precision": baseline["precision"],
        "environment": baseline["environment"], "started_at": min(result["manifest"]["started_at"] for result in results),
        "completed_at": now, "per_artifact_result_fingerprint": deterministic["result_fingerprints"],
        "comparison_result_fingerprint": comparison_fingerprint, "failure_status": None,
        "mismatches": mismatches, "text_storage": False, "token_id_storage": False,
        "output_logical_path": f"{config.output_root}/comparisons/{comparison_id}",
    }
    summary = {
        "schema_version": "1.0", "comparison_id": comparison_id, "status": status,
        "comparison_result_fingerprint": comparison_fingerprint, "rows": rows, "deltas": deltas,
        "composite_score_used": False, "raw_text_stored": False, "token_ids_stored": False,
    }
    _publish(config.external_path(f"{config.output_root}/comparisons/{comparison_id}"), {
        "manifests/comparison.json": manifest, "metrics/artifact-metrics.json": {"rows": rows},
        "metrics/deltas.json": {"deltas": deltas},
        "generation/comparison.json": {"rows": [{key: row[key] for key in (
            "artifact_id", "eos_rate", "average_generation_length", "maximum_length_rate",
            "adjacent_repetition", "repeated_bigram_rate", "repeated_trigram_rate", "unique_token_ratio",
            "distinct_1", "distinct_2", "distinct_3", "degenerate_loop_rate", "empty_generation_rate",
        )} for row in rows]},
        "reports/comparison-summary.json": summary,
        "logs/execution.json": {
            "artifact_count": len(rows), "execution_order": list(ARTIFACT_ORDER), "automatic_retry_count": 0,
        },
        "failures/status.json": {"failure_count": 0, "failures": []},
    })
    return summary
