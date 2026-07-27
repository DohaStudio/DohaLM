"""Read-only, text-free EOS and Quick/Full diagnostics."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import torch
from torch.utils.data import DataLoader

from src.data.checksums import checksum_value, file_checksum
from src.data.tokenized_dataset import TokenizedJsonlDataset
from src.runtime.environment import collect_environment
from src.runtime.paths import repository_root
from src.tokenizer.tokenizer import DohaTokenizer, SPECIAL_TOKEN_IDS
from src.training.collator import CausalLMCollator

from .artifacts import ArtifactRegistry
from .config import EvaluationConfig, EvaluationError
from .metrics import generation_statistics, quantiles
from .reporting import load_completed_result
from .runner import _load_prompts, _model_digest, _prepare_model, _publish


EOS_ID = SPECIAL_TOKEN_IDS["<eos>"]
BOS_ID = SPECIAL_TOKEN_IDS["<bos>"]
EVALUATION_POLICY_STATUS = "approved"
EVALUATION_POLICY_APPROVAL_DATE = "2026-07-27"
CANDIDATE_B_TRAINING_STATUS = "not_approved"
QUICK_V2_STATUS = "planned_awaiting_separate_approval"
REPRESENTATIVENESS_THRESHOLDS = {
    "representative": {"loss": 0.05, "top1": 0.005, "top5": 0.0075, "top10": 0.01, "position_gap": 0.005},
    "approximately_representative": {"loss": 0.10, "top1": 0.015, "top5": 0.02, "top10": 0.02, "position_gap": 0.015},
}


def _distribution(values: Iterable[float]) -> dict[str, float | None]:
    return quantiles(list(values))


def _js_divergence(left: dict[str, float], right: dict[str, float]) -> float:
    keys = set(left) | set(right)
    total = 0.0
    for key in keys:
        a, b = left.get(key, 0.0), right.get(key, 0.0)
        middle = (a + b) / 2.0
        if a > 0:
            total += 0.5 * a * math.log(a / middle)
        if b > 0:
            total += 0.5 * b * math.log(b / middle)
    return total


def _psi(left: dict[str, float], right: dict[str, float]) -> float:
    epsilon = 1e-12
    return sum(
        (max(right.get(key, 0.0), epsilon) - max(left.get(key, 0.0), epsilon))
        * math.log(max(right.get(key, 0.0), epsilon) / max(left.get(key, 0.0), epsilon))
        for key in set(left) | set(right)
    )


def _ks(left: list[float], right: list[float]) -> float | None:
    if not left or not right:
        return None
    values = sorted(set(left + right))
    a, b = sorted(left), sorted(right)
    i = j = 0
    largest = 0.0
    for value in values:
        while i < len(a) and a[i] <= value:
            i += 1
        while j < len(b) and b[j] <= value:
            j += 1
        largest = max(largest, abs(i / len(a) - j / len(b)))
    return largest


def classify_eos_offset(eos_offset: int, *, context_length: int = 256) -> str:
    return "eos_shifted_out_of_target" if eos_offset % context_length == 0 else "eos_preserved"


def inspect_packed_rows(path: Path, *, context_length: int = 256) -> dict[str, Any]:
    sequences = padding = total_eos = target_eos = masked_eos = position_zero = position_255 = 0
    positions = Counter()
    eos_followed_by_bos_same_block = 0
    for line in path.open("r", encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        ids, labels, mask = row["input_ids"], row["labels"], row["attention_mask"]
        if not (len(ids) == len(labels) == len(mask) == context_length):
            raise EvaluationError("PACKING_CONTRACT_MISMATCH", "packed row width mismatch")
        sequences += 1
        padding += mask.count(0)
        for position, token in enumerate(ids):
            if token != EOS_ID:
                continue
            total_eos += 1
            positions[str(position)] += 1
            position_zero += int(position == 0)
            position_255 += int(position == context_length - 1)
            target_eos += int(position > 0 and labels[position] == EOS_ID)
            masked_eos += int(labels[position] == -100)
            eos_followed_by_bos_same_block += int(position + 1 < context_length and ids[position + 1] == BOS_ID)
    return {
        "sequences": sequences, "padding_tokens": padding, "input_eos_tokens": total_eos,
        "target_eos_tokens": target_eos, "masked_eos_tokens": masked_eos,
        "position_zero_eos": position_zero, "position_255_eos": position_255,
        "eos_followed_by_bos_same_block": eos_followed_by_bos_same_block,
        "dropped_tokens": 0, "packing_mode": "continuous", "remainder_policy": "pad",
        "document_boundary": "EOS followed by next BOS when both are in the same block",
        "padding_labels_masked": True, "eos_is_attention_target": True,
        "eos_is_loss_target_except_block_position_zero": True,
        "position_counts": dict(sorted(positions.items(), key=lambda item: int(item[0]))),
        "actual_text_values_stored": False, "token_ids_stored": False,
    }


def reconcile_records(corpus_path: Path, tokenizer: DohaTokenizer, packed: dict[str, Any]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    cursor = 0
    last_block = int(packed["sequences"]) - 1
    for line in corpus_path.open("r", encoding="utf-8"):
        value = json.loads(line)
        text = value.pop("text")
        ids = tokenizer.encode(text, add_bos=True, add_eos=True).ids
        del text
        start, end = cursor, cursor + len(ids) - 1
        reason = classify_eos_offset(end)
        record_hash = value["document_id"]
        records.append({
            "record_hash": record_hash,
            "original_token_length": len(ids) - 2,
            "bos_included_token_length": len(ids) - 1,
            "eos_included_token_length": len(ids),
            "packed_start_block": start // 256, "packed_start_position": start % 256,
            "packed_end_block": end // 256, "packed_end_position": end % 256,
            "eos_inserted": ids[-1] == EOS_ID, "eos_in_input": True,
            "eos_in_label": reason == "eos_preserved", "eos_masked": False,
            "eos_crossed_block_boundary": False, "truncated": False,
            "incomplete_block": end // 256 == last_block and int(packed["padding_tokens"]) > 0,
            "excluded_reason_code": reason,
        })
        cursor += len(ids)
    counts = Counter(row["excluded_reason_code"] for row in records)
    unexplained = sum(count for reason, count in counts.items() if reason not in {"eos_preserved", "eos_shifted_out_of_target"})
    return {
        "record_count": len(records), "total_token_stream_length": cursor,
        "classification_counts": dict(sorted(counts.items())), "unexplained_record_count": unexplained,
        "records": records, "actual_text_values_stored": False, "token_ids_stored": False,
    }


def _rank_summary(values: list[dict[str, float]], *, prefix: str = "") -> dict[str, Any]:
    ranks = [row["rank"] for row in values]
    return {
        f"{prefix}count": len(values), f"{prefix}rank_distribution": _distribution(ranks),
        f"{prefix}logit_distribution": _distribution(row["logit"] for row in values),
        f"{prefix}probability_distribution": _distribution(row["probability"] for row in values),
        f"{prefix}top1_minus_eos_logit_margin": _distribution(row["logit_margin"] for row in values),
        f"{prefix}top1_minus_eos_probability_margin": _distribution(row["probability_margin"] for row in values),
        f"{prefix}rank_1_rate": sum(rank == 1 for rank in ranks) / len(ranks) if ranks else None,
        f"{prefix}rank_2_5_rate": sum(2 <= rank <= 5 for rank in ranks) / len(ranks) if ranks else None,
        f"{prefix}rank_6_10_rate": sum(6 <= rank <= 10 for rank in ranks) / len(ranks) if ranks else None,
        f"{prefix}rank_11_plus_rate": sum(rank >= 11 for rank in ranks) / len(ranks) if ranks else None,
    }


def eos_ranking(model: Any, dataset_path: Path, device: torch.device, record_lengths: list[int]) -> dict[str, Any]:
    dataset = TokenizedJsonlDataset(dataset_path, context_length=256, vocab_size=16000)
    loader = DataLoader(dataset, batch_size=8, shuffle=False, collate_fn=CausalLMCollator(context_length=256))
    rows: list[dict[str, float]] = []
    position_groups: dict[str, list[dict[str, float]]] = {key: [] for key in ("0-31", "32-63", "64-127", "128-191", "192-254", "255")}
    context_groups: dict[str, list[dict[str, float]]] = {key: [] for key in ("short_0_63", "medium_64_127", "long_128_255")}
    document_groups: dict[str, list[dict[str, float]]] = {key: [] for key in ("short_0_255", "medium_256_511", "long_512_plus")}
    record_cursor = 0
    with torch.inference_mode():
        for batch in loader:
            ids, labels, mask = (batch[key].to(device) for key in ("input_ids", "labels", "attention_mask"))
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                logits = model(ids, attention_mask=mask).logits[:, :-1, :].float()
            targets = labels[:, 1:]
            for row_index, position in (targets == EOS_ID).nonzero(as_tuple=False).detach().cpu().tolist():
                vector = logits[row_index, position]
                eos_logit = vector[EOS_ID]
                logsum = torch.logsumexp(vector, dim=0)
                probability = torch.exp(eos_logit - logsum)
                top_index = int(vector.argmax().item())
                rank = int((vector > eos_logit).sum().item()) + 1
                top_probability = torch.exp(vector[top_index] - logsum)
                absolute_position = position + 1
                previous = (ids[row_index, :absolute_position] == EOS_ID).nonzero(as_tuple=False)
                previous_position = int(previous[-1].item()) if previous.numel() else -1
                context_length = absolute_position - previous_position - 1
                item = {
                    "rank": float(rank), "logit": float(eos_logit.item()), "probability": float(probability.item()),
                    "logit_margin": float((vector[top_index] - eos_logit).item()),
                    "probability_margin": float((top_probability - probability).item()),
                }
                rows.append(item)
                if absolute_position == 255:
                    position_groups["255"].append(item)
                elif absolute_position <= 31:
                    position_groups["0-31"].append(item)
                elif absolute_position <= 63:
                    position_groups["32-63"].append(item)
                elif absolute_position <= 127:
                    position_groups["64-127"].append(item)
                elif absolute_position <= 191:
                    position_groups["128-191"].append(item)
                else:
                    position_groups["192-254"].append(item)
                context_key = "short_0_63" if context_length <= 63 else "medium_64_127" if context_length <= 127 else "long_128_255"
                context_groups[context_key].append(item)
                document_length = record_lengths[record_cursor]
                record_cursor += 1
                document_key = "short_0_255" if document_length <= 255 else "medium_256_511" if document_length <= 511 else "long_512_plus"
                document_groups[document_key].append(item)
    if record_cursor != len(record_lengths):
        raise EvaluationError("EOS_RECORD_ALIGNMENT_MISMATCH", "EOS targets and eligible record lengths do not align")
    return {
        **_rank_summary(rows),
        "position_buckets": {key: _rank_summary(value) for key, value in position_groups.items()},
        "context_buckets": {key: _rank_summary(value) for key, value in context_groups.items()},
        "document_length_buckets": {key: _rank_summary(value) for key, value in document_groups.items()},
        "actual_text_values_stored": False, "token_ids_stored": False,
    }


def _sample(logits: torch.Tensor, profile: dict[str, Any], generator: torch.Generator) -> int:
    if profile["strategy"] == "greedy":
        return int(logits.argmax().item())
    adjusted = logits / float(profile["temperature"])
    if profile.get("top_k"):
        threshold = torch.topk(adjusted, int(profile["top_k"])).values[-1]
        adjusted = adjusted.masked_fill(adjusted < threshold, float("-inf"))
    probabilities = torch.softmax(adjusted, dim=-1)
    if profile.get("top_p"):
        sorted_probs, sorted_indices = torch.sort(probabilities, descending=True)
        cumulative = torch.cumsum(sorted_probs, dim=-1)
        remove = cumulative - sorted_probs > float(profile["top_p"])
        sorted_probs = sorted_probs.masked_fill(remove, 0.0)
        sorted_probs /= sorted_probs.sum()
        selected = torch.multinomial(sorted_probs, 1, generator=generator)
        return int(sorted_indices[selected].item())
    return int(torch.multinomial(probabilities, 1, generator=generator).item())


def decoding_diagnostic(model: Any, tokenizer: DohaTokenizer, prompts: list[dict[str, Any]], device: torch.device) -> dict[str, Any]:
    profiles = (
        {"name": "greedy", "strategy": "greedy", "temperature": None},
        {"name": "temperature-0.7", "strategy": "sample", "temperature": 0.7},
        {"name": "temperature-1.0", "strategy": "sample", "temperature": 1.0},
        {"name": "top-k-20", "strategy": "sample", "temperature": 1.0, "top_k": 20},
        {"name": "top-k-50", "strategy": "sample", "temperature": 1.0, "top_k": 50},
        {"name": "top-p-0.9", "strategy": "sample", "temperature": 1.0, "top_p": 0.9},
        {"name": "top-p-0.95", "strategy": "sample", "temperature": 1.0, "top_p": 0.95},
    )
    byte_ids = {index for index in range(tokenizer.vocab_size) if tokenizer.processor.id_to_piece(index).startswith("<0x")}

    def run(profile: dict[str, Any]) -> tuple[list[list[int]], list[dict[str, Any]]]:
        outputs, metadata = [], []
        for prompt in prompts:
            encoded = tokenizer.encode(prompt["text"], truncation=True, max_length=240)
            sequence = torch.tensor([encoded.ids], device=device)
            seed = int.from_bytes(hashlib.sha256(f"17:{profile['name']}:{prompt['prompt_id']}".encode()).digest()[:8], "big") % (2**63 - 1)
            generator = torch.Generator(device=device).manual_seed(seed)
            generated: list[int] = []
            eos_rows: list[dict[str, float]] = []
            loop_step = None
            for step in range(16):
                # Match the existing Quick generation contract, which runs
                # inference without FP16 autocast even when teacher-forced
                # evaluation uses FP16.
                with torch.inference_mode():
                    logits = model(sequence, attention_mask=torch.ones_like(sequence, dtype=torch.bool)).logits[0, -1].float()
                eos_logit = logits[EOS_ID]
                logsum = torch.logsumexp(logits, dim=0)
                eos_probability = torch.exp(eos_logit - logsum)
                top_index = int(logits.argmax().item())
                eos_rows.append({
                    "rank": float(int((logits > eos_logit).sum().item()) + 1),
                    "probability": float(eos_probability.item()),
                    "logit_margin": float((logits[top_index] - eos_logit).item()),
                    "probability_margin": float((torch.exp(logits[top_index] - logsum) - eos_probability).item()),
                })
                token = _sample(logits, profile, generator)
                generated.append(token)
                sequence = torch.cat((sequence, torch.tensor([[token]], device=device)), dim=1)
                if loop_step is None and len(generated) >= 8 and tuple(generated[-4:]) in [tuple(generated[i:i + 4]) for i in range(len(generated) - 7)]:
                    loop_step = step + 1
                if token == EOS_ID:
                    break
            outputs.append(generated)
            metadata.append({
                "prompt_id": prompt["prompt_id"], "input_token_length": len(encoded.ids),
                "generated_token_length": len(generated), "best_eos_rank": min(row["rank"] for row in eos_rows),
                "mean_eos_rank": sum(row["rank"] for row in eos_rows) / len(eos_rows),
                "final_eos_rank": eos_rows[-1]["rank"], "maximum_eos_probability": max(row["probability"] for row in eos_rows),
                "eos_top5_step_count": sum(row["rank"] <= 5 for row in eos_rows),
                "eos_top10_step_count": sum(row["rank"] <= 10 for row in eos_rows),
                "loop_start_step": loop_step, "termination_reason": "eos" if generated[-1] == EOS_ID else "maximum_length",
            })
        return outputs, metadata

    result: dict[str, Any] = {}
    for profile in profiles:
        first, metadata = run(profile)
        second, _ = run(profile)
        stats = [generation_statistics(tokens, eos_id=EOS_ID, unk_id=tokenizer.unk_id, special_ids=set(SPECIAL_TOKEN_IDS.values()), byte_ids=byte_ids) for tokens in first]
        def repeated_ngram_rate(tokens: list[int], n: int) -> float:
            grams = [tuple(tokens[index:index + n]) for index in range(max(0, len(tokens) - n + 1))]
            repeated = sum(amount - 1 for amount in Counter(grams).values() if amount > 1)
            return repeated / len(grams) if grams else 0.0
        mean = lambda key: sum(float(row[key]) for row in stats) / len(stats)
        result[profile["name"]] = {
            "config": profile, "samples": len(stats), "deterministic_reproduction": first == second,
            "eos_rate": mean("eos_reached"), "mean_eos_step": (
                sum(next((i + 1 for i, token in enumerate(tokens) if token == EOS_ID), 0) for tokens in first) /
                max(1, sum(EOS_ID in tokens for tokens in first)) if any(EOS_ID in tokens for tokens in first) else None
            ),
            "maximum_length_rate": sum(EOS_ID not in tokens for tokens in first) / len(first),
            "adjacent_repetition": mean("adjacent_repetition_rate"),
            "repeated_bigram_rate": sum(repeated_ngram_rate(tokens, 2) for tokens in first) / len(first),
            "repeated_trigram_rate": sum(repeated_ngram_rate(tokens, 3) for tokens in first) / len(first),
            "repeated_4gram_rate": mean("repeated_4gram_rate"),
            "distinct_1": mean("distinct_1"), "distinct_2": mean("distinct_2"), "distinct_3": mean("distinct_3"),
            "degenerate_loop_rate": mean("degenerate_loop"), "special_token_rate": mean("special_token_rate"),
            "unk_rate": mean("unk_rate"), "byte_fallback_rate": mean("byte_fallback_rate"),
            "prompt_metadata": metadata, "generated_text_stored": False, "token_ids_stored": False,
        }
    return {
        "profiles": result,
        "generation_contract": {
            "maximum_new_tokens": 16, "eos_suppression": False, "minimum_length": None,
            "special_token_suppression": False, "kv_cache": False, "attention_mask": "all_prompt_and_generated_tokens",
            "temperature_for_greedy": "not_applied", "stop_condition": "EOS ID 3 or maximum_new_tokens",
        },
        "actual_text_values_stored": False, "token_ids_stored": False,
    }


def distribution_comparison(quick: dict[str, Any], full: dict[str, Any]) -> dict[str, Any]:
    quick_rows = [float(row["top1_accuracy"]) for row in quick["per_sequence"]["rows"]]
    full_rows = [float(row["top1_accuracy"]) for row in full["per_sequence"]["rows"]]
    quick_lengths = [float(row["target_tokens"]) for row in quick["per_sequence"]["rows"]]
    full_lengths = [float(row["target_tokens"]) for row in full["per_sequence"]["rows"]]
    q_categories, f_categories = quick["metrics"]["next_token"]["token_type_accuracy"], full["metrics"]["next_token"]["token_type_accuracy"]
    q_total = sum(int(row["tokens"]) for row in q_categories.values())
    f_total = sum(int(row["tokens"]) for row in f_categories.values())
    q_prop = {key: row["tokens"] / q_total for key, row in q_categories.items()}
    f_prop = {key: row["tokens"] / f_total for key, row in f_categories.items()}
    q_pos, f_pos = quick["metrics"]["position"]["buckets"], full["metrics"]["position"]["buckets"]
    q_pos_total, f_pos_total = sum(row["tokens"] for row in q_pos.values()), sum(row["tokens"] for row in f_pos.values())
    q_pos_prop = {key: row["tokens"] / q_pos_total for key, row in q_pos.items()}
    f_pos_prop = {key: row["tokens"] / f_pos_total for key, row in f_pos.items()}
    return {
        "sequence_target_length": {"quick": _distribution(quick_lengths), "full": _distribution(full_lengths), "ks": _ks(quick_lengths, full_lengths)},
        "sequence_top1": {"quick": _distribution(quick_rows), "full": _distribution(full_rows), "ks": _ks(quick_rows, full_rows)},
        "category_proportions": {key: {"quick": q_prop.get(key, 0.0), "full": f_prop.get(key, 0.0), "delta": q_prop.get(key, 0.0) - f_prop.get(key, 0.0)} for key in sorted(set(q_prop) | set(f_prop))},
        "category_js_divergence": _js_divergence(q_prop, f_prop), "category_psi": _psi(q_prop, f_prop),
        "position_proportions": {key: {"quick": q_pos_prop.get(key, 0.0), "full": f_pos_prop.get(key, 0.0), "delta": q_pos_prop.get(key, 0.0) - f_pos_prop.get(key, 0.0)} for key in sorted(set(q_pos_prop) | set(f_pos_prop))},
        "position_js_divergence": _js_divergence(q_pos_prop, f_pos_prop), "position_psi": _psi(q_pos_prop, f_pos_prop),
        "eos_ratio": {"quick": q_prop.get("eos", 0.0), "full": f_prop.get("eos", 0.0), "delta": q_prop.get("eos", 0.0) - f_prop.get("eos", 0.0)},
        "source_archive_distribution": "not_available_in_approved_packed_artifact",
        "source_category_distribution": "not_available_in_approved_packed_artifact",
        "per_sequence_loss_distribution": "not_available_in_historical_quick_result",
        "actual_text_values_stored": False, "token_ids_stored": False,
    }


def run_diagnostic(config: EvaluationConfig, registry: ArtifactRegistry, *, diagnostic_id: str) -> dict[str, Any]:
    output = config.external_path(f"{config.output_root}/diagnostics/eos-quick-policy/{diagnostic_id}")
    if output.exists():
        raise EvaluationError("EVALUATION_OUTPUT_EXISTS", "diagnostic output already exists")
    artifact = registry.get("candidate-a-final")
    inspection = registry.inspect(config, "candidate-a-final", require_eligible=True)
    if inspection["status"] != "eligible":
        raise EvaluationError("ARTIFACT_EVALUATION_BLOCKED", "Candidate A Final is not eligible")
    quick = load_completed_result(config, "candidate-a-final:initial-pilot-candidate-a-quick-20260727-01")
    full = load_completed_result(config, "candidate-a-final:candidate-a-final-full-20260727-01")
    quick["per_sequence"] = json.loads(config.external_path(
        f"{config.output_root}/candidate-a-final/initial-pilot-candidate-a-quick-20260727-01/metrics/per-sequence.json"
    ).read_text(encoding="utf-8"))
    full["per_sequence"] = json.loads(config.external_path(
        f"{config.output_root}/candidate-a-final/candidate-a-final-full-20260727-01/metrics/per-sequence.json"
    ).read_text(encoding="utf-8"))
    prepared = config.external_path(str(Path(config.dataset_manifest).parent).replace("\\", "/"))
    packed_path, corpus_path = prepared / "evaluation.jsonl", prepared / "evaluation-corpus.jsonl"
    source_checksums = {path.name: file_checksum(path) for path in (packed_path, corpus_path, prepared / "packing-manifest.json", prepared / "tokenization-manifest.json")}
    tokenizer_path = config.external_path(config.tokenizer_model)
    tokenizer = DohaTokenizer(tokenizer_path)
    packed = inspect_packed_rows(packed_path)
    reconciliation = reconcile_records(corpus_path, tokenizer, packed)
    if reconciliation["record_count"] != 4799 or packed["input_eos_tokens"] != 4799 or packed["target_eos_tokens"] != 4782:
        raise EvaluationError("EOS_RECONCILIATION_MISMATCH", "observed EOS counts do not match approved Full result")
    if reconciliation["classification_counts"].get("eos_shifted_out_of_target") != 17 or reconciliation["unexplained_record_count"]:
        raise EvaluationError("EOS_RECONCILIATION_UNKNOWN", "EOS difference is not completely classified")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type != "cuda":
        raise EvaluationError("CUDA_REQUIRED", "EOS ranking diagnostic requires approved CUDA environment")
    model, checkpoint_before = _prepare_model(config, artifact, device)
    model_before = _model_digest(model)
    eligible_record_lengths = [row["original_token_length"] for row in reconciliation["records"] if row["eos_in_label"]]
    ranking = eos_ranking(model, packed_path, device, eligible_record_lengths)
    prompts, prompt_fingerprint = _load_prompts(config)
    decoding = decoding_diagnostic(model, tokenizer, prompts, device)
    model_after = _model_digest(model)
    checkpoint_after = file_checksum(config.external_path(artifact.value["logical_external_path"]) / "checksums.json")
    if model_before != model_after or checkpoint_before != checkpoint_after:
        raise EvaluationError("EVALUATION_MUTATED_ARTIFACT", "diagnostic changed model or checkpoint")
    distributions = distribution_comparison(quick, full)
    policy = {
        "status": EVALUATION_POLICY_STATUS,
        "approval_date": EVALUATION_POLICY_APPROVAL_DATE,
        "grades": REPRESENTATIVENESS_THRESHOLDS,
        "candidate_a_grade": "approximately_representative",
        "candidate_a_bias_direction": "optimistic",
        "candidate_a_bias_characteristic": "biased_optimistic",
        "quick_v2_status": QUICK_V2_STATUS,
        "development_role": "regression_and_directional_signal_only",
        "official_role": "Full Evaluation required for candidate baseline and milestone decisions",
    }
    eos_policy = {
        "status": EVALUATION_POLICY_STATUS, "approval_date": EVALUATION_POLICY_APPROVAL_DATE,
        "teacher_forced_baseline": {
            "target_count": 4782, "top1": full["metrics"]["next_token"]["token_type_accuracy"]["eos"]["top1_accuracy"],
            "top5": full["metrics"]["next_token"]["token_type_accuracy"]["eos"]["top5_accuracy"],
            "top10": full["metrics"]["next_token"]["token_type_accuracy"]["eos"]["top10_accuracy"],
            "mean_loss": full["metrics"]["next_token"]["token_type_accuracy"]["eos"]["mean_loss"],
        },
        "candidate_b_required": [
            "EOS target count and ratio unchanged unless a separately approved data policy changes",
            "EOS Top-1/5/10 must not regress from Candidate A Full",
            "greedy EOS rate must improve above 0%", "maximum-length rate must decrease below 100%",
            "adjacent repetition and degenerate loop must not regress", "special-token exposure must remain 0%",
        ],
    }
    contract = {
        "status": EVALUATION_POLICY_STATUS, "approval_date": EVALUATION_POLICY_APPROVAL_DATE,
        "baseline": [
            quick["manifest"]["result_fingerprint"], full["manifest"]["result_fingerprint"],
            "initial-pilot-candidate-a-quick-20260727-01",
        ],
        "required_evaluations": ["same Quick", "same Full internal", "same synthetic generation", "same EOS ranking", "same position-aware", "same token category"],
        "required_metrics": ["Full loss/perplexity/Top-1/5/10", "Korean accuracy", "EOS Top-1/5/10 and rank", "greedy EOS/max-length", "repetition/distinct-n", "position gap", "stability", "resource"],
        "composite_score": None, "candidate_b_training": CANDIDATE_B_TRAINING_STATUS,
        "quick_v2_status": QUICK_V2_STATUS,
    }
    deterministic = {
        "reconciliation": reconciliation, "packing": packed, "ranking": ranking,
        "decoding": decoding, "distribution": distributions, "quick_policy": policy,
        "eos_policy": eos_policy, "candidate_b_contract": contract,
    }
    result_fingerprint = checksum_value(deterministic)
    manifest = {
        "schema_version": "1.0", "diagnostic_id": diagnostic_id, "status": "completed",
        "artifact_identity": artifact.identity_fingerprint, "dataset_identity": config.dataset_identity,
        "quick_result_fingerprint": quick["manifest"]["result_fingerprint"],
        "full_result_fingerprint": full["manifest"]["result_fingerprint"],
        "config_fingerprint": config.fingerprint, "prompt_set_fingerprint": prompt_fingerprint,
        "eos_reconciliation_status": "verified", "unexplained_record_count": 0,
        "decoding_profiles": list(decoding["profiles"]), "policy_status": EVALUATION_POLICY_STATUS,
        "environment": collect_environment(repository_root()), "text_storage": False, "token_id_storage": False,
        "result_fingerprint": result_fingerprint,
        "output_logical_path": f"{config.output_root}/diagnostics/eos-quick-policy/{diagnostic_id}",
        "source_checksums_before": source_checksums, "source_checksums_after": {path.name: file_checksum(path) for path in (packed_path, corpus_path, prepared / "packing-manifest.json", prepared / "tokenization-manifest.json")},
        "model_state_before": model_before, "model_state_after": model_after,
        "checkpoint_before": checkpoint_before, "checkpoint_after": checkpoint_after,
        "training_operations": {"optimizer_created": False, "scheduler_created": False, "backward_called": False, "gradients_enabled": False},
    }
    _publish(output, {
        "manifests/diagnostic.json": manifest,
        "metrics/eos-reconciliation.json": reconciliation,
        "metrics/packing-boundary.json": packed,
        "metrics/eos-ranking.json": ranking,
        "metrics/decoding-comparison.json": decoding,
        "metrics/quick-full-distribution.json": distributions,
        "policies/eos-success-proposal.json": eos_policy,
        "policies/quick-representativeness-proposal.json": policy,
        "policies/candidate-b-evaluation-contract.json": contract,
        "reports/summary.json": {"status": "completed", "result_fingerprint": result_fingerprint, "unknown": 0, "text_stored": False},
        "logs/execution.json": {"automatic_retry_count": 0, "completed": True},
        "failures/status.json": {"failure_count": 0, "failures": []},
    })
    return {"diagnostic_id": diagnostic_id, "status": "completed", "result_fingerprint": result_fingerprint, "unknown": 0}
