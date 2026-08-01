from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.data import artifacts
from src.data.artifacts import AtomicArtifactDirectory
from src.data.checksums import canonical_json_bytes
from src.data.errors import DataPipelineError
from src.data.v02_sidecar import (
    V02SidecarError,
    _canonical_record_hash,
    _normalize_clamped_mean_one,
    _quality_tier,
    build_v02_sidecar_package,
    completion_metrics,
    length_bucket,
    load_policy,
    repetition_metrics,
    validate_v02_package,
)

EOS_ID = 151645


def _content_hash(record: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


def _record(index: int, *, output: str | None = None) -> dict[str, object]:
    return {
        "instruction": f"synthetic instruction {index}",
        "input": None,
        "output": output or f"synthetic complete response {index}입니다.",
        "system": None,
    }


def _encoded(assistant_tokens: int) -> dict[str, list[int]]:
    prompt = 3
    ids = [10, 11, 12, *([20] * (assistant_tokens - 1)), EOS_ID]
    return {
        "input_ids": ids,
        "attention_mask": [1] * len(ids),
        "labels": [-100] * prompt + [20] * (assistant_tokens - 1) + [EOS_ID],
    }


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("wb") as stream:
        for record in records:
            stream.write(canonical_json_bytes(record))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, object], dict[str, Any]]:
    from datasets import Dataset

    source = tmp_path / "source"
    tokenized = tmp_path / "tokenized"
    source.mkdir()
    tokenized.mkdir()
    train = [
        _record(0),
        _record(1),
        _record(2),
        _record(3),
        _record(4, output="반복입니다. 반복입니다."),
        _record(5),
        _record(6),
        _record(7, output="미완성 응답"),
    ]
    validation = [_record(100 + index) for index in range(4)]
    _write_jsonl(source / "train.jsonl", train)
    _write_jsonl(source / "validation.jsonl", validation)
    for name, value in (
        ("manifest.yaml", "schema_version: 1\n"),
        ("statistics.json", "{}\n"),
        ("processing-result.yaml", "schema_version: 1\n"),
    ):
        (source / name).write_text(value, encoding="utf-8")
    train_lengths = [64, 128, 129, 256, 257, 512, 513, 800]
    validation_lengths = [64, 200, 400, 600]
    Dataset.from_list([_encoded(value) for value in train_lengths]).save_to_disk(
        tokenized / "train"
    )
    Dataset.from_list([_encoded(value) for value in validation_lengths]).save_to_disk(
        tokenized / "validation"
    )
    policy = load_policy("configs/data/dohalm-v0.2-sidecar-sampling.yaml")
    policy["dataset_id"] = "SYNTHETIC-V02"
    source_policy = policy["source"]
    assert isinstance(source_policy, dict)
    source_policy["rows"] = {"train": len(train), "validation": len(validation)}
    source_policy["checksums"] = {
        name: _sha(source / name)
        for name in (
            "train.jsonl",
            "validation.jsonl",
            "manifest.yaml",
            "statistics.json",
            "processing-result.yaml",
        )
    }
    lookup: dict[str, Any] = {}
    for index, record in enumerate([*train, *validation]):
        lookup[_content_hash(record)] = {f"category-{index % 2}": 1}
    lookup[_content_hash(train[0])] = {"category-0": 1, "category-1": 1}
    return source, tokenized, policy, lookup


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (0, "short"),
        (128, "short"),
        (129, "medium"),
        (256, "medium"),
        (257, "long"),
        (512, "long"),
        (513, "very_long"),
    ],
)
def test_length_bucket_boundaries(tokens: int, expected: str) -> None:
    assert length_bucket(tokens) == expected


def test_record_identity_is_deterministic_and_split_scoped() -> None:
    record = _record(1)
    identity = _canonical_record_hash("train", 0, record)
    assert identity == _canonical_record_hash("train", 0, record)
    assert identity != _canonical_record_hash("validation", 0, record)
    assert identity != _canonical_record_hash("train", 1, record)


def test_bounded_sampling_normalization_is_mean_one() -> None:
    weights = _normalize_clamped_mean_one([0.01, 1.0, 100.0], 0.25, 3.0)
    assert min(weights) >= 0.25
    assert max(weights) <= 3.0
    assert pytest.approx(sum(weights) / len(weights), abs=1e-10) == 1.0


def test_quality_tier_uses_single_most_conservative_weight() -> None:
    policy = load_policy("configs/data/dohalm-v0.2-sidecar-sampling.yaml")
    assert _quality_tier(
        {"incomplete_candidate", "strong_repeat_candidate", "ambiguous_category"},
        policy,
    ) == ("repeat_and_incomplete", 0.25)


def test_completion_score_is_deterministic() -> None:
    assert completion_metrics("완결된 문장입니다.")[:2] == (1.0, True)
    assert completion_metrics("형식상 종결!")[:2] == (0.75, True)
    assert completion_metrics("열린 괄호입니다. (")[:2] == (0.5, False)
    assert completion_metrics("명확한 미완성")[:2] == (0.0, False)


