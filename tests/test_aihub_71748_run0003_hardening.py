from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from src.data.processing.approval import (
    ProcessingApprovalError,
    consume_approval,
    finalize_approval,
    issue_approval,
    new_approval,
    retire_approval,
    validate_approval,
)
from src.data.processing.post_validation import (
    ALLOWED_OUTPUTS,
    DiskBudget,
    DiskGuard,
    FinalizationGate,
    PostValidationError,
    SourceSnapshot,
    generate_checksums,
    snapshot_source_metadata,
    validate_checksums,
    validate_finalization_gate,
    validate_jsonl_and_splits,
    validate_output_budget,
    validate_source_immutable,
)
from src.data.processing.processing_statistics import (
    ProcessingStatisticsError,
    detailed_statistics_schema,
    validate_detailed_statistics,
)
from src.data.processing.run_contract import (
    ExecutionCounters,
    ProcessingRunContract,
    RunContractError,
    RunRegistry,
    payload_session,
)
from src.data.processing.runtime_monitor import RuntimeMonitor, RuntimeMonitorError


STAMP = "2026-07-29T10:00:00+09:00"


def _contract() -> ProcessingRunContract:
    return ProcessingRunContract(
        "AIHUB-71748-SFT-PROCESSING-20260729-0003",
        "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0003",
        processing_allowed=True,
        payload_read_allowed=True,
        output_write_allowed=True,
        execution_allowed=True,
    )


def _approval():
    return new_approval(
        _contract(),
        immutable_git_commit="1" * 40,
        manifest_sha256="2" * 64,
        backend_fingerprint="3" * 64,
        preflight_evidence_fingerprint="4" * 64,
        approved_by="synthetic-only",
        approved_at=STAMP,
    )


def _record(instruction: str, output: str) -> dict[str, object]:
    return {"instruction": instruction, "input": None, "output": output, "system": None}


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")


def _output_fixture(root: Path) -> None:
    root.mkdir()
    _write_jsonl(root / "train.jsonl", [_record("train", "answer")])
    _write_jsonl(root / "validation.jsonl", [_record("validation", "answer")])
    (root / "manifest.yaml").write_text("synthetic: true\n", encoding="utf-8")
    (root / "statistics.json").write_text("{}", encoding="utf-8")
    (root / "processing-result.yaml").write_text("status: completed\n", encoding="utf-8")
    generate_checksums(root)


def test_run_0002_and_approval_0002_are_permanently_retired() -> None:
    contract = ProcessingRunContract(
        "AIHUB-71748-SFT-PROCESSING-20260729-0002",
        "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0002",
    )
    with pytest.raises(RunContractError, match="^RUN_ID_RETIRED$"):
        new_approval(
            contract,
            immutable_git_commit="1" * 40,
            manifest_sha256="2" * 64,
            backend_fingerprint="3" * 64,
            preflight_evidence_fingerprint="4" * 64,
            approved_by="synthetic-only",
            approved_at=STAMP,
        )


def test_processing_call_counter_is_single_use() -> None:
    counters = ExecutionCounters()
    counters.begin_processing()
    with pytest.raises(RunContractError, match="^PROCESSING_CALL_LIMIT_EXCEEDED$"):
        counters.begin_processing()


def test_payload_session_closes_and_second_session_is_blocked() -> None:
    counters = ExecutionCounters()
    with payload_session(counters):
        assert counters.active_payload_sessions == 1
    counters.validate_closed()
    with pytest.raises(RunContractError, match="^PAYLOAD_SESSION_LIMIT_EXCEEDED$"):
        with payload_session(counters):
            pass


def test_payload_session_active_and_unclosed_fail_closed() -> None:
    counters = ExecutionCounters()
    counters.open_payload_session()
    with pytest.raises(RunContractError, match="^PAYLOAD_SESSION_ALREADY_ACTIVE$"):
        counters.open_payload_session()
    with pytest.raises(RunContractError, match="^PAYLOAD_SESSION_NOT_CLOSED$"):
        counters.validate_closed()
    counters.close_payload_session()
    with pytest.raises(RunContractError, match="^PAYLOAD_SESSION_NOT_ACTIVE$"):
        counters.close_payload_session()


def test_run_registry_rejects_reuse_and_invalid_transition() -> None:
    registry = RunRegistry()
    run_id = _contract().run_id
    registry.register(run_id, "reserved")
    registry.transition(run_id, "reserved", "preflight_passed")
    with pytest.raises(RunContractError, match="^RUN_ID_ALREADY_USED$"):
        registry.register(run_id, "reserved")
    with pytest.raises(RunContractError, match="^RUN_STATE_TRANSITION_INVALID$"):
        registry.transition(run_id, "reserved", "approval_issued")


