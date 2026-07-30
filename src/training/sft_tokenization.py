"""Deterministic assistant-only SFT tokenization without model loading."""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

IGNORE_INDEX = -100
OUTPUT_FIELDS = frozenset({"instruction", "input", "output", "system"})
TOKEN_FIELDS = frozenset({"input_ids", "attention_mask", "labels"})


class SFTTokenizationError(RuntimeError):
    pass


class TokenizerProtocol(Protocol):
    eos_token_id: int | None
    pad_token_id: int | None
    vocab_size: int
    chat_template: str | None
    additional_special_tokens: list[str]

    def __len__(self) -> int: ...

    def apply_chat_template(
        self,
        conversation: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> Any: ...

    def __call__(self, text: str, *, add_special_tokens: bool) -> Mapping[str, Any]: ...

    def decode(self, token_ids: list[int], *, skip_special_tokens: bool = False) -> str: ...


@dataclass(frozen=True)
class LogicalRecord:
    instruction: str
    input_text: str | None
    output: str
    system: str | None
    source_hash: str


@dataclass(frozen=True)
class EncodedRecord:
    input_ids: tuple[int, ...]
    attention_mask: tuple[int, ...]
    labels: tuple[int, ...]
    prompt_tokens: int
    assistant_tokens: int
    user_tokens: int
    instruction_truncated: bool = False
    input_truncated: bool = False
    assistant_truncated: bool = False
    truncated_tokens: int = 0

    def as_dataset_record(self) -> dict[str, list[int]]:
        return {
            "input_ids": list(self.input_ids),
            "attention_mask": list(self.attention_mask),
            "labels": list(self.labels),
        }


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_config(path: str | Path) -> dict[str, object]:
    try:
        value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise SFTTokenizationError("TOKENIZATION_CONFIG_INVALID") from None
    if not isinstance(value, dict):
        raise SFTTokenizationError("TOKENIZATION_CONFIG_INVALID")
    return value


def validate_tokenization_config(config: Mapping[str, object]) -> None:
    if set(config) != {
        "schema_version", "status", "source_dataset", "model", "tokenization",
        "execution_allowed", "training_allowed",
    } or config.get("schema_version") != 1:
        raise SFTTokenizationError("TOKENIZATION_CONFIG_INVALID")
    source = config.get("source_dataset")
    model = config.get("model")
    tokenization = config.get("tokenization")
    if not all(isinstance(value, Mapping) for value in (source, model, tokenization)):
        raise SFTTokenizationError("TOKENIZATION_CONFIG_INVALID")
    assert isinstance(source, Mapping)
    assert isinstance(model, Mapping)
    assert isinstance(tokenization, Mapping)
    if (
        source.get("run_id") != "AIHUB-71748-SFT-PROCESSING-20260730-0015"
        or model.get("id") != "Qwen/Qwen2.5-1.5B-Instruct"
        or model.get("trust_remote_code") is not False
        or tokenization.get("max_seq_length") not in {512, 1024, 1536, 2048}
        or tokenization.get("assistant_only_loss") is not True
        or tokenization.get("train_on_prompt") is not False
        or tokenization.get("packing") is not False
        or config.get("execution_allowed") is not False
        or config.get("training_allowed") is not False
    ):
        raise SFTTokenizationError("TOKENIZATION_CONFIG_INVALID")


def validate_qlora_config(config: Mapping[str, object], *, bf16_supported: bool) -> None:
    expected_targets = [
        "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
    ]
    model = config.get("model")
    quantization = config.get("quantization")
    lora = config.get("lora")
    training = config.get("training")
    dataset = config.get("dataset")
    estimate = config.get("estimate")
    if not all(
        isinstance(value, Mapping)
        for value in (model, quantization, lora, training, dataset, estimate)
    ):
        raise SFTTokenizationError("QLORA_CONFIG_INVALID")
    assert isinstance(model, Mapping)
    assert isinstance(quantization, Mapping)
    assert isinstance(lora, Mapping)
    assert isinstance(training, Mapping)
    assert isinstance(dataset, Mapping)
    assert isinstance(estimate, Mapping)
    if (
        config.get("schema_version") != 1
        or model.get("base_model") != "Qwen/Qwen2.5-1.5B-Instruct"
        or model.get("trust_remote_code") is not False
        or quantization.get("load_in_4bit") is not True
        or quantization.get("quant_type") != "nf4"
        or quantization.get("use_double_quant") is not True
        or quantization.get("compute_dtype") != "bfloat16"
        or list(lora.get("target_modules", [])) != expected_targets
        or training.get("packing") is not False
        or training.get("max_seq_length") != 1536
        or training.get("eval_steps") != 100
        or training.get("save_steps") != 250
        or training.get("bf16") is not True
        or training.get("fp16") is not False
        or not bf16_supported
        or dataset.get("fingerprint")
        != "b6848e9413ecd0f63008cf18f505dda0b3197e562b5c6a9f955c1a7d41bc98a0"
        or estimate.get("optimizer_steps") != 1947
        or config.get("training_allowed") is not False
        or config.get("execution_allowed") is not False
    ):
        raise SFTTokenizationError("QLORA_CONFIG_INVALID")


def validate_output_location(
    output_root: str | Path,
    *,
    source_root: str | Path,
    repository_root: str | Path,
) -> None:
    output = Path(output_root).resolve()
    source = Path(source_root).resolve()
    repository = Path(repository_root).resolve()
    if output == repository or repository in output.parents:
        raise SFTTokenizationError("TOKENIZED_OUTPUT_INSIDE_REPOSITORY")
    if output == source or output in source.parents or source in output.parents:
        raise SFTTokenizationError("TOKENIZED_OUTPUT_OVERLAPS_SOURCE")


def iter_logical_records(path: str | Path) -> Iterable[LogicalRecord]:
    source = Path(path)
    try:
        stream = source.open("r", encoding="utf-8")
    except (OSError, UnicodeError):
        raise SFTTokenizationError("SOURCE_JSONL_INVALID") from None
    with stream:
        for line in stream:
            if not line.strip():
                raise SFTTokenizationError("SOURCE_JSONL_EMPTY_LINE")
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                raise SFTTokenizationError("SOURCE_JSONL_INVALID") from None
            if not isinstance(value, dict) or set(value) != OUTPUT_FIELDS:
                raise SFTTokenizationError("SOURCE_SCHEMA_INVALID")
            instruction = value["instruction"]
            input_text = value["input"]
            output = value["output"]
            system = value["system"]
            if (
                not isinstance(instruction, str)
                or not instruction.strip()
                or not isinstance(output, str)
                or not output.strip()
                or (input_text is not None and not isinstance(input_text, str))
                or (system is not None and not isinstance(system, str))
            ):
                raise SFTTokenizationError("SOURCE_SCHEMA_INVALID")
            yield LogicalRecord(
                instruction=instruction,
                input_text=input_text,
                output=output,
                system=system,
                source_hash=_canonical_sha256(value),
            )


def _content_has_control_token(tokenizer: TokenizerProtocol, value: str) -> bool:
    tokens = list(tokenizer.additional_special_tokens)
    return any(token and token in value for token in tokens)


def messages_for_record(
    record: LogicalRecord, *, separator: str,
) -> tuple[list[dict[str, str]], str]:
    user_content = record.instruction
    if record.input_text:
        user_content += separator + record.input_text
    messages: list[dict[str, str]] = []
    if record.system:
        messages.append({"role": "system", "content": record.system})
    messages.append({"role": "user", "content": user_content})
    return messages, user_content


def encode_record(
    tokenizer: TokenizerProtocol,
    record: LogicalRecord,
    *,
    separator: str = "\n\n",
) -> EncodedRecord:
    if tokenizer.eos_token_id is None or not tokenizer.chat_template:
        raise SFTTokenizationError("TOKENIZER_CONTRACT_INVALID")
    values = (record.instruction, record.input_text or "", record.output, record.system or "")
    if any(_content_has_control_token(tokenizer, value) for value in values):
        raise SFTTokenizationError("CHAT_TEMPLATE_CONTROL_TOKEN_PRESENT")
    messages, user_content = messages_for_record(record, separator=separator)
    prompt_ids = list(tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True,
    ))
    assistant_ids = list(tokenizer(record.output, add_special_tokens=False)["input_ids"])
    user_ids = list(tokenizer(user_content, add_special_tokens=False)["input_ids"])
    if not prompt_ids or not assistant_ids:
        raise SFTTokenizationError("TOKEN_SEQUENCE_EMPTY")
    if tokenizer.eos_token_id in assistant_ids:
        raise SFTTokenizationError("CHAT_TEMPLATE_CONTROL_TOKEN_PRESENT")
    input_ids = (*prompt_ids, *assistant_ids, tokenizer.eos_token_id)
    labels = tuple([IGNORE_INDEX] * len(prompt_ids) + assistant_ids + [tokenizer.eos_token_id])
    encoded = EncodedRecord(
        input_ids=input_ids,
        attention_mask=tuple([1] * len(input_ids)),
        labels=labels,
        prompt_tokens=len(prompt_ids),
        assistant_tokens=len(assistant_ids) + 1,
        user_tokens=len(user_ids),
    )
    validate_encoded_record(encoded, vocab_size=len(tokenizer))
    return encoded


