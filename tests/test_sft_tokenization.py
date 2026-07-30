from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

from scripts.training.tokenize_dohalm_v01 import _package_versions
from src.training.sft_tokenization import (
    IGNORE_INDEX,
    LogicalRecord,
    SFTTokenizationError,
    encode_record,
    encoded_fingerprint,
    iter_logical_records,
    length_statistics,
    load_config,
    truncate_record,
    validate_encoded_record,
    validate_output_location,
    validate_qlora_config,
    validate_tokenization_config,
    write_tokenized_dataset,
)


class FakeTokenizer:
    eos_token_id = 9
    eos_token = "<eos>"
    pad_token_id = 0
    vocab_size = 10
    chat_template = "synthetic"
    additional_special_tokens: ClassVar[list[str]] = ["<control>"]

    def __len__(self) -> int:
        return 10

    def __call__(self, text: str, *, add_special_tokens: bool):
        del add_special_tokens
        return {"input_ids": [1 + ord(value) % 7 for value in text]}

    def apply_chat_template(self, conversation, *, tokenize, add_generation_prompt):
        assert tokenize is True
        ids = [1]
        for message in conversation:
            ids.extend([2 if message["role"] == "system" else 3])
            ids.extend(self(message["content"], add_special_tokens=False)["input_ids"])
            ids.append(4)
        if add_generation_prompt:
            ids.append(5)
        return ids

    def decode(self, token_ids, *, skip_special_tokens=False):
        del skip_special_tokens
        return "".join(chr(97 + token % 7) for token in token_ids)


def _record(**updates: object) -> LogicalRecord:
    values = {
        "instruction": "synthetic instruction",
        "input_text": None,
        "output": "synthetic response",
        "system": None,
        "source_hash": "a" * 64,
    }
    values.update(updates)
    return LogicalRecord(**values)  # type: ignore[arg-type]


def test_assistant_only_loss_masks_every_prompt_token() -> None:
    encoded = encode_record(FakeTokenizer(), _record())

    assert all(value == IGNORE_INDEX for value in encoded.labels[:encoded.prompt_tokens])
    assert encoded.labels[encoded.prompt_tokens:] == encoded.input_ids[encoded.prompt_tokens:]
    assert encoded.input_ids[-1] == FakeTokenizer.eos_token_id
    validate_encoded_record(encoded, vocab_size=len(FakeTokenizer()))


def test_input_then_instruction_then_assistant_truncation() -> None:
    tokenizer = FakeTokenizer()
    with_input = _record(input_text="context" * 8)
    encoded = truncate_record(tokenizer, with_input, max_length=55)
    assert len(encoded.input_ids) <= 55
    assert encoded.input_truncated is True
    assert encoded.assistant_truncated is False

    long_answer = _record(instruction="i", output="response" * 20)
    encoded_answer = truncate_record(tokenizer, long_answer, max_length=30)
    assert encoded_answer.assistant_truncated is True
    assert encoded_answer.input_ids[-1] == tokenizer.eos_token_id


def test_control_token_and_invalid_source_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(SFTTokenizationError, match="^CHAT_TEMPLATE_CONTROL_TOKEN_PRESENT$"):
        encode_record(FakeTokenizer(), _record(output="bad <control> value"))

    path = tmp_path / "invalid.jsonl"
    path.write_text(json.dumps({"instruction": "x"}) + "\n", encoding="utf-8")
    with pytest.raises(SFTTokenizationError, match="^SOURCE_SCHEMA_INVALID$"):
        list(iter_logical_records(path))


def test_same_input_has_same_token_fingerprint() -> None:
    tokenizer = FakeTokenizer()
    records = [encode_record(tokenizer, _record()), encode_record(tokenizer, _record())]
    assert encoded_fingerprint(records) == encoded_fingerprint(records)


def test_length_statistics_and_repository_configs_are_valid() -> None:
    assert length_statistics([1, 2, 3, 4, 5])["p95"] == 5

    tokenization = load_config("configs/training/dohalm-v0.1-tokenization.yaml")
    qlora = load_config("configs/training/dohalm-v0.1-qlora.yaml")
    validate_tokenization_config(tokenization)
    validate_qlora_config(qlora, bf16_supported=True)
    with pytest.raises(SFTTokenizationError, match="^QLORA_CONFIG_INVALID$"):
        validate_qlora_config(qlora, bf16_supported=False)


def test_tokenized_dataset_writer_reloads_and_rejects_run_reuse(tmp_path: Path) -> None:
    encoded = encode_record(FakeTokenizer(), _record()).as_dataset_record()
    destination = tmp_path / "tokenized"
    written = write_tokenized_dataset(
        destination,
        train_records=[encoded],
        validation_records=[encoded],
        config={"schema_version": 1},
        statistics_value={"rows": {"train": 1, "validation": 1}},
        result={"status": "synthetic", "training_started": False},
    )
    assert len(written["artifact_fingerprint"]) == 64
    assert written["total_bytes"] > 0
    assert (destination / "train" / "dataset_info.json").is_file()
    assert (destination / "validation" / "dataset_info.json").is_file()
    with pytest.raises(SFTTokenizationError, match="^TOKENIZATION_RUN_ID_ALREADY_USED$"):
        write_tokenized_dataset(
            destination,
            train_records=[encoded],
            validation_records=[encoded],
            config={},
            statistics_value={},
            result={},
        )


def test_package_versions_are_yaml_serializable_strings() -> None:
    versions = _package_versions()
    assert all(isinstance(value, str) for value in versions.values())
    assert yaml.safe_load(yaml.safe_dump(versions)) == versions


def test_output_location_must_be_external_and_separate(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    source = tmp_path / "source"
    repository.mkdir()
    source.mkdir()
    validate_output_location(
        tmp_path / "tokenized", source_root=source, repository_root=repository,
    )
    with pytest.raises(
        SFTTokenizationError, match="^TOKENIZED_OUTPUT_INSIDE_REPOSITORY$",
    ):
        validate_output_location(
            repository / "data", source_root=source, repository_root=repository,
        )
    with pytest.raises(
        SFTTokenizationError, match="^TOKENIZED_OUTPUT_OVERLAPS_SOURCE$",
    ):
        validate_output_location(
            source / "tokenized", source_root=source, repository_root=repository,
        )