def test_repetition_score_tiers() -> None:
    assert repetition_metrics("정상 문장입니다.", near_duplicate=False)[0] == 0
    assert repetition_metrics("정상 문장입니다.", near_duplicate=True)[0] == 1
    assert (
        repetition_metrics(
            "반복입니다. 다른 문장입니다. 반복입니다.", near_duplicate=False
        )[0]
        == 2
    )
    assert (
        repetition_metrics("반복입니다. 반복입니다. 반복입니다.", near_duplicate=False)[
            0
        ]
        == 3
    )


def test_build_package_preserves_content_and_aligns_sidecar(tmp_path: Path) -> None:
    source, tokenized, policy, lookup = _fixture(tmp_path)
    output = tmp_path / "output"

    result = build_v02_sidecar_package(
        source_root=source,
        tokenized_root=tokenized,
        output_root=output,
        policy=policy,
        git_head="a" * 40,
        category_lookup=lookup,
    )

    assert (output / "train.jsonl").read_bytes() == (
        source / "train.jsonl"
    ).read_bytes()
    assert (output / "validation.jsonl").read_bytes() == (
        source / "validation.jsonl"
    ).read_bytes()
    assert result["rows"] == {"train": 8, "validation": 4, "sidecar": 12}
    sidecar = [
        json.loads(line)
        for line in (output / "quality-sidecar.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len({record["record_hash"] for record in sidecar}) == 12
    assert [record["line_index"] for record in sidecar[:8]] == list(range(8))
    assert all(record["sampling_weight"] == 1.0 for record in sidecar[8:])
    assert sidecar[0]["category_status"] == "ambiguous"
    assert "ambiguous_category" in sidecar[0]["quality_flags"]
    assert (
        pytest.approx(sum(record["sampling_weight"] for record in sidecar[:8]) / 8)
        == 1.0
    )
    assert result["sampling"]["effective_sample_size_ratio"] >= 0.60
    validate_v02_package(output, policy=policy)


def test_review_queue_contains_only_review_flags(tmp_path: Path) -> None:
    source, tokenized, policy, lookup = _fixture(tmp_path)
    output = tmp_path / "output"
    build_v02_sidecar_package(
        source_root=source,
        tokenized_root=tokenized,
        output_root=output,
        policy=policy,
        git_head="b" * 40,
        category_lookup=lookup,
    )
    queue = [
        json.loads(line)
        for line in (output / "review-queue.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert queue
    assert all(
        set(record["review_reason"])
        <= {
            "incomplete_candidate",
            "strong_repeat_candidate",
            "ambiguous_category",
            "unresolved_category",
        }
        for record in queue
    )
    assert all(
        "instruction" not in record and "output" not in record for record in queue
    )


def test_package_no_replace_and_checksum_tamper_fail_closed(tmp_path: Path) -> None:
    source, tokenized, policy, lookup = _fixture(tmp_path)
    output = tmp_path / "output"
    kwargs = {
        "source_root": source,
        "tokenized_root": tokenized,
        "output_root": output,
        "policy": policy,
        "git_head": "c" * 40,
        "category_lookup": lookup,
    }
    build_v02_sidecar_package(**kwargs)
    with pytest.raises(V02SidecarError, match="^OUTPUT_ID_ALREADY_USED$"):
        build_v02_sidecar_package(**kwargs)
    with (output / "statistics.json").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(V02SidecarError, match="^CHECKSUM_MISMATCH$"):
        validate_v02_package(output, policy=policy)


def test_source_checksum_mismatch_fails_before_output(tmp_path: Path) -> None:
    source, tokenized, policy, lookup = _fixture(tmp_path)
    source_policy = policy["source"]
    assert isinstance(source_policy, dict)
    source_policy["checksums"]["train.jsonl"] = "0" * 64
    output = tmp_path / "output"
    with pytest.raises(V02SidecarError, match="^SOURCE_CHECKSUM_MISMATCH$"):
        build_v02_sidecar_package(
            source_root=source,
            tokenized_root=tokenized,
            output_root=output,
            policy=policy,
            git_head="d" * 40,
            category_lookup=lookup,
        )
    assert not output.exists()


def test_atomic_directory_publish_race_does_not_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    final = tmp_path / "final"
    atomic = AtomicArtifactDirectory(final)
    with atomic as staging:
        (staging / "artifact").write_text("candidate", encoding="utf-8")
        original = artifacts._rename_directory_no_replace

        def compete(source: Path, destination: Path) -> None:
            destination.mkdir()
            (destination / "artifact").write_text("winner", encoding="utf-8")
            original(source, destination)

        monkeypatch.setattr(artifacts, "_rename_directory_no_replace", compete)
        with pytest.raises(DataPipelineError):
            atomic.publish()
    assert (final / "artifact").read_text(encoding="utf-8") == "winner"


def test_repository_policy_is_valid_and_non_executable() -> None:
    policy = load_policy("configs/data/dohalm-v0.2-sidecar-sampling.yaml")
    assert policy["execution_allowed"] is False
    assert policy["tokenization_allowed"] is False
    assert policy["training_allowed"] is False
    assert sum(policy["target_length_distribution"].values()) == 1.0
    assert yaml.safe_load(yaml.safe_dump(policy)) == policy
