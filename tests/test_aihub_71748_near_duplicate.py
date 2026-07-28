import json
import logging
import zipfile

import pytest

from src.data.aihub_71748_near_duplicate import (
    NearDuplicatePerformanceContract,
    NearDuplicateScanError,
    _fingerprint,
    _similarity,
    deterministic_result_payload,
    normalize_near_duplicate_text,
    scan_aihub_71748_near_duplicates,
    summarize_near_duplicates,
)


def _summary(training=(), validation=(), **kwargs):
    return summarize_near_duplicates(
        {"training": training, "validation": validation},
        **kwargs,
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("합성 질문입니다", "  합성   질문입니다  "),
        ("합성 질문\n입니다", "합성 질문 입니다"),
        ("Synthetic question", "Synthetic   question"),
    ],
)
def test_normalized_exact_variants_are_detected_but_excluded(first, second):
    result = _summary(training=[(first, "합성 답변 하나"), (second, "합성 답변 둘")])
    assert result["question"]["normalized_exact_excluded_pairs"] == 1
    assert result["question"]["candidate_groups"] == 0
    assert first not in json.dumps(result, ensure_ascii=False)


def test_nearly_equal_answers_are_candidates():
    first = "합성 답변은 안전한 테스트 문장으로 충분히 길게 작성되었습니다."
    second = "합성 답변은 안전한 테스트 문장으로 충분히 길게 작성되었습니다!"
    result = _summary(training=[("합성 질문 하나", first), ("합성 질문 둘", second)])
    assert result["answer"]["candidate_groups"] == 1


def test_nearly_equal_qa_pair_is_counted():
    first_q = "합성 질문은 충분히 길고 거의 같은 문장입니다."
    second_q = "합성 질문은 충분히 길고 거의 같은 문장입니다!"
    first_a = "합성 답변도 충분히 길고 거의 같은 문장입니다."
    second_a = "합성 답변도 충분히 길고 거의 같은 문장입니다!"
    result = _summary(training=[(first_q, first_a), (second_q, second_a)])
    assert result["qa_pair"]["candidate_groups"] == 1


def test_cross_split_near_pair_is_counted():
    question = "합성 교차 질문은 충분히 길게 만들어진 문장입니다."
    answer = "합성 교차 답변도 충분히 길게 만들어진 문장입니다."
    result = _summary(
        training=[(question, answer)],
        validation=[(question + "!", answer + "!")],
    )
    assert result["cross_split"]["candidate_groups"] == 1
    assert result["policy"]["label"] == "REVIEW_REQUIRED"


def test_low_similarity_and_different_length_are_rejected():
    result = _summary(
        training=[
            ("짧은 합성 질문", "짧은 합성 답변"),
            ("완전히 다른 어휘로 구성한 매우 긴 합성 입력 문장입니다", "별개의 응답 구조입니다"),
        ]
    )
    assert result["question"]["candidate_groups"] == 0
    assert result["answer"]["candidate_groups"] == 0


def test_long_string_is_bounded_to_aggregate_output():
    first = "합성장문 " * 2000
    second = ("합성장문 " * 1999) + "합성장문!"
    result = _summary(training=[(first, first), (second, second)])
    assert result["question"]["candidate_groups"] == 1
    assert first not in json.dumps(result, ensure_ascii=False)


def test_empty_and_whitespace_values_are_normalized_exclusions():
    result = _summary(training=[("", ""), ("   ", "\n")])
    assert result["question"]["candidate_groups"] == 0
    assert result["answer"]["candidate_groups"] == 0
    assert result["question"]["normalized_exact_excluded_pairs"] == 1


def test_null_and_unknown_record_shape_fail_closed():
    with pytest.raises(NearDuplicateScanError, match="^FIELD_TYPE_MISMATCH$"):
        _summary(training=[(None, None)])
    with pytest.raises(NearDuplicateScanError, match="^INVALID_RECORD_SHAPE$"):
        _summary(training=[("only one field",)])
    with pytest.raises(NearDuplicateScanError, match="^INVALID_RECORD_SHAPE$"):
        _summary(training=[{"unknown": "SYNTHETIC_MUST_NOT_LEAK"}])


def test_raw_exact_values_are_separately_excluded():
    result = _summary(training=[("synthetic exact", "synthetic exact") for _ in range(2)])
    assert result["question"]["raw_exact_excluded_pairs"] == 1
    assert result["answer"]["raw_exact_excluded_pairs"] == 1
    assert result["qa_pair"]["candidate_groups"] == 0


