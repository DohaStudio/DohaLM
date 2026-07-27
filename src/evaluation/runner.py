"""Evaluation-only runner for approved DohaLM checkpoints."""

from __future__ import annotations

import ctypes
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as functional
import yaml
from torch.utils.data import DataLoader

from src.data.checksums import canonical_json_bytes, checksum_value, file_checksum
from src.data.tokenized_dataset import TokenizedJsonlDataset
from src.model import DohaLMTiny, ModelConfig
from src.runtime.environment import collect_environment
from src.runtime.paths import repository_root
from src.tokenizer.operating import validate_operating_candidate
from src.tokenizer.tokenizer import DohaTokenizer, SPECIAL_TOKEN_IDS
from src.training.checkpoint import CheckpointManager
from src.training.collator import CausalLMCollator

from .artifacts import ArtifactRegistry, EvaluationArtifact
from .config import EvaluationConfig, EvaluationError
from .datasets import IndexedSubset, deterministic_indices
from .metrics import generation_statistics, prefix_metrics, quantiles, safe_perplexity, token_category


POSITION_BUCKETS = ((0, 31), (32, 63), (64, 127), (128, 191), (192, 255))


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _ensure_deadline(deadline: float) -> None:
    if time.perf_counter() > deadline:
        raise EvaluationError("EVALUATION_TIMEOUT", "evaluation profile timeout exceeded")


def _working_set_bytes() -> int | None:
    if os.name != "nt":
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return int(counters.WorkingSetSize)


def _model_digest(model: DohaLMTiny) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        digest.update(name.encode("utf-8"))
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return f"sha256:{digest.hexdigest()}"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _publish(output: Path, files: dict[str, Any]) -> dict[str, str]:
    if output.exists():
        raise EvaluationError("EVALUATION_OUTPUT_EXISTS", "existing evaluation output cannot be overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        for relative, value in files.items():
            _write_json(staging / relative, value)
        checksums = {relative: file_checksum(staging / relative) for relative in sorted(files)}
        _write_json(staging / "manifests/checksums.json", {"algorithm": "sha256", "files": checksums})
        os.replace(staging, output)
        return checksums
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def publish_failure(config: EvaluationConfig, artifact_id: str, evaluation_id: str, exc: Exception) -> bool:
    """Atomically preserve a text-free failure record for an uncompleted run."""
    if not evaluation_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in evaluation_id):
        return False
    output = config.external_path(f"{config.output_root}/{artifact_id}/{evaluation_id}")
    if output.exists():
        return False
    failure = {
        "schema_version": "1.0", "status": "failed", "artifact_id": artifact_id,
        "evaluation_id": evaluation_id, "failure_code": getattr(exc, "code", type(exc).__name__),
        "failure_type": type(exc).__name__, "automatic_retry": False,
        "raw_text_stored": False, "token_ids_stored": False,
    }
    _publish(output, {"failures/failure.json": failure})
    return True


def _load_prompts(config: EvaluationConfig) -> tuple[list[dict[str, Any]], str]:
    path = config.repository_path(config.prompt_set)
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        prompts = value["prompts"]
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise EvaluationError("PROMPT_SET_INVALID", "synthetic prompt set could not be read") from exc
    if value.get("source") != "synthetic" or value.get("pii_free") is not True or not isinstance(prompts, list):
        raise EvaluationError("PROMPT_SET_INVALID", "prompt set must be synthetic and PII-free")
    return prompts, file_checksum(path)