def validate_encoded_record(record: EncodedRecord, *, vocab_size: int) -> None:
    size = len(record.input_ids)
    if not size or len(record.attention_mask) != size or len(record.labels) != size:
        raise SFTTokenizationError("TOKEN_SEQUENCE_SHAPE_INVALID")
    if any(not isinstance(token, int) or isinstance(token, bool) or not 0 <= token < vocab_size for token in record.input_ids):
        raise SFTTokenizationError("TOKEN_ID_OUT_OF_RANGE")
    if any(value != 1 for value in record.attention_mask):
        raise SFTTokenizationError("ATTENTION_MASK_INVALID")
    if any(label != IGNORE_INDEX and not 0 <= label < vocab_size for label in record.labels):
        raise SFTTokenizationError("LABEL_ID_OUT_OF_RANGE")
    if any(label != IGNORE_INDEX for label in record.labels[:record.prompt_tokens]):
        raise SFTTokenizationError("PROMPT_LABEL_NOT_MASKED")
    if not any(label != IGNORE_INDEX for label in record.labels[record.prompt_tokens:]):
        raise SFTTokenizationError("ASSISTANT_LABEL_EMPTY")


def _prefix_text(tokenizer: TokenizerProtocol, text: str, tokens: int) -> str:
    ids = list(tokenizer(text, add_special_tokens=False)["input_ids"])
    return tokenizer.decode(ids[:tokens], skip_special_tokens=False)