def test_similarity_pipeline_is_bounded_and_numeric():
    first = _fingerprint("합성 유사도 검증 문장입니다")
    second = _fingerprint("합성 유사도 검증 문장입니다!")
    assert first.character_ngrams and first.token_ngrams
    assert all(isinstance(item, int) for item in first.character_ngrams)
    assert isinstance(first.simhash, int) and len(first.minhash) == 16
    assert 0.0 <= _similarity(first, second) <= 1.0
    assert normalize_near_duplicate_text(" A\r\n  B ") == "A B"


def test_question_source_is_single_canonical_component():
    result = _summary(training=[("synthetic canonical question", "synthetic answer")])
    assert result["question_source"] == {
        "canonical_component": "sftdata",
        "sftlabel_question": "skipped_verified_exact_copy",
    }
    assert result["question"]["scanned"] == 1
    assert result["answer"]["scanned"] == 1


def test_deterministic_semantic_payload_ignores_elapsed_time():
    records = [(f"synthetic question {index}", f"synthetic answer {index}") for index in range(40)]
    first = _summary(training=records)
    second = _summary(training=reversed(records))
    assert deterministic_result_payload(first) == deterministic_result_payload(second)


def test_leak_guard_blocks_raw_and_substring_output():
    from src.data.safety import guard_safe_output

    raw = "SYNTHETIC_NEAR_DUPLICATE_RAW_VALUE"
    assert guard_safe_output({"status": "completed", "unsafe": raw}, raw)["error_code"] == "RAW_VALUE_LEAK_DETECTED"
    assert guard_safe_output({"status": "completed", "unsafe": raw[2:20]}, raw)["error_code"] == "RAW_VALUE_LEAK_DETECTED"


def _write_archive(root, split, prefix, component, records):
    directory = root / split / component
    directory.mkdir(parents=True, exist_ok=True)
    name = "VL.zip" if prefix == "VL" else f"{prefix}.synthetic.zip"
    with zipfile.ZipFile(directory / name, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"synthetic/{component}.json", json.dumps({"data_info": records}))


def _package(root):
    values = {
        ("Training", "TS_02", "sftdata"): [
            {"question": "Synthetic training question"},
            {"question": "Synthetic training question!"},
        ],
        ("Training", "TL_02", "sftlabel"): [
            {"answer": {"contents": "Synthetic training answer"}},
            {"answer": {"contents": "Synthetic training answer!"}},
        ],
        ("Validation", "VS_02", "sftdata"): [{"question": "Synthetic validation question"}],
        ("Validation", "VL", "sftlabel"): [
            {"answer": {"contents": "Synthetic validation answer"}},
        ],
    }
    for (split, prefix, component), records in values.items():
        _write_archive(root, split, prefix, component, records)
    return root


def test_scan_runs_exactly_once_without_label_question_payload_or_logs(
    tmp_path, monkeypatch, capsys, caplog
):
    import src.data.aihub_71748_near_duplicate as module

    monkeypatch.setattr(module, "EXPECTED_RECORDS", {"training": 2, "validation": 1})
    calls = 0
    original = module._scan_once

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "_scan_once", counted)
    with caplog.at_level(logging.DEBUG):
        result = scan_aihub_71748_near_duplicates(
            _package(tmp_path),
            execution_id="SYNTHETIC_SCAN",
        )
    captured = capsys.readouterr()
    encoded = json.dumps(result)
    assert calls == 1 and result["full_scan_count"] == 1 and result["status"] == "completed"
    assert "Synthetic training question" not in encoded
    assert "Synthetic training answer" not in encoded
    assert captured.out == "" and captured.err == "" and caplog.text == ""


def test_missing_root_is_blocked_before_scan(tmp_path):
    result = scan_aihub_71748_near_duplicates(
        tmp_path / "missing",
        execution_id="SYNTHETIC_MISSING",
    )
    assert result["status"] == "blocked"
    assert result["full_scan_count"] == 0
    assert result["execution_allowed"] is False


def test_invalid_contract_and_execution_id_fail_closed():
    with pytest.raises(NearDuplicateScanError, match="^INVALID_PERFORMANCE_CONTRACT$"):
        _summary(contract=NearDuplicatePerformanceContract(maximum_total_pairs=0))
    with pytest.raises(NearDuplicateScanError, match="^INVALID_EXECUTION_ID$"):
        _summary(execution_id="")
    with pytest.raises(NearDuplicateScanError, match="^INVALID_EXECUTION_ID$"):
        _summary(execution_id="unsafe execution id")