def _validate_dataset_manifests(config: EvaluationConfig, tokenizer_fingerprint: str, pii_fingerprint: str | None) -> str:
    try:
        dataset_manifest = json.loads(config.external_path(config.dataset_manifest).read_text(encoding="utf-8"))
        split_manifest = json.loads(config.external_path(config.split_manifest).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise EvaluationError("EVALUATION_DATASET_MISMATCH", "dataset manifests could not be read") from exc
    expected = config.dataset_identity
    if dataset_manifest.get("dataset_version") != expected["dataset_version"]:
        raise EvaluationError("EVALUATION_DATASET_MISMATCH", "dataset version mismatch")
    if dataset_manifest.get("statistics", {}).get("evaluation", {}).get("records") != expected["records"]:
        raise EvaluationError("EVALUATION_DATASET_MISMATCH", "evaluation record count mismatch")
    if dataset_manifest.get("split_fingerprint") != expected["split_fingerprint"] or split_manifest.get("split_fingerprint") != expected["split_fingerprint"]:
        raise EvaluationError("EVALUATION_DATASET_MISMATCH", "split fingerprint mismatch")
    if split_manifest.get("original_validation_used") is not False:
        raise EvaluationError("EVALUATION_DATASET_MISMATCH", "original Validation use is forbidden")
    if dataset_manifest.get("tokenizer_fingerprint") != tokenizer_fingerprint or split_manifest.get("tokenizer_fingerprint") != tokenizer_fingerprint:
        raise EvaluationError("TOKENIZER_FINGERPRINT_MISMATCH", "dataset tokenizer identity mismatch")
    if pii_fingerprint is None or dataset_manifest.get("pii_result_fingerprint") != pii_fingerprint:
        raise EvaluationError("PII_FINGERPRINT_MISMATCH", "dataset PII identity mismatch")
    checksum = file_checksum(config.external_path(config.evaluation_dataset))
    if dataset_manifest.get("artifact_checksums", {}).get("evaluation.jsonl") != checksum or expected["evaluation_fingerprint"] != checksum:
        raise EvaluationError("EVALUATION_DATASET_MISMATCH", "evaluation artifact checksum mismatch")
    return checksum


def _prepare_model(config: EvaluationConfig, artifact: EvaluationArtifact, device: torch.device) -> tuple[DohaLMTiny, str | None]:
    torch.manual_seed(config.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(config.seed)
    model = DohaLMTiny(ModelConfig())
    model_fingerprint = checksum_value(model.config.to_dict())
    if model_fingerprint != artifact.value["model_fingerprint"]:
        raise EvaluationError("MODEL_FINGERPRINT_MISMATCH", "model config fingerprint does not match artifact")
    if artifact.is_initial:
        initialization_fingerprint = checksum_value({
            "mode": "fresh_seed_17", "seed": config.seed,
            "model_fingerprint": model_fingerprint, "pilot_checkpoint_used": False,
        })
        if initialization_fingerprint != artifact.value["config_fingerprint"]:
            raise EvaluationError(
                "INITIALIZATION_FINGERPRINT_MISMATCH",
                "deterministic initialization fingerprint does not match artifact",
            )
    checkpoint_checksum = None
    if not artifact.is_initial:
        path = config.external_path(artifact.value["logical_external_path"])
        CheckpointManager.inspect(path)
        checkpoint_checksum = file_checksum(path / "checksums.json")
        try:
            state = torch.load(path / "model.pt", map_location="cpu", weights_only=True)
            model.load_state_dict(state, strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise EvaluationError("CHECKPOINT_LOAD_FAILED", "model weights could not be loaded read-only") from exc
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    model.eval()
    model.to(device)
    return model, checkpoint_checksum


def _aggregate_teacher_forced(model: DohaLMTiny, loader: DataLoader, tokenizer: Any, device: torch.device, *, use_amp: bool, timeout_seconds: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started = time.perf_counter()
    total_loss = 0.0
    total_tokens = 0
    batch_count = 0
    sequence_values: list[float] = []
    top_hits = {1: 0, 5: 0, 10: 0}
    category_names = sorted({token_category(tokenizer.processor.id_to_piece(index), index) for index in range(tokenizer.vocab_size)})
    category_ids = {name: index for index, name in enumerate(category_names)}
    category_lookup = torch.tensor([
        category_ids[token_category(tokenizer.processor.id_to_piece(index), index)]
        for index in range(tokenizer.vocab_size)
    ], dtype=torch.long, device=device)
    categories = {name: {"tokens": 0, "top1": 0, "top5": 0, "top10": 0, "loss": 0.0} for name in category_names}
    positions = {
        f"{low}-{high}": {"tokens": 0, "top1": 0, "top5": 0, "loss": 0.0}
        for low, high in POSITION_BUCKETS
    }
    eos_id = SPECIAL_TOKEN_IDS["<eos>"]
    eos_input_count = 0
    eos_masked_count = 0
    eos_label_mismatch_count = 0
    eos_context_lengths: list[float] = []
    eos_positions = {f"{low}-{high}": 0 for low, high in POSITION_BUCKETS}
    nonfinite_logits = 0
    per_sequence: list[dict[str, Any]] = []
    sequence_cursor = 0
    with torch.inference_mode():
        for batch_index, batch in enumerate(loader):
            if time.perf_counter() - started > timeout_seconds:
                raise EvaluationError("EVALUATION_TIMEOUT", "evaluation profile timeout exceeded")
            ids = batch["input_ids"].to(device)
            labels = batch["labels"].to(device)
            mask = batch["attention_mask"].to(device)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                logits = model(ids, attention_mask=mask).logits[:, :-1, :].float()
            targets = labels[:, 1:]
            valid = targets != -100
            if not bool(valid.any().item()):
                continue
            nonfinite_logits += int((~torch.isfinite(logits[valid])).sum().item())
            losses = functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), targets.reshape(-1), ignore_index=-100, reduction="none").reshape_as(targets)
            total_loss += float(losses[valid].sum().item())
            count = int(valid.sum().item())
            total_tokens += count
            batch_count += 1
            top = torch.topk(logits, 10, dim=-1).indices
            for k in top_hits:
                top_hits[k] += int(((top[..., :k] == targets.unsqueeze(-1)).any(-1) & valid).sum().item())
            top1 = top[..., 0]
            for row in range(ids.shape[0]):
                row_valid = valid[row]
                row_count = int(row_valid.sum().item())
                accuracy = float(((top1[row] == targets[row]) & row_valid).sum().item() / row_count)
                sequence_values.append(accuracy)
                per_sequence.append({"sample_id": hashlib.sha256(f"sequence:{sequence_cursor}".encode()).hexdigest()[:16], "top1_accuracy": accuracy, "target_tokens": row_count})
                sequence_cursor += 1
            valid_categories = category_lookup[targets.clamp_min(0)]
            top5_hit = (top[..., :5] == targets.unsqueeze(-1)).any(-1)
            top10_hit = (top == targets.unsqueeze(-1)).any(-1)
            for category, category_id in category_ids.items():
                selected = valid & (valid_categories == category_id)
                item = categories[category]
                item["tokens"] += int(selected.sum().item())
                item["top1"] += int(((top1 == targets) & selected).sum().item())
                item["top5"] += int((top5_hit & selected).sum().item())
                item["top10"] += int((top10_hit & selected).sum().item())
                item["loss"] += float(losses[selected].sum().item())
            position_index = torch.arange(1, targets.shape[1] + 1, device=device).unsqueeze(0).expand_as(targets)
            for low, high in POSITION_BUCKETS:
                selected = valid & (position_index >= low) & (position_index <= high)
                key = f"{low}-{high}"
                item = positions[key]
                item["tokens"] += int(selected.sum().item())
                item["top1"] += int(((top1 == targets) & selected).sum().item())
                item["top5"] += int((top5_hit & selected).sum().item())
                item["loss"] += float(losses[selected].sum().item())
            eos_inputs = ids[:, 1:] == eos_id
            eos_targets = valid & (targets == eos_id)
            eos_input_count += int(eos_inputs.sum().item())
            eos_masked_count += int((eos_inputs & ~valid).sum().item())
            eos_label_mismatch_count += int((eos_inputs & valid & (targets != eos_id)).sum().item())
            for row, position in eos_targets.nonzero(as_tuple=False).detach().cpu().tolist():
                absolute_position = position + 1
                for low, high in POSITION_BUCKETS:
                    if low <= absolute_position <= high:
                        eos_positions[f"{low}-{high}"] += 1
                        break
                preceding = (ids[row, :absolute_position] == eos_id).nonzero(as_tuple=False)
                previous = int(preceding[-1].item()) if preceding.numel() else -1
                eos_context_lengths.append(float(absolute_position - previous - 1))
    elapsed = time.perf_counter() - started
    if total_tokens == 0:
        raise EvaluationError("EVALUATION_DATASET_EMPTY", "no valid target tokens were evaluated")
    mean_loss = total_loss / total_tokens
    result = {
        **safe_perplexity(mean_loss), "sequences": len(sequence_values), "target_tokens": total_tokens,
        "batches": batch_count, "evaluation_seconds": elapsed, "tokens_per_second": total_tokens / elapsed,
        "top1_accuracy": top_hits[1] / total_tokens, "top5_accuracy": top_hits[5] / total_tokens,
        "top10_accuracy": top_hits[10] / total_tokens, "sequence_top1_distribution": quantiles(sequence_values),
        "token_type_accuracy": {
            key: {
                "tokens": int(item["tokens"]),
                "accuracy": item["top1"] / item["tokens"] if item["tokens"] else None,
                "top1_accuracy": item["top1"] / item["tokens"] if item["tokens"] else None,
                "top5_accuracy": item["top5"] / item["tokens"] if item["tokens"] else None,
                "top10_accuracy": item["top10"] / item["tokens"] if item["tokens"] else None,
                "mean_loss": item["loss"] / item["tokens"] if item["tokens"] else None,
            }
            for key, item in sorted(categories.items())
        },
        "position_bucket_accuracy": {
            key: {
                "tokens": int(item["tokens"]),
                "accuracy": item["top1"] / item["tokens"] if item["tokens"] else None,
                "top1_accuracy": item["top1"] / item["tokens"] if item["tokens"] else None,
                "top5_accuracy": item["top5"] / item["tokens"] if item["tokens"] else None,
                "mean_loss": item["loss"] / item["tokens"] if item["tokens"] else None,
            }
            for key, item in positions.items()
        },
        "eos_diagnostics": {
            "eos_token_id": eos_id,
            "target_tokens": categories["eos"]["tokens"],
            "target_ratio": categories["eos"]["tokens"] / total_tokens,
            "top1_accuracy": categories["eos"]["top1"] / categories["eos"]["tokens"] if categories["eos"]["tokens"] else None,
            "top5_accuracy": categories["eos"]["top5"] / categories["eos"]["tokens"] if categories["eos"]["tokens"] else None,
            "top10_accuracy": categories["eos"]["top10"] / categories["eos"]["tokens"] if categories["eos"]["tokens"] else None,
            "mean_loss": categories["eos"]["loss"] / categories["eos"]["tokens"] if categories["eos"]["tokens"] else None,
            "position_distribution": eos_positions,
            "context_length_distribution": quantiles(eos_context_lengths),
            "input_eos_tokens": eos_input_count,
            "masked_eos_tokens": eos_masked_count,
            "label_mismatch_tokens": eos_label_mismatch_count,
            "packing_boundary_preserved": eos_input_count == categories["eos"]["tokens"] + eos_masked_count and eos_label_mismatch_count == 0,
            "label_masking_applied": eos_masked_count > 0,
            "included_in_loss": categories["eos"]["tokens"] > 0,
        },
        "nan_inf_logits": nonfinite_logits, "nan_inf_loss": not math.isfinite(mean_loss),
    }
    return result, per_sequence


def _rebased_metrics(model: DohaLMTiny, subset: IndexedSubset, device: torch.device, *, use_amp: bool, deadline: float) -> dict[str, Any]:
    total_loss, total_tokens, top1, top5, documents = 0.0, 0, 0, 0, 0
    eos = SPECIAL_TOKEN_IDS["<eos>"]
    collator = CausalLMCollator(context_length=256)
    with torch.inference_mode():
        for sequence_index in range(len(subset)):
            _ensure_deadline(deadline)
            ids = subset[sequence_index]["input_ids"].tolist()
            start = 0
            for position, token in enumerate(ids):
                if token != eos:
                    continue
                segment = ids[start:position + 1]
                start = position + 1
                if len(segment) < 2:
                    continue
                batch = collator([{"input_ids": torch.tensor(segment), "labels": torch.tensor(segment)}])
                input_ids, labels, mask = (batch[key].to(device) for key in ("input_ids", "labels", "attention_mask"))
                with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
                    logits = model(input_ids, attention_mask=mask).logits[:, :-1, :].float()
                targets = labels[:, 1:]
                total_loss += float(functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), targets.reshape(-1), reduction="sum").item())
                count = targets.numel(); total_tokens += count; documents += 1
                choices = torch.topk(logits, 5, dim=-1).indices
                top1 += int((choices[..., 0] == targets).sum().item())
                top5 += int((choices == targets.unsqueeze(-1)).any(-1).sum().item())
    if not total_tokens:
        return {"status": "not_computable", "reason": "no complete EOS-bounded documents in subset"}
    return {"status": "computed", "documents": documents, "target_tokens": total_tokens, "loss": total_loss / total_tokens, "top1_accuracy": top1 / total_tokens, "top5_accuracy": top5 / total_tokens}