def truncate_record(
    tokenizer: TokenizerProtocol,
    record: LogicalRecord,
    *,
    max_length: int,
    separator: str = "\n\n",
) -> EncodedRecord:
    original = encode_record(tokenizer, record, separator=separator)
    if len(original.input_ids) <= max_length:
        return original
    working = record
    input_truncated = False
    instruction_truncated = False
    assistant_truncated = False
    for field in ("input_text", "instruction", "output"):
        value = getattr(working, field)
        if not value:
            continue
        ids = list(tokenizer(value, add_special_tokens=False)["input_ids"])
        low, high = 0, len(ids)
        best = 0
        while low <= high:
            middle = (low + high) // 2
            candidate = LogicalRecord(
                instruction=(
                    _prefix_text(tokenizer, value, middle)
                    if field == "instruction" else working.instruction
                ),
                input_text=(
                    _prefix_text(tokenizer, value, middle)
                    if field == "input_text" else working.input_text
                ),
                output=(
                    _prefix_text(tokenizer, value, middle)
                    if field == "output" else working.output
                ),
                system=working.system,
                source_hash=working.source_hash,
            )
            encoded = encode_record(tokenizer, candidate, separator=separator)
            if len(encoded.input_ids) <= max_length:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        if best < len(ids):
            working = LogicalRecord(
                instruction=(
                    _prefix_text(tokenizer, value, best)
                    if field == "instruction" else working.instruction
                ),
                input_text=(
                    _prefix_text(tokenizer, value, best)
                    if field == "input_text" else working.input_text
                ),
                output=(
                    _prefix_text(tokenizer, value, best)
                    if field == "output" else working.output
                ),
                system=working.system,
                source_hash=working.source_hash,
            )
            input_truncated |= field == "input_text"
            instruction_truncated |= field == "instruction"
            assistant_truncated |= field == "output"
        encoded = encode_record(tokenizer, working, separator=separator)
        if len(encoded.input_ids) <= max_length:
            return EncodedRecord(
                **{
                    **encoded.__dict__,
                    "input_truncated": input_truncated,
                    "instruction_truncated": instruction_truncated,
                    "assistant_truncated": assistant_truncated,
                    "truncated_tokens": len(original.input_ids) - len(encoded.input_ids),
                }
            )
    raise SFTTokenizationError("MAX_SEQUENCE_LENGTH_UNSATISFIABLE")


