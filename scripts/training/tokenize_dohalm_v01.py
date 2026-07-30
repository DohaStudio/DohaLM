"""Build the DohaLM v0.1 tokenized SFT Dataset; never starts training."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any

from src.data.processing.post_validation import (
    validate_checksums,
    validate_jsonl_and_splits,
)
from src.training.sft_tokenization import (
    LogicalRecord,
    SFTTokenizationError,
    encode_record,
    encoded_fingerprint,
    iter_logical_records,
    length_statistics,
    load_config,
    messages_for_record,
    tokenizer_fingerprint,
    truncate_record,
    validate_encoded_record,
    validate_output_location,
    validate_tokenization_config,
    write_tokenized_dataset,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run-root", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--config", type=Path,
        default=Path("configs/training/dohalm-v0.1-tokenization.yaml"),
    )
    parser.add_argument("--tokenize-only", action="store_true", required=True)
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_versions() -> dict[str, str]:
    import accelerate
    import bitsandbytes
    import datasets
    import peft
    import sentencepiece
    import tokenizers
    import torch
    import transformers
    import trl

    return {
        "python": str(platform.python_version()),
        "torch": str(torch.__version__),
        "cuda": str(torch.version.cuda),
        "transformers": str(transformers.__version__),
        "datasets": str(datasets.__version__),
        "tokenizers": str(tokenizers.__version__),
        "accelerate": str(accelerate.__version__),
        "peft": str(peft.__version__),
        "trl": str(trl.__version__),
        "bitsandbytes": str(bitsandbytes.__version__),
        "sentencepiece": str(sentencepiece.__version__),
    }


def run(arguments: argparse.Namespace) -> dict[str, object]:
    from transformers import AutoTokenizer

    config = load_config(arguments.config)
    validate_tokenization_config(config)
    validate_output_location(
        arguments.output_root,
        source_root=arguments.source_run_root,
        repository_root=Path(__file__).resolve().parents[2],
    )
    source = config["source_dataset"]
    model = config["model"]
    tokenization = config["tokenization"]
    assert isinstance(source, dict)
    assert isinstance(model, dict)
    assert isinstance(tokenization, dict)
    expected_checksums = source["checksums"]
    expected_rows = source["expected_rows"]
    assert isinstance(expected_checksums, dict)
    assert isinstance(expected_rows, dict)
    validate_checksums(arguments.source_run_root)
    for name, expected in expected_checksums.items():
        if _sha256(arguments.source_run_root / name) != expected:
            raise SFTTokenizationError("SOURCE_CHECKSUM_MISMATCH")
    validate_jsonl_and_splits(
        arguments.source_run_root,
        expected_training=int(expected_rows["train"]),
        expected_validation=int(expected_rows["validation"]),
        minimum_training=10_000,
        minimum_validation=1_000,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        arguments.tokenizer_root, local_files_only=True,
        trust_remote_code=bool(model["trust_remote_code"]),
    )
    fingerprint, tokenizer_checksums = tokenizer_fingerprint(arguments.tokenizer_root)
    max_length = int(tokenization["max_seq_length"])
    separator = str(tokenization["user_input_separator"])
    split_paths = {
        "train": arguments.source_run_root / "train.jsonl",
        "validation": arguments.source_run_root / "validation.jsonl",
    }
    lengths: dict[str, list[int]] = {
        "total": [], "prompt": [], "assistant": [], "user": [],
    }
    encoded_by_split: dict[str, list[Any]] = {"train": [], "validation": []}
    decode_samples: dict[str, list[tuple[LogicalRecord, Any]]] = {
        "train": [], "validation": [],
    }
    truncation = {
        "records": 0, "input_records": 0, "instruction_records": 0,
        "assistant_records": 0, "tokens_removed": 0,
    }
    candidate_stats = {
        str(candidate): {
            "truncated_records": 0,
            "assistant_truncated_records": 0,
            "minimum_tokens_over_limit": 0,
        }
        for candidate in tokenization["candidates"]
    }
    for split, path in split_paths.items():
        for logical in iter_logical_records(path):
            full = encode_record(tokenizer, logical, separator=separator)
            lengths["total"].append(len(full.input_ids))
            lengths["prompt"].append(full.prompt_tokens)
            lengths["assistant"].append(full.assistant_tokens)
            lengths["user"].append(full.user_tokens)
            encoded = (
                full
                if len(full.input_ids) <= max_length
                else truncate_record(
                    tokenizer, logical, max_length=max_length, separator=separator,
                )
            )
            for candidate in tokenization["candidates"]:
                candidate_length = int(candidate)
                candidate_value = candidate_stats[str(candidate_length)]
                if len(full.input_ids) <= candidate_length:
                    continue
                candidate_value["truncated_records"] += 1
                candidate_value["minimum_tokens_over_limit"] += (
                    len(full.input_ids) - candidate_length
                )
                instruction_ids = tokenizer(
                    logical.instruction, add_special_tokens=False,
                )["input_ids"]
                minimal_instruction = tokenizer.decode(
                    list(instruction_ids[:1]), skip_special_tokens=False,
                )
                minimal_prompt = LogicalRecord(
                    instruction=minimal_instruction,
                    input_text=None,
                    output=logical.output,
                    system=logical.system,
                    source_hash=logical.source_hash,
                )
                if len(encode_record(
                    tokenizer, minimal_prompt, separator=separator,
                ).input_ids) > candidate_length:
                    candidate_value["assistant_truncated_records"] += 1
            validate_encoded_record(encoded, vocab_size=len(tokenizer))
            encoded_by_split[split].append(encoded)
            if len(decode_samples[split]) < 5:
                decode_samples[split].append((logical, encoded))
            if encoded.truncated_tokens:
                truncation["records"] += 1
                truncation["tokens_removed"] += encoded.truncated_tokens
                truncation["input_records"] += int(encoded.input_truncated)
                truncation["instruction_records"] += int(encoded.instruction_truncated)
                truncation["assistant_records"] += int(encoded.assistant_truncated)
    first_fingerprints = {
        split: encoded_fingerprint(records)
        for split, records in encoded_by_split.items()
    }
    first_sample_fingerprints = {
        split: encoded_fingerprint(records[:64])
        for split, records in encoded_by_split.items()
    }
    second_sample_fingerprints = {}
    for split, path in split_paths.items():
        repeated = []
        for logical in islice(iter_logical_records(path), 64):
            full = encode_record(tokenizer, logical, separator=separator)
            repeated.append(
                full
                if len(full.input_ids) <= max_length
                else truncate_record(
                    tokenizer, logical, max_length=max_length, separator=separator,
                )
            )
        second_sample_fingerprints[split] = encoded_fingerprint(repeated)
    if first_sample_fingerprints != second_sample_fingerprints:
        raise SFTTokenizationError("TOKENIZATION_FINGERPRINT_NONDETERMINISTIC")
    decoded_samples = 0
    for split in ("train", "validation"):
        for logical, encoded in decode_samples[split]:
            decoded = tokenizer.decode(list(encoded.input_ids), skip_special_tokens=False)
            if not decoded or tokenizer.eos_token not in decoded:
                raise SFTTokenizationError("DECODE_VALIDATION_FAILED")
            messages, _ = messages_for_record(
                logical, separator=separator,
            )
            expected_prompt = list(tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=True,
            ))
            expected_assistant = list(tokenizer(
                logical.output, add_special_tokens=False,
            )["input_ids"])
            if list(encoded.input_ids) != [
                *expected_prompt, *expected_assistant, tokenizer.eos_token_id,
            ]:
                raise SFTTokenizationError("CHAT_TEMPLATE_BOUNDARY_INVALID")
            decoded_assistant = tokenizer.decode(
                expected_assistant, skip_special_tokens=False,
            )
            if (
                "\ufffd" in decoded_assistant
                or list(tokenizer(
                    decoded_assistant, add_special_tokens=False,
                )["input_ids"]) != expected_assistant
            ):
                raise SFTTokenizationError("DECODE_VALIDATION_FAILED")
            decoded_samples += 1
    statistics_value: dict[str, object] = {
        "schema_version": 1,
        "source_run_id": source["run_id"],
        "rows": {
            "train": len(encoded_by_split["train"]),
            "validation": len(encoded_by_split["validation"]),
            "total": sum(len(records) for records in encoded_by_split.values()),
        },
        "lengths": {name: length_statistics(values) for name, values in lengths.items()},
        "max_seq_length": max_length,
        "truncation": truncation,
        "candidate_analysis": candidate_stats,
        "token_fingerprints": first_fingerprints,
        "deterministic_sample_token_fingerprints": first_sample_fingerprints,
        "decoded_samples_checked": decoded_samples,
        "template_valid": True,
        "loss_boundary_valid": True,
        "korean_decode_valid": True,
        "statistics_note": (
            "Run 0015 statistics.json의 pii.training_excluded는 전역 PII 우선 제외 수치다. "
            "Tokenization 행 수와 split 행 수는 train.jsonl 및 validation.jsonl을 기준으로 검증했다."
        ),
    }
    config_fingerprint = hashlib.sha256(arguments.config.read_bytes()).hexdigest()
    dataset_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "source_run_id": source["run_id"],
                "config_fingerprint": config_fingerprint,
                "token_fingerprints": first_fingerprints,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    result: dict[str, object] = {
        "schema_version": 1,
        "status": "completed",
        "tokenization_run_id": tokenization["run_id"],
        "source_run_id": source["run_id"],
        "model_id": model["id"],
        "model_revision": model["revision"],
        "tokenizer_fingerprint": fingerprint,
        "config_fingerprint": config_fingerprint,
        "dataset_fingerprint": dataset_fingerprint,
        "length_distribution_fingerprint": hashlib.sha256(
            json.dumps(statistics_value["lengths"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "token_fingerprints": first_fingerprints,
        "deterministic_sample_token_fingerprints": first_sample_fingerprints,
        "source_checksums": expected_checksums,
        "tokenizer_checksums": tokenizer_checksums,
        "versions": _package_versions(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "packing": False,
        "assistant_only_loss": True,
        "training_started": False,
        "training_allowed": False,
        "execution_allowed": False,
    }
    written = write_tokenized_dataset(
        arguments.output_root,
        train_records=[value.as_dataset_record() for value in encoded_by_split["train"]],
        validation_records=[value.as_dataset_record() for value in encoded_by_split["validation"]],
        config=config,
        statistics_value=statistics_value,
        result=result,
    )
    return {**result, **written, "statistics": statistics_value}


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = run(arguments)
    except (SFTTokenizationError, OSError, RuntimeError, ValueError) as exc:
        code = str(exc) if str(exc).isupper() else "TOKENIZATION_FAILED"
        print(json.dumps({"status": "blocked", "error_code": code, "training_started": False}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
