import json
import logging
from pathlib import Path
import zipfile

import pytest
import yaml

import src.data.aihub_71748_leakage as module
from src.data.aihub_71748_leakage import (
    LeakagePerformanceContract,
    LeakageScanError,
    scan_aihub_71748_leakage,
    summarize_leakage,
)


def _records(training=(), validation=()):
    return {"training": training, "validation": validation}


def _prompts(evaluation=(), candidate=(), benchmark=()):
    return {
        "evaluation_framework": evaluation,
        "candidate_model": candidate,
        "benchmark": benchmark,
    }


def test_train_validation_exact_and_normalized_leakage_is_aggregate_only():
    result = summarize_leakage(
        _records(
            training=[("Synthetic question", "Synthetic question", "Synthetic answer")],
            validation=[(" Synthetic  question ", " Synthetic  question ", "Synthetic answer")],
        ),
        _prompts(["Evaluation prompt"], ["Candidate prompt"]),
    )
    assert result["train_validation"]["question"]["exact"]["pairs"] == 0
    assert result["train_validation"]["question"]["normalized"]["pairs"] == 1
    assert result["train_validation"]["answer"]["exact"]["pairs"] == 1
    assert result["train_validation"]["qa_pair"]["normalized"]["pairs"] == 1
    assert "Synthetic question" not in json.dumps(result, ensure_ascii=False)


def test_existing_near_evidence_is_reused_without_scan():
    result = summarize_leakage(
        _records(training=[("Question A", "Question A", "Answer A")]),
        _prompts(["Evaluation prompt"], ["Candidate prompt"]),
    )
    assert result["train_validation"]["question"]["near"] == {
        "groups": 40,
        "pairs": 45,
        "source": "approved_near_duplicate_run_0002",
        "reexecuted": False,
    }
    assert result["near_evidence"]["scan_reexecuted"] is False


def test_evaluation_and_candidate_prompt_matches_are_separate():
    result = summarize_leakage(
        _records(
            training=[("Evaluation prompt", "Evaluation prompt", "Candidate prompt")],
        ),
        _prompts(["Evaluation prompt"], ["Candidate prompt"]),
    )
    assert result["evaluation_framework"]["candidates"] == 1
    assert result["candidate_model"]["candidates"] == 1
    assert result["benchmark"] == {
        "sources": 0,
        "prompts_scanned": 0,
        "candidates": 0,
        "status": "not_available_local",
        "external_download": False,
    }


def test_synthetic_benchmark_prompt_match_is_aggregate_only():
    result = summarize_leakage(
        _records(training=[("Benchmark prompt", "Benchmark prompt", "Answer")]),
        _prompts(["Evaluation"], ["Candidate"], ["Benchmark prompt"]),
    )
    assert result["benchmark"]["sources"] == 1
    assert result["benchmark"]["prompts_scanned"] == 1
    assert result["benchmark"]["candidates"] == 1
    assert result["benchmark"]["status"] == "synthetic_test_only"
    assert "Benchmark prompt" not in json.dumps(result)


def test_unknown_prompt_source_and_component_mismatch_fail_closed():
    with pytest.raises(LeakageScanError, match="^UNKNOWN_PROMPT_SOURCE$"):
        summarize_leakage(
            _records(training=[("Question", "Question", "Answer")]),
            {**_prompts(["Evaluation"], ["Candidate"]), "unknown": ["Prompt"]},
        )
    with pytest.raises(LeakageScanError, match="^QUESTION_COMPONENT_MISMATCH$"):
        summarize_leakage(
            _records(training=[("Question A", "Question B", "Answer")]),
            _prompts(["Evaluation"], ["Candidate"]),
        )


def test_output_guard_blocks_prompt_or_dataset_value(monkeypatch):
    def unsafe_guard(_result, source):
        assert source
        return {"error_code": "RAW_VALUE_LEAK_DETECTED"}

    monkeypatch.setattr(module, "guard_safe_output", unsafe_guard)
    with pytest.raises(LeakageScanError, match="^RAW_VALUE_LEAK_DETECTED$"):
        summarize_leakage(
            _records(training=[("Question", "Question", "Answer")]),
            _prompts(["Evaluation"], ["Candidate"]),
        )