def _generation_metrics(model: DohaLMTiny, tokenizer: Any, prompts: list[dict[str, Any]], device: torch.device, *, deadline: float) -> dict[str, Any]:
    byte_ids = {index for index in range(tokenizer.vocab_size) if tokenizer.processor.id_to_piece(index).startswith("<0x")}
    rows = []
    for prompt in prompts:
        _ensure_deadline(deadline)
        encoded = tokenizer.encode(prompt["text"], truncation=True, max_length=240)
        ids = torch.tensor([encoded.ids], dtype=torch.long, device=device)
        limit = min(int(prompt["maximum_generation_length"]), 16)
        generated = model.generate(ids, max_new_tokens=limit, eos_token_id=SPECIAL_TOKEN_IDS["<eos>"])
        new_tokens = generated[0, ids.shape[1]:].detach().cpu().tolist()
        stats = generation_statistics(new_tokens, eos_id=SPECIAL_TOKEN_IDS["<eos>"], unk_id=tokenizer.unk_id, special_ids=set(SPECIAL_TOKEN_IDS.values()), byte_ids=byte_ids)
        stats["maximum_length_reached"] = len(new_tokens) == limit and SPECIAL_TOKEN_IDS["<eos>"] not in new_tokens
        rows.append({"prompt_id_hash": hashlib.sha256(prompt["prompt_id"].encode()).hexdigest()[:16], "category": prompt["category"], "input_tokens": len(encoded.ids), **stats})
    numeric = lambda key: sum(float(row[key]) for row in rows) / len(rows) if rows else 0.0
    def repeated_ngram_rate(row: dict[str, Any], n: int) -> float:
        distinct = float(row[f"distinct_{n}"])
        return 1.0 - distinct
    return {
        "samples": len(rows), "average_generation_length": numeric("length"),
        "eos_rate": numeric("eos_reached"), "maximum_length_rate": numeric("maximum_length_reached"),
        "empty_rate": numeric("empty"), "repetition_rate": numeric("adjacent_repetition_rate"),
        "repeated_bigram_rate": sum(repeated_ngram_rate(row, 2) for row in rows) / len(rows) if rows else 0.0,
        "repeated_trigram_rate": sum(repeated_ngram_rate(row, 3) for row in rows) / len(rows) if rows else 0.0,
        "unique_token_ratio": numeric("unique_token_ratio"),
        "distinct_1": numeric("distinct_1"), "distinct_2": numeric("distinct_2"), "distinct_3": numeric("distinct_3"),
        "degenerate_loop_rate": numeric("degenerate_loop"), "special_token_rate": numeric("special_token_rate"),
        "unk_rate": numeric("unk_rate"), "byte_fallback_rate": numeric("byte_fallback_rate"),
        "rows": rows, "decoded_text_stored": False, "token_ids_stored": False,
    }