def test_approval_lifecycle_and_terminal_reuse(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    issued = issue_approval(path, _approval(), issued_at=STAMP)
    consumed = consume_approval(path, issued, consumed_at=STAMP)
    completed = finalize_approval(path, consumed, success=True, finalized_at=STAMP)
    assert completed.status == "completed"
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_ALREADY_FINALIZED$"):
        finalize_approval(path, completed, success=True, finalized_at=STAMP)


def test_approval_retirement_only_before_consumption() -> None:
    assert retire_approval(_approval()).status == "retired"
    issued = replace(_approval(), status="issued", issued_at=STAMP, checksum="")
    from src.data.processing.approval import approval_checksum

    issued = replace(issued, checksum=approval_checksum(issued))
    assert retire_approval(issued).status == "retired_before_consumption"
    consumed = replace(issued, status="consumed", consumed_at=STAMP, checksum="")
    consumed = replace(consumed, checksum=approval_checksum(consumed))
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_STATE_TRANSITION_INVALID$"):
        retire_approval(consumed)


@pytest.mark.parametrize("value", ["2026-07-29T10:00:00", "invalid"])
def test_approval_timezone_is_required(value: str) -> None:
    record = replace(_approval(), approved_at=value, checksum="")
    from src.data.processing.approval import approval_checksum

    record = replace(record, checksum=approval_checksum(record))
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_TIMESTAMP_INVALID$"):
        validate_approval(record, _contract())


def test_approval_timestamp_order_is_enforced() -> None:
    record = replace(
        _approval(), status="issued", approved_at="2026-07-29T11:00:00+09:00",
        issued_at="2026-07-29T10:00:00+09:00", checksum="",
    )
    from src.data.processing.approval import approval_checksum

    record = replace(record, checksum=approval_checksum(record))
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_TIMESTAMP_ORDER_INVALID$"):
        validate_approval(record, _contract())


@pytest.mark.parametrize(
    ("clock", "memory", "code"),
    [
        ([0.0, 1801.0], 1, "RUNTIME_HARD_LIMIT_EXCEEDED"),
        ([0.0, 0.0], 2048 * 1024 * 1024 + 1, "MEMORY_HARD_LIMIT_EXCEEDED"),
    ],
)
def test_runtime_hard_limits(clock: list[float], memory: int, code: str) -> None:
    values = iter(clock)
    with pytest.raises(RuntimeMonitorError, match=f"^{code}$"):
        RuntimeMonitor(clock=lambda: next(values), memory_provider=lambda: memory)


def test_runtime_soft_limits_are_recorded() -> None:
    times = iter([0.0, 1201.0, 1201.0])
    monitor = RuntimeMonitor(
        clock=lambda: next(times), memory_provider=lambda: 1536 * 1024 * 1024 + 1,
    )
    assert monitor.soft_runtime_triggered is True
    assert monitor.soft_memory_triggered is True


def test_memory_measurement_unavailable_is_fail_closed() -> None:
    with pytest.raises(RuntimeMonitorError, match="^MEMORY_MEASUREMENT_UNAVAILABLE$"):
        RuntimeMonitor(memory_provider=lambda: 0)


def test_disk_budget_before_and_during_write() -> None:
    with pytest.raises(PostValidationError, match="^DISK_BUDGET_INSUFFICIENT$"):
        DiskGuard(".", DiskBudget(minimum_free_bytes=10), provider=lambda _: 9)
    values = iter([100, 100, 100, 5])
    guard = DiskGuard(".", DiskBudget(minimum_free_bytes=10), provider=lambda _: next(values))
    guard.check(estimated_remaining_bytes=0, bytes_written=1)
    with pytest.raises(PostValidationError, match="^DISK_BUDGET_EXCEEDED_DURING_WRITE$"):
        guard.check(estimated_remaining_bytes=0, bytes_written=2)


def test_disk_measurement_failure_is_fail_closed() -> None:
    with pytest.raises(PostValidationError, match="^DISK_MEASUREMENT_FAILED$"):
        DiskGuard(".", provider=lambda _: (_ for _ in ()).throw(OSError()))


def test_output_allowlist_count_and_size(tmp_path: Path) -> None:
    root = tmp_path / "output"
    _output_fixture(root)
    assert validate_output_budget(root)["file_count"] == 6
    (root / "unknown.txt").write_text("x", encoding="utf-8")
    with pytest.raises(PostValidationError, match="^OUTPUT_FILE_NOT_ALLOWED$"):
        validate_output_budget(root)
    (root / "unknown.txt").unlink()
    with pytest.raises(PostValidationError, match="^OUTPUT_TOTAL_BYTES_EXCEEDED$"):
        validate_output_budget(root, maximum_total_bytes=1)


def test_checksum_revalidation_detects_tamper(tmp_path: Path) -> None:
    root = tmp_path / "output"
    _output_fixture(root)
    assert set(validate_checksums(root)) == set(ALLOWED_OUTPUTS) - {"checksums.sha256"}
    (root / "manifest.yaml").write_text("tampered: true\n", encoding="utf-8")
    with pytest.raises(PostValidationError, match="^CHECKSUM_MISMATCH$"):
        validate_checksums(root)


@pytest.mark.parametrize(
    ("record", "code"),
    [
        ({"bad": True}, "JSONL_FORBIDDEN_FIELD"),
        (_record(" ", "answer"), "JSONL_SCHEMA_MISMATCH"),
    ],
)
def test_jsonl_schema_failures(tmp_path: Path, record: dict[str, object], code: str) -> None:
    root = tmp_path / "output"
    root.mkdir()
    _write_jsonl(root / "train.jsonl", [record])
    _write_jsonl(root / "validation.jsonl", [_record("validation", "answer")])
    with pytest.raises(PostValidationError, match=f"^{code}$"):
        validate_jsonl_and_splits(
            root, expected_training=1, expected_validation=1,
            minimum_training=0, minimum_validation=0,
        )


def test_jsonl_malformed_and_count_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "output"
    root.mkdir()
    (root / "train.jsonl").write_text("{", encoding="utf-8")
    _write_jsonl(root / "validation.jsonl", [_record("validation", "answer")])
    with pytest.raises(PostValidationError, match="^JSONL_MALFORMED_RECORD$"):
        validate_jsonl_and_splits(root, expected_training=1, expected_validation=1, minimum_training=0, minimum_validation=0)
    _write_jsonl(root / "train.jsonl", [_record("train", "answer")])
    with pytest.raises(PostValidationError, match="^JSONL_COUNT_MISMATCH$"):
        validate_jsonl_and_splits(root, expected_training=2, expected_validation=1, minimum_training=0, minimum_validation=0)


@pytest.mark.parametrize("validation", [_record("train", "answer"), _record(" train ", " answer ")])
def test_cross_split_exact_and_normalized_leakage(tmp_path: Path, validation: dict[str, object]) -> None:
    root = tmp_path / "output"
    root.mkdir()
    _write_jsonl(root / "train.jsonl", [_record("train", "answer")])
    _write_jsonl(root / "validation.jsonl", [validation])
    code = "CROSS_SPLIT_EXACT_QA_PRESENT" if validation["instruction"] == "train" else "CROSS_SPLIT_NORMALIZED_QA_PRESENT"
    with pytest.raises(PostValidationError, match=f"^{code}$"):
        validate_jsonl_and_splits(root, expected_training=1, expected_validation=1, minimum_training=0, minimum_validation=0)


def test_source_snapshot_detects_added_removed_and_mutated(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    first = root / "one.zip"
    first.write_bytes(b"one")
    before = snapshot_source_metadata(root)
    second = root / "two.zip"
    second.write_bytes(b"two")
    with pytest.raises(PostValidationError, match="^SOURCE_FILE_ADDED$"):
        validate_source_immutable(before, snapshot_source_metadata(root))
    second.unlink()
    first.write_bytes(b"changed")
    with pytest.raises(PostValidationError, match="^SOURCE_DATASET_MUTATED$"):
        validate_source_immutable(before, snapshot_source_metadata(root))
    removed = SourceSnapshot(0, 0, "x", "y")
    with pytest.raises(PostValidationError, match="^SOURCE_FILE_REMOVED$"):
        validate_source_immutable(before, removed)


def test_statistics_contract_and_action_total() -> None:
    statistics = detailed_statistics_schema(run_id=_contract().run_id, approval_id=_contract().approval_id)
    statistics["input"].update({"Training": 1, "Validation": 0, "Total": 1})
    statistics["actions"]["keep"] = 1
    statistics["output"].update({"Training": 1, "Validation": 0, "Total": 1, "excluded_total": 0})
    validate_detailed_statistics(statistics)
    statistics["actions"]["keep"] = 0
    with pytest.raises(ProcessingStatisticsError, match="^STATISTICS_ACTION_MISMATCH$"):
        validate_detailed_statistics(statistics)


def test_finalization_gate_is_fail_closed() -> None:
    values = {
        "approval_consumed": True,
        "processing_calls": 1,
        "payload_open_sessions": 1,
        "payload_session_closed": True,
        "statistics_valid": True,
        "record_budget_valid": True,
        "exclusion_threshold_valid": True,
        "jsonl_valid": True,
        "split_valid": True,
        "checksum_valid": True,
        "source_immutable": True,
        "runtime_hard_limit_exceeded": False,
        "memory_hard_limit_exceeded": False,
        "disk_budget_valid": True,
        "output_budget_valid": True,
        "unresolved_records": 0,
        "malformed_records": 0,
        "join_failures": 0,
    }
    validate_finalization_gate(FinalizationGate(**values))
    values["approval_consumed"] = False
    with pytest.raises(PostValidationError, match="^FINALIZATION_GATE_FAILED$"):
        validate_finalization_gate(FinalizationGate(**values))
