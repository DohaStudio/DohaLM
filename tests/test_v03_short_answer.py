from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from src.data.checksums import canonical_json_bytes
from src.data.v03_quality_validation import (
    assess_candidate,
    extract_numbers,
    select_extractive_variant,
    validate_no_raw_text,
)
from src.data.v03_short_answer import (
    V03ShortAnswerError,
    _source_record_hash,
    _variant_hash,
    generate_candidates,
    load_policy,
    publish_package,
    validate_package,
)


class FakeEvaluator:
    identity = {"model_id": "synthetic", "model_revision": "1"}

    @staticmethod
    def token_count(value: str) -> int:
        return len(value.split())

    @staticmethod
    def similarities(
        sources: list[str], candidates: list[str], *, batch_size: int = 4
    ) -> list[float]:
        del batch_size
        return [0.95 for _ in zip(sources, candidates)]


def _sentence(prefix: str, start: int, count: int) -> str:
    return (
        " ".join(f"{prefix}{index:03d}" for index in range(start, start + count))
        + "입니다."
    )


def _record(index: int) -> dict[str, object]:
    return {
        "instruction": f"topic{index:03d}의 핵심 결론은 무엇입니까?",
        "input": None,
        "output": " ".join(
            (
                _sentence(f"topic{index:03d}a", 0, 90),
                _sentence(f"topic{index:03d}b", 90, 90),
                _sentence(f"topic{index:03d}c", 180, 90),
            )
        ),
        "system": None,
    }


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    with path.open("wb") as stream:
        for value in values:
            stream.write(canonical_json_bytes(value))


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    source = tmp_path / "source"
    source.mkdir()
    train = [_record(index) for index in range(20)]
    validation = [_record(100)]
    _write_jsonl(source / "train.jsonl", train)
    _write_jsonl(source / "validation.jsonl", validation)
    sidecar = []
    for index, record in enumerate((*train, *validation)):
        split = "train" if index < len(train) else "validation"
        line_index = index if split == "train" else 0
        sidecar.append(
            {
                "record_hash": _source_record_hash(split, line_index, record),
                "split": split,
                "line_index": line_index,
                "category": f"category-{index % 2}",
                "category_status": "resolved",
                "assistant_tokens": 270,
                "completion_score": 1.0,
                "repetition_score": 0,
                "is_strong_repeat_candidate": False,
                "quality_flags": ["complete", "long"],
                "review_required": False,
            }
        )
    _write_jsonl(source / "quality-sidecar.jsonl", sidecar)
    policy = deepcopy(load_policy("configs/data/dohalm-v0.3-short-answer.yaml"))
    policy["source"]["rows"] = {"train": len(train), "validation": len(validation)}
    policy["source"]["checksums"] = {
        name: hashlib.sha256((source / name).read_bytes()).hexdigest()
        for name in ("train.jsonl", "validation.jsonl", "quality-sidecar.jsonl")
    }
    policy["dry_run"]["records_per_category"] = 2
    return source, policy


def test_extractive_generation_uses_complete_source_sentences() -> None:
    source = _record(1)
    candidate = select_extractive_variant(
        str(source["instruction"]),
        str(source["output"]),
        token_count=FakeEvaluator.token_count,
        minimum_tokens=80,
        maximum_tokens=180,
    )
    assert candidate is not None
    assert 80 <= FakeEvaluator.token_count(candidate) <= 180
    assert candidate in str(source["output"])


def test_quality_blocks_numeric_change_and_new_fact() -> None:
    assessment = assess_candidate(
        source_answer="2024년 기준 값은 10입니다.",
        candidate="2025년 기준 값은 11입니다.",
        source_tokens=100,
        candidate_tokens=80,
        semantic_score=0.99,
        semantic_threshold=0.85,
        generation_method="constrained_abstractive",
    )
    assert not assessment["accepted"]
    assert "numeric_mismatch" in assessment["rejection_reasons"]
    assert "new_fact_risk" in assessment["rejection_reasons"]
    assert extract_numbers("2024년 10%") == ("2024년", "10%")


def test_completion_repetition_and_semantic_gate() -> None:
    assessment = assess_candidate(
        source_answer="서로 다른 핵심 문장입니다. 결론을 완성합니다.",
        candidate="반복입니다. 반복입니다. 반복입니다.",
        source_tokens=200,
        candidate_tokens=80,
        semantic_score=0.2,
        semantic_threshold=0.85,
        generation_method="extractive",
    )
    assert not assessment["accepted"]
    assert {"strong_repetition", "semantic_threshold"} <= set(
        assessment["rejection_reasons"]
    )


def test_record_identity_is_parent_variant_and_policy_scoped() -> None:
    first = _variant_hash("a" * 64, "short", "답변입니다.", "sha256:" + "b" * 64)
    assert first == _variant_hash(
        "a" * 64, "short", "답변입니다.", "sha256:" + "b" * 64
    )
    assert first != _variant_hash(
        "a" * 64, "medium", "답변입니다.", "sha256:" + "b" * 64
    )


def test_sidecar_rejects_raw_fields() -> None:
    validate_no_raw_text({"record_hash": "a" * 64})
    with pytest.raises(ValueError, match="RAW_TEXT_FIELD_FORBIDDEN"):
        validate_no_raw_text({"record_hash": "a" * 64, "output": "secret"})


def test_synthetic_candidate_flow_and_source_preservation(tmp_path: Path) -> None:
    source, policy = _fixture(tmp_path)
    before = {
        name: (source / name).read_bytes()
        for name in ("train.jsonl", "validation.jsonl")
    }
    result = generate_candidates(
        source_root=source, evaluator=FakeEvaluator(), policy=policy, dry_run=True
    )
    assert result["attempted"] == 4
    assert len(result["accepted"]) == 4
    assert all(not item["review_required"] for item in result["sidecar_new"])
    assert before == {name: (source / name).read_bytes() for name in before}


def test_checksum_mismatch_fails_closed(tmp_path: Path) -> None:
    source, policy = _fixture(tmp_path)
    policy["source"]["checksums"]["train.jsonl"] = "0" * 64
    with pytest.raises(V03ShortAnswerError, match="SOURCE_CHECKSUM_MISMATCH"):
        generate_candidates(
            source_root=source, evaluator=FakeEvaluator(), policy=policy, dry_run=True
        )


def test_package_is_atomic_reloadable_and_no_replace(tmp_path: Path) -> None:
    source, policy = _fixture(tmp_path)
    output = tmp_path / "v03"
    validation_before = (source / "validation.jsonl").read_bytes()
    result = publish_package(
        source_root=source,
        output_root=output,
        policy=policy,
        evaluator=FakeEvaluator(),
        git_head="a" * 40,
    )
    assert result["status"] == "completed"
    assert (output / "validation.jsonl").read_bytes() == validation_before
    assert validate_package(output, policy=policy)["rows"]["validation"] == 1
    assert not list(tmp_path.glob(".v03.staging-*"))
    with pytest.raises(V03ShortAnswerError, match="OUTPUT_ID_ALREADY_USED"):
        publish_package(
            source_root=source,
            output_root=output,
            policy=policy,
            evaluator=FakeEvaluator(),
            git_head="a" * 40,
        )
