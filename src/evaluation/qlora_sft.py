"""Read-only, deterministic evaluation for the DohaLM v0.1 QLoRA adapter."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import time
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.data.checksums import canonical_json_bytes, checksum_value, file_checksum
from src.data.processing.aihub_71748_reader import (
    discover_sft_sources,
    iter_source_records,
)
from src.evaluation.metrics import safe_perplexity
from src.training.qlora_training import (
    DynamicSFTCollator,
    load_tokenizer_and_model,
    release_cuda,
)

EXPECTED_MODELS = ("base", "checkpoint-1750", "checkpoint-1947", "final-adapter")
EXPECTED_CONFIG_KEYS = {
    "schema_version", "status", "evaluation_id", "git_head", "training_run_id",
    "model", "dataset", "evaluation", "generation", "privacy", "execution",
}
PII_PATTERNS = (
    re.compile(r"(?<!\d)01[016789][ -]?\d{3,4}[ -]?\d{4}(?!\d)"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<!\d)\d{6}[ -]?[1-4]\d{6}(?!\d)"),
)


class QLoRAEvaluationError(RuntimeError):
    """Fail-closed evaluation error with a stable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PromptRecord:
    sample_hash: str
    kind: str
    category: str
    prompt: str
    reference: str
    length_bucket: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _read_yaml(path: str | Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise QLoRAEvaluationError("EVALUATION_CONFIG_INVALID") from None
    if not isinstance(value, dict):
        raise QLoRAEvaluationError("EVALUATION_CONFIG_INVALID")
    return value


def load_evaluation_config(path: str | Path) -> dict[str, Any]:
    value = _read_yaml(path)
    if set(value) != EXPECTED_CONFIG_KEYS or value.get("schema_version") != 1:
        raise QLoRAEvaluationError("EVALUATION_CONFIG_INVALID")
    model = value.get("model")
    dataset = value.get("dataset")
    evaluation = value.get("evaluation")
    generation = value.get("generation")
    privacy = value.get("privacy")
    execution = value.get("execution")
    if not all(isinstance(item, Mapping) for item in (model, dataset, evaluation, generation, privacy, execution)):
        raise QLoRAEvaluationError("EVALUATION_CONFIG_INVALID")
    assert isinstance(model, Mapping)
    assert isinstance(dataset, Mapping)
    assert isinstance(evaluation, Mapping)
    assert isinstance(generation, Mapping)
    assert isinstance(privacy, Mapping)
    assert isinstance(execution, Mapping)
    if (
        value.get("status") != "approved_for_evaluation"
        or value.get("git_head") != "runtime_required"
        or model.get("base_model") != "Qwen/Qwen2.5-1.5B-Instruct"
        or model.get("revision") != "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
        or dataset.get("validation_rows") != 1287
        or dataset.get("assistant_only_loss") is not True
        or evaluation.get("batch_size") != 1
        or evaluation.get("pad_to_multiple_of") != 8
        or evaluation.get("ignore_index") != -100
        or evaluation.get("precision") != "bfloat16"
        or evaluation.get("deterministic_repeats") != 2
        or evaluation.get("comparison_batches") != 10
        or generation.get("synthetic_count") != 30
        or generation.get("held_out_count") != 50
        or generation.get("expected_categories") != 10
        or generation.get("do_sample") is not False
        or generation.get("max_new_tokens") != 256
        or privacy.get("raw_text_storage") is not False
        or privacy.get("token_id_storage") is not False
        or privacy.get("record_id_storage") is not False
        or any(execution.get(key) is not False for key in (
            "training_allowed", "optimizer_allowed", "adapter_write_allowed", "overwrite_allowed",
        ))
    ):
        raise QLoRAEvaluationError("EVALUATION_CONFIG_INVALID")
    return value


def verify_checksum_manifest(root: str | Path) -> dict[str, str]:
    directory = Path(root)
    manifest = directory / "checksums.sha256"
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise QLoRAEvaluationError("CHECKSUM_MANIFEST_INVALID") from None
    result: dict[str, str] = {}
    for line in lines:
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise QLoRAEvaluationError("CHECKSUM_MANIFEST_INVALID")
        relative = parts[1].lstrip("*").replace("\\", "/")
        candidate = (directory / relative).resolve()
        try:
            candidate.relative_to(directory.resolve())
        except ValueError:
            raise QLoRAEvaluationError("CHECKSUM_PATH_INVALID") from None
        if not candidate.is_file() or file_checksum(candidate).removeprefix("sha256:") != parts[0]:
            raise QLoRAEvaluationError("CHECKSUM_MISMATCH")
        result[relative] = parts[0]
    if not result:
        raise QLoRAEvaluationError("CHECKSUM_MANIFEST_INVALID")
    return result


def verify_training_artifacts(training_root: str | Path, config: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(training_root)
    expected = {"checkpoint-1750", "checkpoint-1947", "final-adapter"}
    if not root.is_dir() or any(not (root / name).is_dir() for name in expected):
        raise QLoRAEvaluationError("TRAINING_ARTIFACT_MISSING")
    root_checksums = verify_checksum_manifest(root)
    adapter_checksums = verify_checksum_manifest(root / "final-adapter")
    result = _read_yaml(root / "training-result.yaml")
    model = config["model"]
    dataset = config["dataset"]
    if (
        result.get("status") != "completed"
        or result.get("run_id") != config.get("training_run_id")
        or result.get("base_revision") != model.get("revision")
        or result.get("adapter_fingerprint") != model.get("adapter_fingerprint")
        or result.get("dataset_fingerprint") != dataset.get("fingerprint")
        or result.get("tokenizer_fingerprint") != dataset.get("tokenizer_fingerprint")
        or result.get("tokenization_run") != dataset.get("tokenization_run_id")
        or result.get("source_processing_run") != dataset.get("processing_run_id")
        or result.get("training_config_fingerprint") != file_checksum(root / "final-adapter" / "training-config.yaml").removeprefix("sha256:")
        or result.get("source_dataset_modified") is not False
        or result.get("tokenization_modified") is not False
    ):
        raise QLoRAEvaluationError("TRAINING_LINEAGE_MISMATCH")
    return {
        "root_checksum_count": len(root_checksums),
        "final_adapter_checksum_count": len(adapter_checksums),
        "training_result_checksum": file_checksum(root / "training-result.yaml"),
        "training_config_fingerprint": result["training_config_fingerprint"],
        "trainer_final_eval_loss": result["eval_metrics"]["eval_loss"],
        "trainer_best_eval_loss": result["best_eval_loss"],
        "reload_validation_loss": result["final_adapter"]["validation_loss"],
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                value = json.loads(line)
                if not isinstance(value, dict) or set(value) != {"instruction", "input", "output", "system"}:
                    raise QLoRAEvaluationError("PROCESSED_SCHEMA_MISMATCH")
                if not isinstance(value["instruction"], str) or not isinstance(value["output"], str):
                    raise QLoRAEvaluationError("PROCESSED_SCHEMA_MISMATCH")
                records.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise QLoRAEvaluationError("PROCESSED_DATASET_INVALID") from None
    return records


def _raw_validation_categories(raw_root: Path) -> dict[str, str]:
    sources = [source for source in discover_sft_sources(raw_root) if source.split == "validation"]
    data: dict[str, Any] = {}
    labels: dict[str, Any] = {}
    for source in sources:
        destination = data if source.component == "sftdata" else labels
        for record in iter_source_records(source):
            if record.data_id in destination:
                raise QLoRAEvaluationError("RAW_METADATA_DUPLICATE")
            destination[record.data_id] = record
    if not data or set(data) != set(labels):
        raise QLoRAEvaluationError("RAW_METADATA_JOIN_MISMATCH")
    result: dict[str, str] = {}
    for source_id, record in data.items():
        label = labels[source_id]
        if record.question != label.question or label.answer_contents is None or record.data_category is None:
            raise QLoRAEvaluationError("RAW_METADATA_JOIN_MISMATCH")
        safe = {"instruction": record.question, "input": None, "output": label.answer_contents, "system": None}
        digest = _canonical_hash(safe)
        if digest in result and result[digest] != record.data_category:
            raise QLoRAEvaluationError("RAW_METADATA_HASH_COLLISION")
        result[digest] = record.data_category
    return result


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _length_boundaries(lengths: Sequence[int]) -> tuple[int, int, int]:
    ordered = sorted(lengths)
    if not ordered:
        raise QLoRAEvaluationError("EVALUATION_DATASET_EMPTY")
    def percentile(fraction: float) -> int:
        return ordered[round((len(ordered) - 1) * fraction)]
    return percentile(.33), percentile(.66), percentile(.95)


def _length_bucket(length: int, boundaries: tuple[int, int, int]) -> str:
    short, medium, p95 = boundaries
    if length >= p95:
        return "p95_or_above"
    if length <= short:
        return "short"
    if length <= medium:
        return "medium"
    return "long"


def load_prompt_records(
    *, processed_root: str | Path, raw_root: str | Path, prompt_path: str | Path,
    expected_validation_rows: int = 1287,
) -> tuple[list[PromptRecord], dict[str, Any], set[str], list[str]]:
    processed = Path(processed_root)
    validation = _read_jsonl(processed / "validation.jsonl")
    train = _read_jsonl(processed / "train.jsonl")
    if len(validation) != expected_validation_rows:
        raise QLoRAEvaluationError("VALIDATION_ROW_COUNT_MISMATCH")
    category_by_hash = _raw_validation_categories(Path(raw_root))
    train_hashes = {_canonical_hash(record) for record in train}
    output_hashes = {_canonical_hash(_normalized_text(str(record["output"]))) for record in train}
    categorized: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    validation_categories: list[str] = []
    for record in validation:
        digest = _canonical_hash(record)
        category = category_by_hash.get(digest)
        if category is None:
            raise QLoRAEvaluationError("CATEGORY_LINEAGE_MISMATCH")
        if digest in train_hashes:
            raise QLoRAEvaluationError("TRAIN_VALIDATION_EXACT_OVERLAP")
        categorized[category].append((digest, record))
        validation_categories.append(category)
    if len(categorized) != 10 or any(len(items) < 5 for items in categorized.values()):
        raise QLoRAEvaluationError("CATEGORY_BALANCE_UNAVAILABLE")
    lengths = [len(str(record["output"])) for record in validation]
    boundaries = _length_boundaries(lengths)
    prompts: list[PromptRecord] = []
    for category in sorted(categorized):
        for digest, record in sorted(categorized[category], key=lambda item: item[0])[:5]:
            prompts.append(PromptRecord(
                sample_hash=digest, kind="held_out_validation", category=category,
                prompt=str(record["instruction"]), reference=str(record["output"]),
                length_bucket=_length_bucket(len(str(record["output"])), boundaries),
            ))
    synthetic = _read_yaml(prompt_path)
    values = synthetic.get("prompts")
    if synthetic.get("schema_version") != 1 or not isinstance(values, list) or len(values) != 30:
        raise QLoRAEvaluationError("SYNTHETIC_PROMPT_SET_INVALID")
    seen_ids: set[str] = set()
    for item in values:
        if not isinstance(item, dict) or set(item) != {"id", "category", "prompt", "reference"}:
            raise QLoRAEvaluationError("SYNTHETIC_PROMPT_SET_INVALID")
        if not all(isinstance(item[key], str) and item[key].strip() for key in item):
            raise QLoRAEvaluationError("SYNTHETIC_PROMPT_SET_INVALID")
        if item["id"] in seen_ids:
            raise QLoRAEvaluationError("SYNTHETIC_PROMPT_SET_INVALID")
        seen_ids.add(item["id"])
        prompts.append(PromptRecord(
            sample_hash=_canonical_hash({"id": item["id"], "prompt": item["prompt"], "reference": item["reference"]}),
            kind="synthetic", category=item["category"], prompt=item["prompt"],
            reference=item["reference"], length_bucket=_length_bucket(len(item["reference"]), boundaries),
        ))
    identity = {
        "validation_rows": len(validation),
        "train_rows": len(train),
        "category_counts": {category: len(items) for category, items in sorted(categorized.items())},
        "selected_held_out": 50,
        "selected_synthetic": 30,
        "training_exact_overlap": False,
        "row_hash_list_fingerprint": checksum_value([record.sample_hash for record in prompts]),
        "prompt_set_fingerprint": checksum_value([
            {"sample_hash": record.sample_hash, "kind": record.kind, "category": record.category}
            for record in prompts
        ]),
        "length_boundaries_characters": {"short_max": boundaries[0], "medium_max": boundaries[1], "p95": boundaries[2]},
    }
    return prompts, identity, output_hashes, validation_categories


def tensor_checksum(tensor: Any) -> str:
    value = tensor.detach().contiguous().view(-1).view(__import__("torch").uint8).cpu().numpy().tobytes()
    return hashlib.sha256(value).hexdigest()


def batch_identity(batch: Mapping[str, Any]) -> dict[str, Any]:
    labels = batch["labels"]
    attention = batch["attention_mask"]
    return {
        "input_ids_checksum": tensor_checksum(batch["input_ids"]),
        "attention_mask_checksum": tensor_checksum(attention),
        "labels_checksum": tensor_checksum(labels),
        "sequence_length": int(batch["input_ids"].shape[1]),
        "attention_tokens": int(attention.sum().item()),
        "valid_label_tokens": int((labels != -100).sum().item()),
    }


def _parameter_digest(model: Any, *, include_lora: bool) -> str:
    digest = hashlib.sha256()
    matched = 0
    for name, parameter in sorted(model.named_parameters(), key=lambda item: item[0]):
        is_lora = "lora_" in name
        if is_lora != include_lora:
            continue
        matched += 1
        digest.update(name.encode("utf-8"))
        digest.update(str(tuple(parameter.shape)).encode("ascii"))
        digest.update(str(parameter.dtype).encode("ascii"))
        digest.update(parameter.detach().contiguous().view(-1).view(__import__("torch").uint8).cpu().numpy().tobytes())
    if matched == 0 and include_lora:
        raise QLoRAEvaluationError("ADAPTER_NOT_ACTIVE")
    return digest.hexdigest()


def model_parameter_checksums(model: Any) -> dict[str, str | None]:
    has_lora = any("lora_" in name for name, _ in model.named_parameters())
    return {
        "base_parameter_checksum": _parameter_digest(model, include_lora=False),
        "lora_parameter_checksum": _parameter_digest(model, include_lora=True) if has_lora else None,
    }


def model_mode_report(model: Any) -> dict[str, Any]:
    modules = list(model.modules())
    decoder_layers = [module for module in modules if module.__class__.__name__ == "Qwen2DecoderLayer"]
    dropouts = [module for module in modules if module.__class__.__name__.casefold().endswith("dropout")]
    lora_dropouts = [module for name, module in model.named_modules() if "lora_dropout" in name]
    active_value = getattr(model, "active_adapters", [])
    if callable(active_value):
        try:
            active_value = active_value()
        except ValueError:
            if hasattr(model, "peft_config"):
                raise QLoRAEvaluationError("ADAPTER_STATE_INVALID") from None
            active_value = []
    if isinstance(active_value, str):
        active = [active_value]
    elif isinstance(active_value, Sequence):
        active = list(active_value)
    else:
        raise QLoRAEvaluationError("ADAPTER_STATE_INVALID")
    lora_parameters = [name for name, _ in model.named_parameters() if "lora_" in name]
    report = {
        "top_level_training": bool(model.training),
        "peft_training": bool(model.training) if hasattr(model, "peft_config") else None,
        "decoder_layers": len(decoder_layers),
        "decoder_layers_training": sum(bool(layer.training) for layer in decoder_layers),
        "dropout_modules": len(dropouts),
        "dropout_modules_training": sum(bool(module.training) for module in dropouts),
        "lora_dropout_modules": len(lora_dropouts),
        "lora_dropout_training": sum(bool(module.training) for module in lora_dropouts),
        "gradient_checkpointing": bool(getattr(model, "is_gradient_checkpointing", False)),
        "use_cache": bool(getattr(model.config, "use_cache", False)),
        "active_adapters": active,
        "lora_parameter_tensors": len(lora_parameters),
    }
    if (
        report["top_level_training"]
        or report["decoder_layers_training"]
        or report["dropout_modules_training"]
        or report["lora_dropout_training"]
    ):
        raise QLoRAEvaluationError("MODEL_MODE_MISMATCH")
    return report


def load_model_for_evaluation(
    *, config: Mapping[str, Any], cache_dir: str | Path, adapter_root: str | Path | None,
) -> tuple[Any, Any, dict[str, Any]]:
    import torch
    from peft import PeftModel

    tokenizer, base = load_tokenizer_and_model(config, cache_dir=cache_dir)
    model = base if adapter_root is None else PeftModel.from_pretrained(
        base, adapter_root, is_trainable=False,
    )
    if hasattr(model, "gradient_checkpointing_disable"):
        model.gradient_checkpointing_disable()
    model.config.use_cache = True
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    report = model_mode_report(model)
    report.update(model_parameter_checksums(model))
    report["adapter_loaded"] = adapter_root is not None
    report["adapter_enabled"] = bool(report["active_adapters"]) if adapter_root is not None else False
    if adapter_root is not None and not report["adapter_enabled"]:
        raise QLoRAEvaluationError("ADAPTER_NOT_ACTIVE")
    if any(parameter.requires_grad for parameter in model.parameters()):
        raise QLoRAEvaluationError("EVALUATION_ONLY_VIOLATION")
    torch.cuda.reset_peak_memory_stats()
    return tokenizer, model, report


def _model_device(model: Any) -> Any:
    import torch
    try:
        return next(model.parameters()).device
    except StopIteration:
        return torch.device("cpu")


def _move_batch(batch: Mapping[str, Any], device: Any) -> dict[str, Any]:
    return {key: value.to(device, non_blocking=device.type == "cuda") for key, value in batch.items()}


def evaluate_loss(
    model: Any, dataset: Any, collator: DynamicSFTCollator,
    *, categories: Sequence[str], comparison_batches: int,
) -> dict[str, Any]:
    import torch
    from torch.nn import functional

    if len(dataset) != len(categories):
        raise QLoRAEvaluationError("CATEGORY_ROW_COUNT_MISMATCH")
    device = _model_device(model)
    label_lengths = [sum(int(token) != -100 for token in dataset[index]["labels"]) for index in range(len(dataset))]
    boundaries = _length_boundaries(label_lengths)
    total_nll = 0.0
    total_tokens = 0
    batch_losses: list[float] = []
    batch_details: list[dict[str, Any]] = []
    category_values: dict[str, dict[str, float]] = defaultdict(lambda: {"nll": 0.0, "tokens": 0.0, "batch_loss": 0.0, "rows": 0.0})
    length_values: dict[str, dict[str, float]] = defaultdict(lambda: {"nll": 0.0, "tokens": 0.0, "batch_loss": 0.0, "rows": 0.0})
    first_logits_checksum: str | None = None
    reload_style_first_record_loss: float | None = None
    started = time.perf_counter()
    with torch.inference_mode():
        for index in range(len(dataset)):
            cpu_batch = collator([dataset[index]])
            identity = batch_identity(cpu_batch)
            batch = _move_batch(cpu_batch, device)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                output = model(**batch)
            logits = output.logits[:, :-1, :].float()
            targets = batch["labels"][:, 1:]
            valid = targets != -100
            losses = functional.cross_entropy(
                logits.reshape(-1, logits.shape[-1]), targets.reshape(-1),
                ignore_index=-100, reduction="none",
            ).reshape_as(targets)
            if not bool(valid.any().item()) or output.loss is None or not torch.isfinite(output.loss):
                raise QLoRAEvaluationError("NONFINITE_EVALUATION_LOSS")
            nll = float(losses[valid].sum().item())
            count = int(valid.sum().item())
            batch_loss = float(output.loss.float().item())
            total_nll += nll
            total_tokens += count
            batch_losses.append(batch_loss)
            category = categories[index]
            bucket = _length_bucket(label_lengths[index], boundaries)
            for target in (category_values[category], length_values[bucket]):
                target["nll"] += nll
                target["tokens"] += count
                target["batch_loss"] += batch_loss
                target["rows"] += 1
            if index < comparison_batches:
                detail = {**identity, "batch_index": index, "loss": batch_loss,
                          "logit_shape": list(output.logits.shape), "finite": True}
                batch_details.append(detail)
            if index == 0:
                first_logits_checksum = tensor_checksum(logits)
                reload_output = model(**batch)
                if reload_output.loss is None or not torch.isfinite(reload_output.loss):
                    raise QLoRAEvaluationError("NONFINITE_EVALUATION_LOSS")
                reload_style_first_record_loss = float(reload_output.loss.float().item())
    token_loss = total_nll / total_tokens
    batch_mean = sum(batch_losses) / len(batch_losses)
    def aggregate(values: Mapping[str, Mapping[str, float]]) -> dict[str, Any]:
        return {
            key: {
                "rows": int(value["rows"]), "valid_label_tokens": int(value["tokens"]),
                "token_weighted_loss": value["nll"] / value["tokens"],
                "batch_mean_loss": value["batch_loss"] / value["rows"],
            }
            for key, value in sorted(values.items())
        }
    return {
        "rows": len(dataset), "batches": len(batch_losses), "valid_label_tokens": total_tokens,
        "token_weighted_loss": token_loss, "batch_mean_loss": batch_mean,
        "perplexity": safe_perplexity(token_loss)["perplexity"],
        "first_record_loss": batch_losses[0], "comparison_batches": batch_details,
        "reload_style_first_record_loss": reload_style_first_record_loss,
        "first_logits_checksum": first_logits_checksum,
        "category_metrics": aggregate(category_values), "length_metrics": aggregate(length_values),
        "length_boundaries_tokens": {"short_max": boundaries[0], "medium_max": boundaries[1], "p95": boundaries[2]},
        "elapsed_seconds": time.perf_counter() - started,
    }


def _character_f1(predicted: str, expected: str) -> float:
    left = Counter(_normalized_text(predicted).replace(" ", ""))
    right = Counter(_normalized_text(expected).replace(" ", ""))
    overlap = sum((left & right).values())
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    precision = overlap / sum(left.values())
    recall = overlap / sum(right.values())
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def _rouge_l(predicted: str, expected: str) -> float:
    left = list(_normalized_text(predicted).replace(" ", ""))
    right = list(_normalized_text(expected).replace(" ", ""))
    if not left or not right:
        return float(not left and not right)
    previous = [0] * (len(right) + 1)
    for character in left:
        current = [0]
        for index, target in enumerate(right, 1):
            current.append(previous[index - 1] + 1 if character == target else max(previous[index], current[-1]))
        previous = current
    lcs = previous[-1]
    precision = lcs / len(left)
    recall = lcs / len(right)
    return 2 * precision * recall / (precision + recall)


def _repetition(tokens: Sequence[int]) -> bool:
    grams = [tuple(tokens[index:index + 4]) for index in range(max(0, len(tokens) - 3))]
    return any(count >= 3 for count in Counter(grams).values())


def evaluate_generation(
    model: Any, tokenizer: Any, prompts: Sequence[PromptRecord], *,
    max_new_tokens: int, repetition_penalty: float, train_output_hashes: set[str],
) -> dict[str, Any]:
    import torch

    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    device = _model_device(model)
    special_tokens = [token for token in tokenizer.all_special_tokens if token]
    for record in prompts:
        ids = tokenizer.apply_chat_template(
            [{"role": "user", "content": record.prompt}], tokenize=True,
            add_generation_prompt=True, return_tensors="pt",
        ).to(device)
        with torch.inference_mode(), torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
            generated = model.generate(
                ids, do_sample=False, max_new_tokens=max_new_tokens,
                repetition_penalty=repetition_penalty,
                pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id,
            )
        tokens = generated[0, ids.shape[1]:].tolist()
        text = tokenizer.decode(tokens, skip_special_tokens=True).strip()
        raw = tokenizer.decode(tokens, skip_special_tokens=False)
        normalized = _normalized_text(text)
        reference = _normalized_text(record.reference)
        predicted_tokens = set(tokenizer(text, add_special_tokens=False)["input_ids"])
        reference_tokens = set(tokenizer(record.reference, add_special_tokens=False)["input_ids"])
        token_overlap = len(predicted_tokens & reference_tokens) / len(reference_tokens) if reference_tokens else 0.0
        korean = sum("가" <= char <= "힣" for char in text)
        visible = sum(not char.isspace() for char in text)
        rows.append({
            "sample_hash": record.sample_hash, "kind": record.kind, "category": record.category,
            "length_bucket": record.length_bucket, "exact_match": normalized == reference,
            "character_f1": _character_f1(text, record.reference), "rouge_l": _rouge_l(text, record.reference),
            "reference_token_overlap": token_overlap, "empty": not bool(normalized),
            "korean_ratio": korean / visible if visible else 0.0,
            "special_token_exposure": any(token in raw.removesuffix(tokenizer.eos_token or "") for token in special_tokens),
            "prompt_echo": bool(normalized and _normalized_text(record.prompt) in normalized),
            "repetition": _repetition(tokens), "maximum_length_reached": len(tokens) == max_new_tokens,
            "eos_terminated": bool(tokens and tokens[-1] == tokenizer.eos_token_id),
            "pii_like": any(pattern.search(text) for pattern in PII_PATTERNS),
            "memorization_suspicion": _canonical_hash(normalized) in train_output_hashes,
            "output_token_count": len(tokens), "output_hash": _canonical_hash(normalized),
        })
    def summary(selected: Iterable[dict[str, Any]]) -> dict[str, Any]:
        values = list(selected)
        count = len(values)
        return {
            "samples": count,
            "exact_match": sum(row["exact_match"] for row in values) / count,
            "character_f1": sum(row["character_f1"] for row in values) / count,
            "rouge_l": sum(row["rouge_l"] for row in values) / count,
            "reference_token_overlap": sum(row["reference_token_overlap"] for row in values) / count,
            "empty": sum(row["empty"] for row in values),
            "repetition": sum(row["repetition"] for row in values),
            "special_token_exposure": sum(row["special_token_exposure"] for row in values),
            "prompt_echo": sum(row["prompt_echo"] for row in values),
            "maximum_length_reached": sum(row["maximum_length_reached"] for row in values),
            "eos_terminated": sum(row["eos_terminated"] for row in values),
            "pii_like": sum(row["pii_like"] for row in values),
            "memorization_suspicion": sum(row["memorization_suspicion"] for row in values),
        }
    return {
        "overall": summary(rows),
        "by_kind": {kind: summary(row for row in rows if row["kind"] == kind) for kind in sorted({row["kind"] for row in rows})},
        "by_category": {category: summary(row for row in rows if row["category"] == category) for category in sorted({row["category"] for row in rows})},
        "by_length": {bucket: summary(row for row in rows if row["length_bucket"] == bucket) for bucket in sorted({row["length_bucket"] for row in rows})},
        "rows": rows, "elapsed_seconds": time.perf_counter() - started,
        "raw_text_stored": False, "token_ids_stored": False,
    }


def deterministic_metric_fingerprint(loss: Mapping[str, Any], generation: Mapping[str, Any]) -> str:
    loss_keys = {key: value for key, value in loss.items() if key != "elapsed_seconds"}
    generation_keys = {key: value for key, value in generation.items() if key != "elapsed_seconds"}
    return checksum_value({"loss": loss_keys, "generation": generation_keys})


def aggregate_generation(generation: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in generation.items() if key != "rows"}


def environment_snapshot() -> dict[str, Any]:
    import bitsandbytes
    import datasets
    import peft
    import torch
    import transformers

    return {
        "captured_at": _utc_now(), "python": platform.python_version(),
        "platform": platform.platform(), "torch": torch.__version__,
        "transformers": transformers.__version__, "peft": peft.__version__,
        "datasets": datasets.__version__, "bitsandbytes": bitsandbytes.__version__,
        "cuda_runtime": torch.version.cuda, "cuda_available": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


def write_evaluation_artifact(
    *, output_root: str | Path, evaluation_id: str, files: Mapping[str, Any],
) -> Path:
    root = Path(output_root)
    final = root / evaluation_id
    staging = root / f"{evaluation_id}.staging"
    if final.exists() or staging.exists():
        raise QLoRAEvaluationError("EVALUATION_OUTPUT_CONFLICT")
    root.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        for name, value in files.items():
            path = staging / name
            if name.endswith((".yaml", ".yml")):
                payload = yaml.safe_dump(value, allow_unicode=True, sort_keys=False).encode("utf-8")
            else:
                payload = canonical_json_bytes(value)
            with path.open("wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        checksums = []
        for path in sorted(staging.iterdir(), key=lambda item: item.name):
            if path.name == "checksums.sha256":
                continue
            checksums.append(f"{file_checksum(path).removeprefix('sha256:')}  {path.name}")
        checksum_path = staging / "checksums.sha256"
        with checksum_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(checksums) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        verify_checksum_manifest(staging)
        os.replace(staging, final)
        if os.name != "nt":
            directory_fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        verify_checksum_manifest(final)
        return final
    except Exception:
        if staging.exists():
            failed = root / f"{evaluation_id}.failed"
            if not failed.exists():
                os.replace(staging, failed)
        raise


def release_model(model: Any, tokenizer: Any) -> None:
    del model, tokenizer
    release_cuda()
    import torch
    torch.cuda.empty_cache()