def _continuation_metrics(model: DohaLMTiny, subset: IndexedSubset, device: torch.device, *, deadline: float) -> dict[str, Any]:
    rows = []
    for sample_index in range(min(4, len(subset))):
        _ensure_deadline(deadline)
        ids = subset[sample_index]["input_ids"].tolist()
        for prefix_length in (16, 32, 64, 128):
            target = ids[prefix_length:prefix_length + 16]
            if len(target) < 16:
                continue
            prompt = torch.tensor([ids[:prefix_length]], device=device)
            generated = model.generate(prompt, max_new_tokens=16, eos_token_id=SPECIAL_TOKEN_IDS["<eos>"])[0, prefix_length:].cpu().tolist()
            full = torch.tensor([ids[:prefix_length + 16]], device=device)
            with torch.inference_mode():
                logits = model(full).logits[:, prefix_length - 1:prefix_length + 15, :].float()
                expected = torch.tensor([target], device=device)
                teacher_loss = float(functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), expected.reshape(-1)).item())
            adjacent = sum(left == right for left, right in zip(generated, generated[1:]))
            rows.append({
                "sample_id": hashlib.sha256(f"{sample_index}".encode()).hexdigest()[:16],
                "prefix_length": prefix_length, **prefix_metrics(generated, target),
                "teacher_forced_loss": teacher_loss, "eos_reached": SPECIAL_TOKEN_IDS["<eos>"] in generated,
                "repetition_rate": adjacent / max(1, len(generated) - 1),
                "special_token_rate": sum(token in SPECIAL_TOKEN_IDS.values() for token in generated) / max(1, len(generated)),
            })
    return {"probes": len(rows), "rows": rows, "prefix_text_stored": False, "continuation_text_stored": False, "token_ids_stored": False}