def test_timeout_and_cancellation_fail_closed():
    ticks = iter([0.0, 0.0, 1.0])
    with pytest.raises(LeakageScanError, match="^RUNTIME_BUDGET_EXCEEDED$"):
        summarize_leakage(
            _records(training=[("Question", "Question", "Answer")]),
            _prompts(["Evaluation"], ["Candidate"]),
            contract=LeakagePerformanceContract(runtime_budget_seconds=0.5),
            clock=lambda: next(ticks),
        )
    with pytest.raises(LeakageScanError, match="^SCAN_CANCELLED$"):
        summarize_leakage(
            _records(training=[("Question", "Question", "Answer")]),
            _prompts(["Evaluation"], ["Candidate"]),
            cancelled=lambda: True,
        )


def _write_archive(root, split, prefix, component, records):
    directory = root / split / component
    directory.mkdir(parents=True, exist_ok=True)
    name = "VL.zip" if prefix == "VL" else f"{prefix}.synthetic.zip"
    with zipfile.ZipFile(directory / name, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"synthetic/{component}.json", json.dumps({"data_info": records}))


def _package(root):
    values = {
        ("Training", "TS_02", "sftdata"): [{"question": "Training question"}],
        ("Training", "TL_02", "sftlabel"): [
            {"question": "Training question", "answer": {"contents": "Training answer"}},
        ],
        ("Validation", "VS_02", "sftdata"): [{"question": "Validation question"}],
        ("Validation", "VL", "sftlabel"): [
            {"question": "Validation question", "answer": {"contents": "Validation answer"}},
        ],
    }
    for (split, prefix, component), records in values.items():
        _write_archive(root, split, prefix, component, records)
    return root


def _repository(root: Path) -> Path:
    configs = root / "configs"
    configs.mkdir(parents=True)
    documents = {
        "evaluation-prompts.example.yaml": ["Evaluation prompt"],
        "eos-generation-prompts.example.yaml": ["Candidate prompt"],
    }
    for name, values in documents.items():
        payload = {
            "source": "synthetic",
            "pii_free": True,
            "prompts": [{"text": value} for value in values],
        }
        (configs / name).write_text(yaml.safe_dump(payload), encoding="utf-8")
    return root


def test_real_path_runs_once_without_raw_output_or_logs(tmp_path, monkeypatch, capsys, caplog):
    monkeypatch.setattr(module, "EXPECTED_RECORDS", {"training": 1, "validation": 1})
    calls = 0
    original = module._scan_once

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "_scan_once", counted)
    with caplog.at_level(logging.DEBUG):
        result = scan_aihub_71748_leakage(
            _package(tmp_path / "dataset"),
            _repository(tmp_path / "repository"),
            execution_id="SYNTHETIC_LEAKAGE_SCAN",
        )
    captured = capsys.readouterr()
    encoded = json.dumps(result)
    assert calls == 1 and result["full_scan_count"] == 1
    assert result["status"] == "completed"
    assert "Training question" not in encoded and "Candidate prompt" not in encoded
    assert captured.out == "" and captured.err == "" and caplog.text == ""


def test_missing_root_is_blocked_before_scan(tmp_path):
    result = scan_aihub_71748_leakage(
        tmp_path / "missing",
        tmp_path,
        execution_id="SYNTHETIC_MISSING",
    )
    assert result["status"] == "blocked"
    assert result["full_scan_count"] == 0
    assert result["execution_allowed"] is False


def test_invalid_prompt_contract_fails_closed(tmp_path):
    repository = _repository(tmp_path / "repository")
    path = repository / "configs/evaluation-prompts.example.yaml"
    path.write_text(yaml.safe_dump({"source": "unknown", "pii_free": True, "prompts": []}))
    with pytest.raises(LeakageScanError, match="^PROMPT_SOURCE_NOT_APPROVED$"):
        module._load_prompt_set(repository, Path("configs/evaluation-prompts.example.yaml"))