def percentile(values: list[int], percentage: int) -> int:
    if not values:
        raise SFTTokenizationError("LENGTH_STATISTICS_EMPTY")
    ordered = sorted(values)
    return ordered[math.ceil(percentage / 100 * len(ordered)) - 1]


def length_statistics(values: list[int]) -> dict[str, int | float]:
    return {
        "count": len(values),
        "min": min(values),
        "mean": round(statistics.fmean(values), 6),
        "median": statistics.median(values),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values),
        "sum": sum(values),
    }


def encoded_fingerprint(records: Iterable[EncodedRecord]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(json.dumps(
            record.as_dataset_record(), separators=(",", ":"), sort_keys=True,
        ).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def tokenizer_fingerprint(tokenizer_root: str | Path) -> tuple[str, dict[str, str]]:
    root = Path(tokenizer_root)
    names = (
        "config.json", "generation_config.json", "merges.txt", "tokenizer.json",
        "tokenizer_config.json", "vocab.json",
    )
    checksums: dict[str, str] = {}
    digest = hashlib.sha256()
    for name in names:
        path = root / name
        if not path.is_file():
            raise SFTTokenizationError("TOKENIZER_ARTIFACT_MISSING")
        value = hashlib.sha256(path.read_bytes()).hexdigest()
        checksums[name] = value
        digest.update(f"{name}\0{value}\n".encode("ascii"))
    return digest.hexdigest(), checksums


def _file_checksums(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file() and path.name != "checksums.sha256":
            values[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return values


def write_tokenized_dataset(
    output_root: str | Path,
    *,
    train_records: list[dict[str, list[int]]],
    validation_records: list[dict[str, list[int]]],
    config: Mapping[str, object],
    statistics_value: Mapping[str, object],
    result: Mapping[str, object],
) -> dict[str, object]:
    try:
        from datasets import Dataset, load_from_disk
    except ImportError:
        raise SFTTokenizationError("DATASETS_DEPENDENCY_MISSING") from None
    final = Path(output_root)
    staging = final.with_name(final.name + ".staging")
    failed = final.with_name(final.name + ".failed")
    if any(path.exists() for path in (final, staging, failed)):
        raise SFTTokenizationError("TOKENIZATION_RUN_ID_ALREADY_USED")
    staging.mkdir(parents=True)
    try:
        Dataset.from_list(train_records).save_to_disk(staging / "train")
        Dataset.from_list(validation_records).save_to_disk(staging / "validation")
        (staging / "tokenization-config.yaml").write_text(
            yaml.safe_dump(dict(config), allow_unicode=True, sort_keys=False), encoding="utf-8",
        )
        (staging / "tokenization-statistics.json").write_text(
            json.dumps(dict(statistics_value), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        (staging / "tokenization-result.yaml").write_text(
            yaml.safe_dump(dict(result), allow_unicode=True, sort_keys=False), encoding="utf-8",
        )
        checksums = _file_checksums(staging)
        (staging / "checksums.sha256").write_text(
            "".join(f"{value}  {name}\n" for name, value in checksums.items()), encoding="ascii",
        )
        reloaded_train = load_from_disk(staging / "train")
        reloaded_validation = load_from_disk(staging / "validation")
        if len(reloaded_train) != len(train_records) or len(reloaded_validation) != len(validation_records):
            raise SFTTokenizationError("TOKENIZED_DATASET_RELOAD_FAILED")
        os.replace(staging, final)
    except Exception:
        if staging.exists() and not failed.exists():
            os.replace(staging, failed)
        raise
    final_checksums = _file_checksums(final)
    fingerprint = _canonical_sha256(final_checksums)
    return {
        "checksums": final_checksums,
        "artifact_fingerprint": fingerprint,
        "total_bytes": sum(path.stat().st_size for path in final.rglob("*") if path.is_file()),
    }