def _stability_probe(model: DohaLMTiny, subset: IndexedSubset, device: torch.device, *, sequences: int, use_amp: bool, deadline: float) -> dict[str, Any]:
    _ensure_deadline(deadline)
    count = min(sequences, len(subset))
    records = [subset[index] for index in range(count)]
    batch = CausalLMCollator(context_length=256)(records)
    ids, labels, mask = (batch[key].to(device) for key in ("input_ids", "labels", "attention_mask"))
    def probe(amp: bool) -> tuple[float, float]:
        with torch.inference_mode(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=amp):
            output = model(ids, attention_mask=mask, labels=labels)
        logits = output.logits[:, :-1, :]
        targets = labels[:, 1:]
        valid = targets != -100
        top1 = float(((logits.argmax(dim=-1) == targets) & valid).sum().item() / valid.sum().item())
        return float(output.loss.float().item()), top1
    primary_a, primary_top1_a = probe(use_amp)
    primary_b, primary_top1_b = probe(use_amp)
    fp32, fp32_top1 = probe(False)
    return {
        "sequences": count,
        "deterministic_repeat_equal": primary_a == primary_b and primary_top1_a == primary_top1_b,
        "primary_loss": primary_a, "fp32_loss": fp32, "fp16_fp32_absolute_gap": abs(primary_a - fp32),
        "primary_top1": primary_top1_a, "fp32_top1": fp32_top1,
        "fp16_fp32_top1_absolute_gap": abs(primary_top1_a - fp32_top1),
        "batch_size_tolerance_status": "covered_by_weighted_token_aggregation_tests",
        "exact_fp16_fp32_match_required": False, "configured_tolerance": {"absolute_loss": 0.05, "relative_loss": 0.01},
        "within_tolerance": abs(primary_a - fp32) <= max(0.05, abs(fp32) * 0.01),
        "empty_logits": False, "vocabulary_size": model.config.vocab_size,
        "special_token_contract_valid": sorted(SPECIAL_TOKEN_IDS.values()) == list(range(8)),
    }


def _result_fingerprint_payload(metrics: dict[str, Any], *, schema: str) -> dict[str, Any]:
    """Keep historical Quick fingerprints stable while Full uses the complete v2 metrics."""
    if schema == "evaluation-result-v2":
        return metrics
    perplexity_keys = ("loss", "log_perplexity", "perplexity", "perplexity_overflow", "finite_perplexity")
    generation_keys = (
        "samples", "eos_rate", "maximum_length_rate", "empty_rate", "repetition_rate",
        "distinct_1", "distinct_2", "distinct_3", "rows", "decoded_text_stored", "token_ids_stored",
    )
    stability_keys = (
        "sequences", "deterministic_repeat_equal", "primary_loss", "fp32_loss",
        "fp16_fp32_absolute_gap", "batch_size_tolerance_status", "exact_fp16_fp32_match_required",
        "configured_tolerance", "within_tolerance", "empty_logits", "vocabulary_size",
        "special_token_contract_valid",
    )
    distribution_keys = ("minimum", "p10", "p25", "median", "mean", "p75", "p90", "maximum")
    next_token = metrics["next_token"]
    legacy_categories = {
        key: {"accuracy": item["accuracy"], "tokens": item["tokens"]}
        for key, item in next_token["token_type_accuracy"].items()
    }
    position = metrics["position"]
    legacy_buckets = {
        key: {"accuracy": item["accuracy"], "tokens": item["tokens"]}
        for key, item in position["buckets"].items()
    }
    return {
        "perplexity": {key: metrics["perplexity"][key] for key in perplexity_keys},
        "next_token": {
            "top1_accuracy": next_token["top1_accuracy"],
            "top5_accuracy": next_token["top5_accuracy"],
            "top10_accuracy": next_token["top10_accuracy"],
            "sequence_top1_distribution": {
                key: next_token["sequence_top1_distribution"][key] for key in distribution_keys
            },
            "token_type_accuracy": legacy_categories,
        },
        "position": {
            "packed_top1": position["packed_top1"], "packed_top5": position["packed_top5"],
            "packed_loss": position["packed_loss"], "rebased": position["rebased"],
            "position_gap": position["position_gap"], "buckets": legacy_buckets,
        },
        "generation": {key: metrics["generation"][key] for key in generation_keys},
        "continuation": metrics["continuation"],
        "stability": {key: metrics["stability"][key] for key in stability_keys},
    }


def _quick_full_comparison(
    full_metrics: dict[str, Any],
    full_resource: dict[str, Any],
    quick_result: dict[str, Any],
) -> dict[str, Any]:
    manifest = quick_result["manifest"]
    if manifest.get("artifact_id") != "candidate-a-final" or manifest.get("profile") != "quick":
        raise EvaluationError("QUICK_REFERENCE_INVALID", "Full Evaluation requires Candidate A Final Quick reference")
    quick = quick_result["metrics"]
    quick_resource = quick_result["resource"]
    full_next, quick_next = full_metrics["next_token"], quick["next_token"]
    full_position, quick_position = full_metrics["position"], quick["position"]
    loss_delta = full_metrics["perplexity"]["loss"] - quick["perplexity"]["loss"]
    deltas = {
        "loss_absolute": loss_delta,
        "loss_relative": loss_delta / quick["perplexity"]["loss"],
        "perplexity_ratio": full_metrics["perplexity"]["perplexity"] / quick["perplexity"]["perplexity"],
        "top1": full_next["top1_accuracy"] - quick_next["top1_accuracy"],
        "top5": full_next["top5_accuracy"] - quick_next["top5_accuracy"],
        "top10": full_next["top10_accuracy"] - quick_next["top10_accuracy"],
        "packed_top1": full_position["packed_top1"] - quick_position["packed_top1"],
        "rebased_top1": full_position["rebased"]["top1_accuracy"] - quick_position["rebased"]["top1_accuracy"],
        "position_gap": full_position["position_gap"] - quick_position["position_gap"],
        "evaluation_time_ratio": full_resource["evaluation_seconds"] / quick_resource["evaluation_seconds"],
        "peak_reserved_vram_ratio": (
            full_resource["peak_gpu_reserved_bytes"] / quick_resource["peak_gpu_reserved_bytes"]
            if quick_resource["peak_gpu_reserved_bytes"] else None
        ),
    }
    bucket_deltas = {
        key: full_position["buckets"][key]["top1_accuracy"] - quick_position["buckets"][key]["accuracy"]
        for key in full_position["buckets"]
    }
    category_deltas = {
        key: full_next["token_type_accuracy"][key]["top1_accuracy"] - quick_next["token_type_accuracy"][key]["accuracy"]
        for key in full_next["token_type_accuracy"] if key in quick_next["token_type_accuracy"]
    }
    proposed_thresholds = {
        "loss_absolute": 0.1, "top1_absolute": 0.01, "top5_absolute": 0.015,
        "top10_absolute": 0.02, "position_gap_absolute": 0.01,
    }
    candidate_pass = (
        abs(deltas["loss_absolute"]) <= proposed_thresholds["loss_absolute"]
        and abs(deltas["top1"]) <= proposed_thresholds["top1_absolute"]
        and abs(deltas["top5"]) <= proposed_thresholds["top5_absolute"]
        and abs(deltas["top10"]) <= proposed_thresholds["top10_absolute"]
        and abs(deltas["position_gap"]) <= proposed_thresholds["position_gap_absolute"]
    )
    return {
        "quick_reference_result_fingerprint": manifest["result_fingerprint"],
        "quick_evaluation_id": manifest["evaluation_id"],
        "comparability": "comparable_profile_scope_difference",
        "deltas": deltas,
        "position_bucket_top1_deltas": bucket_deltas,
        "category_top1_deltas": category_deltas,
        "representativeness_status": "insufficient_evidence",
        "policy_status": "proposed_not_approved",
        "proposed_thresholds": proposed_thresholds,
        "candidate_threshold_outcome": "pass" if candidate_pass else "fail",
        "raw_text_stored": False,
        "token_ids_stored": False,
    }


def run_evaluation(
    config: EvaluationConfig,
    registry: ArtifactRegistry,
    artifact_id: str,
    *,
    evaluation_id: str,
    quick_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not evaluation_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in evaluation_id):
        raise EvaluationError("EVALUATION_ID_INVALID", "evaluation ID must be a safe logical name")
    artifact = registry.get(artifact_id)
    inspection = registry.inspect(config, artifact_id, require_eligible=True)
    if inspection["status"] != "eligible":
        raise EvaluationError("ARTIFACT_EVALUATION_BLOCKED", f"artifact validation status is {inspection['status']}")
    if config.device == "cuda" and not torch.cuda.is_available():
        raise EvaluationError("CUDA_REQUIRED", "CUDA evaluation was requested but CUDA is unavailable")
    device = torch.device(config.device)
    use_amp = config.precision == "fp16" and device.type == "cuda"
    if config.deterministic_algorithms:
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        torch.use_deterministic_algorithms(True)
    tokenizer_path = config.external_path(config.tokenizer_model)
    tokenizer_checksum_before = file_checksum(tokenizer_path)
    tokenizer_report = validate_operating_candidate(tokenizer_path.parent)
    tokenizer = DohaTokenizer(tokenizer_path)
    if tokenizer_report["tokenizer_fingerprint"] != artifact.value["tokenizer_fingerprint"]:
        raise EvaluationError("TOKENIZER_FINGERPRINT_MISMATCH", "tokenizer fingerprint does not match artifact")
    dataset_manifest_path = config.external_path(config.dataset_manifest)
    split_manifest_path = config.external_path(config.split_manifest)
    dataset_manifest_checksum_before = file_checksum(dataset_manifest_path)
    split_manifest_checksum_before = file_checksum(split_manifest_path)
    dataset_checksum_before = _validate_dataset_manifests(
        config, tokenizer_report["tokenizer_fingerprint"], artifact.value["pii_fingerprint"],
    )
    dataset = TokenizedJsonlDataset(config.external_path(config.evaluation_dataset), context_length=256, vocab_size=16000)
    if len(dataset) != int(config.dataset_identity["packed_sequences"]):
        raise EvaluationError("EVALUATION_DATASET_MISMATCH", "packed sequence count mismatch")
    indices = deterministic_indices(len(dataset), config.profile.maximum_sequences, seed=config.seed, dataset_fingerprint=config.dataset_identity["evaluation_fingerprint"])
    subset = IndexedSubset(dataset, tuple(indices))
    if config.profile.name == "full" and (
        len(subset) != int(config.dataset_identity["packed_sequences"])
        or tuple(indices) != tuple(range(len(dataset)))
    ):
        raise EvaluationError("FULL_DATASET_INCOMPLETE", "full profile must use every packed sequence in source order")
    loader = DataLoader(subset, batch_size=config.profile.batch_size, shuffle=False, collate_fn=CausalLMCollator(context_length=256), num_workers=0)
    prompts, prompt_fingerprint = _load_prompts(config)
    model, checkpoint_before = _prepare_model(config, artifact, device)
    model_before = _model_digest(model)
    if any(parameter.requires_grad for parameter in model.parameters()) or model.training:
        raise EvaluationError("EVALUATION_ONLY_VIOLATION", "model must be frozen and in eval mode")
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    started_at = _utc_now()
    wall_started = time.perf_counter()
    deadline = wall_started + config.profile.timeout_seconds
    packed, per_sequence = _aggregate_teacher_forced(model, loader, tokenizer, device, use_amp=use_amp, timeout_seconds=config.profile.timeout_seconds)
    if config.profile.name == "full" and packed["target_tokens"] != int(config.dataset_identity["target_tokens"]):
        raise EvaluationError("FULL_TARGET_TOKEN_MISMATCH", "full target token count does not match dataset identity")
    _ensure_deadline(deadline)
    rebased = _rebased_metrics(model, subset, device, use_amp=use_amp, deadline=deadline)
    generation = _generation_metrics(model, tokenizer, prompts, device, deadline=deadline) if config.profile.generation_enabled else {"status": "disabled"}
    continuation = _continuation_metrics(model, subset, device, deadline=deadline) if config.profile.continuation_enabled else {"status": "disabled"}
    stability = _stability_probe(model, subset, device, sequences=config.profile.fp32_comparison_sequences, use_amp=use_amp, deadline=deadline)
    stability.update({"nan_inf_logits": packed["nan_inf_logits"], "nan_inf_loss": packed["nan_inf_loss"], "evaluation_failure_count": 0})
    model_after = _model_digest(model)
    checkpoint_after = None if artifact.is_initial else file_checksum(config.external_path(artifact.value["logical_external_path"]) / "checksums.json")
    tokenizer_checksum_after = file_checksum(tokenizer_path)
    dataset_manifest_checksum_after = file_checksum(dataset_manifest_path)
    split_manifest_checksum_after = file_checksum(split_manifest_path)
    dataset_checksum_after = file_checksum(config.external_path(config.evaluation_dataset))
    unchanged = (
        model_before == model_after and checkpoint_before == checkpoint_after
        and tokenizer_checksum_before == tokenizer_checksum_after
        and dataset_manifest_checksum_before == dataset_manifest_checksum_after
        and split_manifest_checksum_before == split_manifest_checksum_after
        and dataset_checksum_before == dataset_checksum_after
    )
    if not unchanged:
        raise EvaluationError("EVALUATION_MUTATED_ARTIFACT", "model or checkpoint changed during evaluation")
    position_gap = None if rebased.get("status") != "computed" else float(rebased["top1_accuracy"]) - float(packed["top1_accuracy"])
    deterministic_metrics = {
        "perplexity": {key: packed[key] for key in ("loss", "log_perplexity", "perplexity", "perplexity_overflow", "finite_perplexity", "sequences", "target_tokens", "batches")},
        "next_token": {key: packed[key] for key in ("top1_accuracy", "top5_accuracy", "top10_accuracy", "sequence_top1_distribution", "token_type_accuracy")},
        "position": {"packed_top1": packed["top1_accuracy"], "packed_top5": packed["top5_accuracy"], "packed_loss": packed["loss"], "rebased": rebased, "position_gap": position_gap, "buckets": packed["position_bucket_accuracy"], "eos_diagnostics": packed["eos_diagnostics"]},
        "generation": generation, "continuation": continuation, "stability": stability,
    }
    result_fingerprint_schema = "evaluation-result-v2" if config.profile.name == "full" else "evaluation-result-v1"
    result_fingerprint = checksum_value(_result_fingerprint_payload(deterministic_metrics, schema=result_fingerprint_schema))
    total_evaluation_seconds = time.perf_counter() - wall_started
    resource = {
        "evaluation_seconds": total_evaluation_seconds,
        "teacher_forced_seconds": packed["evaluation_seconds"],
        "tokens_per_second": packed["target_tokens"] / total_evaluation_seconds,
        "teacher_forced_tokens_per_second": packed["tokens_per_second"],
        "peak_gpu_allocated_bytes": torch.cuda.max_memory_allocated(device) if device.type == "cuda" else 0,
        "peak_gpu_reserved_bytes": torch.cuda.max_memory_reserved(device) if device.type == "cuda" else 0,
        "cpu_working_set_bytes": _working_set_bytes(),
    }
    _ensure_deadline(deadline)
    if resource["peak_gpu_reserved_bytes"] > config.resource_limits["maximum_reserved_vram_bytes"]:
        raise EvaluationError("EVALUATION_VRAM_LIMIT", "evaluation exceeded reserved VRAM limit")
    if (
        resource["cpu_working_set_bytes"] is not None
        and resource["cpu_working_set_bytes"] > config.resource_limits["maximum_cpu_working_set_bytes"]
    ):
        raise EvaluationError("EVALUATION_CPU_MEMORY_LIMIT", "evaluation exceeded CPU working-set limit")
    quick_full = None
    if config.profile.name == "full":
        if quick_reference is None:
            raise EvaluationError("QUICK_REFERENCE_REQUIRED", "Full Evaluation requires an immutable Quick reference")
        quick_manifest = quick_reference["manifest"]
        if (
            quick_manifest["dataset_identity"]["evaluation_fingerprint"] != config.dataset_identity["evaluation_fingerprint"]
            or quick_manifest["tokenizer_fingerprint"] != tokenizer_report["tokenizer_fingerprint"]
            or quick_manifest["prompt_set_fingerprint"] != prompt_fingerprint
        ):
            raise EvaluationError("QUICK_REFERENCE_INCOMPARABLE", "Quick reference identity does not match Full Evaluation")
        quick_full = _quick_full_comparison(deterministic_metrics, resource, quick_reference)
    manifest = {
        "schema_version": "1.0", "evaluation_id": evaluation_id, "profile": config.profile.name,
        "artifact_id": artifact_id, "artifact_identity_fingerprint": artifact.identity_fingerprint,
        "checkpoint_identity": inspection.get("checkpoint"), "dataset_identity": config.dataset_identity,
        "source_lineage_fingerprint": artifact.value["source_lineage_fingerprint"],
        "pii_fingerprint": artifact.value["pii_fingerprint"],
        "split_fingerprint": artifact.value["split_fingerprint"],
        "evaluation_subset_identity": subset.manifest, "tokenizer_fingerprint": tokenizer_report["tokenizer_fingerprint"],
        "model_fingerprint": artifact.value["model_fingerprint"], "config_fingerprint": config.fingerprint,
        "profile_fingerprint": config.profile_fingerprint,
        "prompt_set_fingerprint": prompt_fingerprint, "environment": collect_environment(repository_root()),
        "precision": "fp16" if use_amp else "fp32", "seed": config.seed, "started_at": started_at,
        "completed_at": _utc_now(), "metrics_enabled": config.metrics, "generation_enabled": config.profile.generation_enabled,
        "text_storage": False, "token_id_storage": False,
        "output_logical_path": f"{config.output_root}/{artifact_id}/{evaluation_id}",
        "status": "completed", "failure_code": None, "result_fingerprint": result_fingerprint,
        "result_fingerprint_schema": result_fingerprint_schema,
        "quick_reference_fingerprint": None if quick_full is None else quick_full["quick_reference_result_fingerprint"],
        "quick_full_comparability": None if quick_full is None else quick_full["comparability"],
        "checkpoint_checksum_before": checkpoint_before, "checkpoint_checksum_after": checkpoint_after,
        "tokenizer_checksum_before": tokenizer_checksum_before, "tokenizer_checksum_after": tokenizer_checksum_after,
        "dataset_manifest_checksum_before": dataset_manifest_checksum_before,
        "dataset_manifest_checksum_after": dataset_manifest_checksum_after,
        "split_manifest_checksum_before": split_manifest_checksum_before,
        "split_manifest_checksum_after": split_manifest_checksum_after,
        "evaluation_dataset_checksum_before": dataset_checksum_before,
        "evaluation_dataset_checksum_after": dataset_checksum_after,
        "model_state_fingerprint_before": model_before, "model_state_fingerprint_after": model_after,
        "training_operations": {"optimizer_created": False, "scheduler_created": False, "backward_called": False, "gradients_enabled": False},
    }
    summary = {"artifact_id": artifact_id, "evaluation_id": evaluation_id, "profile": config.profile.name, "status": "completed", "result_fingerprint": result_fingerprint, "loss": packed["loss"], "perplexity": packed["perplexity"], "top1_accuracy": packed["top1_accuracy"], "top5_accuracy": packed["top5_accuracy"], "position_gap": position_gap, "model_checkpoint_unchanged": unchanged}
    output_files = {
        "manifests/execution.json": manifest, "manifests/subset.json": subset.manifest,
        "metrics/aggregate.json": deterministic_metrics, "metrics/per-sequence.json": {"rows": per_sequence, "raw_text_stored": False, "token_ids_stored": False},
        "metrics/resources.json": resource, "generation/statistics.json": generation, "reports/summary.json": summary,
        "logs/execution.json": {"status": "completed", "automatic_retry_count": 0, "batches": packed["batches"]},
        "failures/status.json": {"failure_count": 0, "failures": []},
    }
    if quick_full is not None:
        output_files["reports/full-vs-quick.json"] = quick_full
    _publish(config.external_path(f"{config.output_root}/{artifact_id}/{evaluation_id}"), output_files)
    return summary
