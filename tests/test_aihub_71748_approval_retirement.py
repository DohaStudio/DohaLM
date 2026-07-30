from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

import scripts.datasets.retire_aihub_71748_sft_approval as cli
import src.data.processing.aihub_71748_processor as processor_module
import src.data.processing.approval as approval_module
from src.data.processing.approval import (
    ProcessingApprovalError,
    approval_checksum,
    approval_fingerprint,
    approval_retirement_evidence_path,
    consume_approval,
    issue_approval,
    load_approval,
    load_approval_retirement_evidence,
    new_approval,
    retire_approval_file,
)
from src.data.processing.run_contract import ExecutionCounters, ProcessingRunContract
from src.data.processing.runtime_request_artifact import (
    RuntimeRequestArtifactError,
    validate_runtime_execution_request_issuance,
)


RUN_ID = "AIHUB-71748-SFT-PROCESSING-20990101-9998"
APPROVAL_ID = "AIHUB-71748-SFT-PROCESSING-APPROVAL-20990101-9998"
STAMP = "2099-01-01T00:00:00+00:00"
RETIRED_AT = "2099-01-01T01:00:00+00:00"
REASON = "RUNTIME_REQUEST_GIT_LINEAGE_MISMATCH"


def _contract() -> ProcessingRunContract:
    return ProcessingRunContract(
        RUN_ID,
        APPROVAL_ID,
        processing_allowed=True,
        payload_read_allowed=True,
        output_write_allowed=True,
        execution_allowed=False,
        synthetic=True,
    )


def _issued(path: Path) -> tuple[object, str, str, str]:
    record = new_approval(
        _contract(),
        execution_source_commit="1" * 40,
        governance_record_commit="2" * 40,
        manifest_sha256="3" * 64,
        backend_fingerprint="4" * 64,
        preflight_evidence_fingerprint="5" * 64,
        approved_by="synthetic-only",
        approved_at=STAMP,
    )
    issued = issue_approval(path, record, issued_at=STAMP, contract=_contract())
    file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return issued, file_sha, issued.checksum, approval_fingerprint(issued)


def _retire(path: Path, *, counters: ExecutionCounters | None = None):
    issued, file_sha, checksum, fingerprint = _issued(path)
    retired = retire_approval_file(
        path,
        expected_approval_id=APPROVAL_ID,
        expected_run_id=RUN_ID,
        expected_file_sha256=file_sha,
        expected_checksum=checksum,
        expected_stable_fingerprint=fingerprint,
        retired_at=RETIRED_AT,
        reason_code=REASON,
        counters=counters,
    )
    return issued, retired


def _write_record(path: Path, record: object) -> None:
    path.write_text(
        json.dumps(asdict(record), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _assert_no_residue(path: Path) -> None:
    assert not path.with_name(path.name + ".lifecycle.lock").exists()
    assert not path.with_name(path.name + ".retirement.tmp").exists()
    assert not path.with_name(path.name + ".retirement-evidence.tmp").exists()
    assert not path.with_name(path.name + ".retirement-link-probe").exists()


def test_retire_issued_approval_atomically_with_separate_evidence(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    counters = ExecutionCounters(approval_issue_calls=1)
    issued, retired = _retire(path, counters=counters)

    assert issued.status == "issued"
    assert retired == load_approval(path)
    assert retired.status == "retired_before_consumption"
    assert retired.consumed is retired.execution_allowed is False
    assert approval_fingerprint(retired) == approval_fingerprint(issued)
    assert retired.checksum == approval_checksum(retired)
    evidence = load_approval_retirement_evidence(approval_retirement_evidence_path(path))
    assert evidence.retired_at == RETIRED_AT
    assert evidence.reason_code == REASON
    assert evidence.before_checksum == issued.checksum
    assert evidence.after_checksum == retired.checksum
    assert evidence.after_file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert counters.approval_issue_calls == 1
    assert counters.approval_consume_calls == counters.runtime_request_creations == 0
    _assert_no_residue(path)


@pytest.mark.parametrize(
    ("status", "consumed", "issued_at", "consumed_at", "completed_at", "failed_at", "error"),
    [
        ("prepared_not_issued", False, None, None, None, None, "STATUS_INVALID"),
        ("consumed", True, STAMP, STAMP, None, None, "ALREADY_CONSUMED"),
        ("completed", True, STAMP, STAMP, STAMP, None, "ALREADY_CONSUMED"),
        ("failed", False, STAMP, None, None, STAMP, "STATUS_INVALID"),
        ("retired_not_issued", False, None, None, None, None, "STATUS_INVALID"),
        ("retired_before_consumption", False, STAMP, None, None, None, "STATUS_INVALID"),
        ("retired_issue_incomplete", False, STAMP, None, None, None, "STATUS_INVALID"),
    ],
)
def test_invalid_lifecycle_states_fail_closed(
    tmp_path: Path,
    status: str,
    consumed: bool,
    issued_at: str | None,
    consumed_at: str | None,
    completed_at: str | None,
    failed_at: str | None,
    error: str,
) -> None:
    path = tmp_path / "approval.json"
    issued, _, _, _ = _issued(path)
    changed = replace(
        issued,
        status=status,
        consumed=consumed,
        issued_at=issued_at,
        consumed_at=consumed_at,
        completed_at=completed_at,
        failed_at=failed_at,
        checksum="",
    )
    changed = replace(changed, checksum=approval_checksum(changed))
    _write_record(path, changed)
    file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ProcessingApprovalError, match=error):
        retire_approval_file(
            path,
            expected_approval_id=APPROVAL_ID,
            expected_run_id=RUN_ID,
            expected_file_sha256=file_sha,
            retired_at=RETIRED_AT,
            reason_code=REASON,
        )
    assert path.read_bytes() == json.dumps(
        asdict(changed), sort_keys=True, separators=(",", ":"),
    ).encode()
    _assert_no_residue(path)


def test_execution_allowed_approval_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    issued, _, _, _ = _issued(path)
    changed = replace(issued, execution_allowed=True, checksum="")
    changed = replace(changed, checksum=approval_checksum(changed))
    _write_record(path, changed)
    with pytest.raises(ProcessingApprovalError, match="STATUS_INVALID"):
        retire_approval_file(
            path,
            expected_approval_id=APPROVAL_ID,
            expected_run_id=RUN_ID,
            expected_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            retired_at=RETIRED_AT,
            reason_code=REASON,
        )


@pytest.mark.parametrize("mismatch", ["file", "checksum", "fingerprint", "run", "approval"])
def test_expected_integrity_and_identity_mismatches_are_distinct(
    tmp_path: Path,
    mismatch: str,
) -> None:
    path = tmp_path / "approval.json"
    _, file_sha, checksum, fingerprint = _issued(path)
    arguments = {
        "expected_approval_id": APPROVAL_ID,
        "expected_run_id": RUN_ID,
        "expected_file_sha256": file_sha,
        "expected_checksum": checksum,
        "expected_stable_fingerprint": fingerprint,
        "retired_at": RETIRED_AT,
        "reason_code": REASON,
    }
    expected = {
        "file": "ARTIFACT_CHANGED",
        "checksum": "CHECKSUM_MISMATCH",
        "fingerprint": "FINGERPRINT_MISMATCH",
        "run": "IDENTITY_MISMATCH",
        "approval": "IDENTITY_MISMATCH",
    }[mismatch]
    arguments[{
        "file": "expected_file_sha256",
        "checksum": "expected_checksum",
        "fingerprint": "expected_stable_fingerprint",
        "run": "expected_run_id",
        "approval": "expected_approval_id",
    }[mismatch]] = "0" * 64 if mismatch in {"file", "checksum", "fingerprint"} else "wrong"
    with pytest.raises(ProcessingApprovalError, match=expected):
        retire_approval_file(path, **arguments)  # type: ignore[arg-type]
    assert load_approval(path).status == "issued"
    _assert_no_residue(path)


@pytest.mark.parametrize("content", [b"not-json", b"{}"])
def test_corrupt_or_unknown_schema_is_rejected(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "approval.json"
    path.write_bytes(content)
    with pytest.raises(ProcessingApprovalError, match="ARTIFACT_CHANGED"):
        retire_approval_file(
            path,
            expected_approval_id=APPROVAL_ID,
            expected_run_id=RUN_ID,
            expected_file_sha256=hashlib.sha256(content).hexdigest(),
            retired_at=RETIRED_AT,
            reason_code=REASON,
        )
    assert path.read_bytes() == content


def test_competing_artifact_change_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    _, file_sha, checksum, fingerprint = _issued(path)

    def compete(target: Path) -> None:
        target.write_bytes(b"competing-artifact")

    monkeypatch.setattr(approval_module, "_retirement_compare_and_swap_hook", compete)
    with pytest.raises(ProcessingApprovalError, match="ARTIFACT_CHANGED"):
        retire_approval_file(
            path,
            expected_approval_id=APPROVAL_ID,
            expected_run_id=RUN_ID,
            expected_file_sha256=file_sha,
            expected_checksum=checksum,
            expected_stable_fingerprint=fingerprint,
            retired_at=RETIRED_AT,
            reason_code=REASON,
        )
    assert path.read_bytes() == b"competing-artifact"
    assert not approval_retirement_evidence_path(path).exists()
    _assert_no_residue(path)


def test_concurrent_retirement_has_exactly_one_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    _, file_sha, checksum, fingerprint = _issued(path)
    entered = Event()
    release = Event()

    def pause(_target: Path) -> None:
        entered.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(approval_module, "_retirement_compare_and_swap_hook", pause)

    def retire() -> str:
        try:
            retire_approval_file(
                path,
                expected_approval_id=APPROVAL_ID,
                expected_run_id=RUN_ID,
                expected_file_sha256=file_sha,
                expected_checksum=checksum,
                expected_stable_fingerprint=fingerprint,
                retired_at=RETIRED_AT,
                reason_code=REASON,
            )
        except ProcessingApprovalError as exc:
            return str(exc)
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(retire)
        assert entered.wait(timeout=5)
        second = executor.submit(retire)
        second_result = second.result(timeout=5)
        release.set()
        first_result = first.result(timeout=5)
    assert [first_result, second_result].count("success") == 1
    assert "APPROVAL_RETIREMENT_LOCK_COLLISION" in {first_result, second_result}
    assert load_approval(path).status == "retired_before_consumption"
    _assert_no_residue(path)


def test_lock_and_temporary_collisions_preserve_issued_artifact(tmp_path: Path) -> None:
    for suffix, error in (
        (".lifecycle.lock", "LOCK_COLLISION"),
        (".retirement.tmp", "TEMPORARY_COLLISION"),
    ):
        root = tmp_path / suffix.removeprefix(".")
        root.mkdir()
        path = root / "approval.json"
        _, file_sha, checksum, fingerprint = _issued(path)
        collision = path.with_name(path.name + suffix)
        collision.write_text("occupied", encoding="utf-8")
        with pytest.raises(ProcessingApprovalError, match=error):
            retire_approval_file(
                path,
                expected_approval_id=APPROVAL_ID,
                expected_run_id=RUN_ID,
                expected_file_sha256=file_sha,
                expected_checksum=checksum,
                expected_stable_fingerprint=fingerprint,
                retired_at=RETIRED_AT,
                reason_code=REASON,
            )
        assert load_approval(path).status == "issued"
        assert collision.read_text(encoding="utf-8") == "occupied"


def test_replace_failure_preserves_issued_and_cleans_residue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    _, file_sha, checksum, fingerprint = _issued(path)
    monkeypatch.setattr(
        approval_module.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("synthetic")),
    )
    with pytest.raises(ProcessingApprovalError, match="ATOMIC_WRITE_FAILED"):
        retire_approval_file(
            path,
            expected_approval_id=APPROVAL_ID,
            expected_run_id=RUN_ID,
            expected_file_sha256=file_sha,
            expected_checksum=checksum,
            expected_stable_fingerprint=fingerprint,
            retired_at=RETIRED_AT,
            reason_code=REASON,
        )
    assert load_approval(path).status == "issued"
    _assert_no_residue(path)


def test_retirement_temp_fsync_failure_preserves_issued_and_cleans_residue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    _, file_sha, checksum, fingerprint = _issued(path)
    monkeypatch.setattr(
        approval_module.os,
        "fsync",
        lambda _fd: (_ for _ in ()).throw(OSError("synthetic")),
    )
    with pytest.raises(ProcessingApprovalError, match="ATOMIC_WRITE_FAILED"):
        retire_approval_file(
            path,
            expected_approval_id=APPROVAL_ID,
            expected_run_id=RUN_ID,
            expected_file_sha256=file_sha,
            expected_checksum=checksum,
            expected_stable_fingerprint=fingerprint,
            retired_at=RETIRED_AT,
            reason_code=REASON,
        )
    assert load_approval(path).status == "issued"
    _assert_no_residue(path)


def test_short_write_is_detected() -> None:
    stream = SimpleNamespace(write=lambda payload: len(payload) - 1)
    with pytest.raises(OSError, match="short write"):
        approval_module._write_complete(stream, b"synthetic")


def test_flush_failure_is_detected_before_fsync(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"fsync": 0}
    stream = SimpleNamespace(
        flush=lambda: (_ for _ in ()).throw(OSError("synthetic flush")),
        fileno=lambda: 1,
    )
    monkeypatch.setattr(
        approval_module.os,
        "fsync",
        lambda _fd: calls.__setitem__("fsync", calls["fsync"] + 1),
    )
    with pytest.raises(OSError, match="synthetic flush"):
        approval_module._flush_and_sync(stream)
    assert calls["fsync"] == 0


def test_evidence_publish_unsupported_is_detected_before_replace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    _, file_sha, checksum, fingerprint = _issued(path)
    monkeypatch.setattr(
        approval_module,
        "_publish_no_replace",
        lambda *_args: (_ for _ in ()).throw(
            ProcessingApprovalError("APPROVAL_NO_REPLACE_UNSUPPORTED"),
        ),
    )
    with pytest.raises(ProcessingApprovalError, match="RETIREMENT_UNSUPPORTED"):
        retire_approval_file(
            path,
            expected_approval_id=APPROVAL_ID,
            expected_run_id=RUN_ID,
            expected_file_sha256=file_sha,
            expected_checksum=checksum,
            expected_stable_fingerprint=fingerprint,
            retired_at=RETIRED_AT,
            reason_code=REASON,
        )
    assert load_approval(path).status == "issued"
    assert not approval_retirement_evidence_path(path).exists()
    _assert_no_residue(path)


def test_directory_sync_failure_is_incomplete_but_non_reusable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    _, file_sha, checksum, fingerprint = _issued(path)
    monkeypatch.setattr(
        approval_module,
        "_sync_parent_directory",
        lambda _path: (_ for _ in ()).throw(
            ProcessingApprovalError("APPROVAL_DIRECTORY_SYNC_FAILED"),
        ),
    )
    with pytest.raises(ProcessingApprovalError, match="DIRECTORY_SYNC_FAILED"):
        retire_approval_file(
            path,
            expected_approval_id=APPROVAL_ID,
            expected_run_id=RUN_ID,
            expected_file_sha256=file_sha,
            expected_checksum=checksum,
            expected_stable_fingerprint=fingerprint,
            retired_at=RETIRED_AT,
            reason_code=REASON,
        )
    assert load_approval(path).status == "retired_before_consumption"
    assert approval_retirement_evidence_path(path).is_file()
    _assert_no_residue(path)


def test_unlock_failure_is_incomplete_and_leaves_retired_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    _, file_sha, checksum, fingerprint = _issued(path)
    lock_path = path.with_name(path.name + ".lifecycle.lock")
    original_unlink = Path.unlink

    def fail_unlock(candidate: Path, *args: object, **kwargs: object) -> None:
        if candidate == lock_path:
            raise OSError("synthetic unlock")
        original_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_unlock)
    with pytest.raises(ProcessingApprovalError, match="RETIREMENT_INCOMPLETE"):
        retire_approval_file(
            path,
            expected_approval_id=APPROVAL_ID,
            expected_run_id=RUN_ID,
            expected_file_sha256=file_sha,
            expected_checksum=checksum,
            expected_stable_fingerprint=fingerprint,
            retired_at=RETIRED_AT,
            reason_code=REASON,
        )
    assert load_approval(path).status == "retired_before_consumption"
    assert approval_retirement_evidence_path(path).is_file()
    assert lock_path.is_file()


def test_unsupported_platform_has_no_overwrite_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    _, file_sha, checksum, fingerprint = _issued(path)
    monkeypatch.setattr(approval_module, "_approval_platform", lambda: "unsupported")
    with pytest.raises(ProcessingApprovalError, match="RETIREMENT_UNSUPPORTED"):
        retire_approval_file(
            path,
            expected_approval_id=APPROVAL_ID,
            expected_run_id=RUN_ID,
            expected_file_sha256=file_sha,
            expected_checksum=checksum,
            expected_stable_fingerprint=fingerprint,
            retired_at=RETIRED_AT,
            reason_code=REASON,
        )
    assert load_approval(path).status == "issued"


def test_retired_approval_is_rejected_by_runtime_request_validator(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    _retire(path)
    with pytest.raises(RuntimeRequestArtifactError, match="APPROVAL_NOT_ISSUED"):
        validate_runtime_execution_request_issuance(
            repository_root=tmp_path,
            processed_root=tmp_path,
            contract=_contract(),
            approval_path=path,
            initial_evidence_path=tmp_path / "initial.json",
            refresh_evidence_path=tmp_path / "refresh.json",
            initial_evidence_fingerprint="6" * 64,
            refresh_evidence_fingerprint="7" * 64,
        )


def test_retired_approval_is_rejected_by_consume_before_runtime_validation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    _, retired = _retire(path)
    counters = ExecutionCounters()
    with pytest.raises(ProcessingApprovalError, match="APPROVAL_ALREADY_CONSUMED"):
        consume_approval(
            path,
            retired,
            consumed_at=RETIRED_AT,
            contract=_contract(),
            runtime_request=SimpleNamespace(),  # type: ignore[arg-type]
            counters=counters,
        )
    assert counters.approval_consume_calls == 0
    assert counters.runtime_execution_gate_activations == 0


def test_retired_approval_is_rejected_before_processing_discovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    _, retired = _retire(path)
    calls = {"discover": 0}
    monkeypatch.setattr(
        processor_module,
        "validate_aihub_71748_processing_manifest",
        lambda _manifest: None,
    )
    monkeypatch.setattr(
        processor_module,
        "validate_approval_file",
        lambda _path, _contract: retired,
    )
    monkeypatch.setattr(
        processor_module,
        "discover_sft_sources",
        lambda _root: calls.__setitem__("discover", calls["discover"] + 1),
    )
    counters = ExecutionCounters()
    with pytest.raises(ProcessingApprovalError, match="APPROVAL_ALREADY_CONSUMED"):
        processor_module.execute_approved_processing(
            package_root=tmp_path / "package",
            run_root=tmp_path / "run",
            repository_root=tmp_path,
            manifest={},
            contract=_contract(),
            approval_path=path,
            manifest_sha256=retired.manifest_sha256,
            backend_git_commit=retired.execution_source_commit,
            backend_fingerprint=retired.backend_fingerprint,
            preflight_evidence_fingerprint=retired.preflight_evidence_fingerprint,
            runtime_request=SimpleNamespace(),  # type: ignore[arg-type]
            counters=counters,
        )
    assert calls["discover"] == 0
    assert counters.processing_engine_calls == 0
    assert counters.payload_sessions == 0
    assert counters.zip_entry_opens == 0
    assert counters.json_parser_calls == 0


def test_existing_runtime_request_blocks_retirement(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    path = processed / "approvals" / f"{APPROVAL_ID}.json"
    path.parent.mkdir(parents=True)
    _, file_sha, checksum, fingerprint = _issued(path)
    runtime_request = (
        processed / "runtime-evidence" / APPROVAL_ID / "runtime-execution-request.json"
    )
    runtime_request.parent.mkdir(parents=True)
    runtime_request.write_text("synthetic-existing-request", encoding="utf-8")
    with pytest.raises(ProcessingApprovalError, match="STATUS_INVALID"):
        retire_approval_file(
            path,
            expected_approval_id=APPROVAL_ID,
            expected_run_id=RUN_ID,
            expected_file_sha256=file_sha,
            expected_checksum=checksum,
            expected_stable_fingerprint=fingerprint,
            retired_at=RETIRED_AT,
            reason_code=REASON,
        )
    assert load_approval(path).status == "issued"
    assert runtime_request.read_text(encoding="utf-8") == "synthetic-existing-request"


def test_cli_is_retirement_only_and_does_not_run_other_surfaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    processed = tmp_path / "processed"
    path = processed / "approvals" / f"{APPROVAL_ID}.json"
    path.parent.mkdir(parents=True)
    _, file_sha, checksum, fingerprint = _issued(path)
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text("synthetic: true\n", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "resolve_dataset_mapping",
        lambda **_kwargs: SimpleNamespace(processed_root=processed),
    )
    args = [
        "--mapping", str(mapping),
        "--approval-artifact", str(path),
        "--run-id", RUN_ID,
        "--approval-id", APPROVAL_ID,
        "--expected-file-sha256", file_sha,
        "--expected-checksum", checksum,
        "--expected-stable-fingerprint", fingerprint,
        "--reason-code", REASON,
        "--retirement-only",
    ]
    assert cli.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "approval_retired_before_consumption"
    assert output["approval_consumed"] is output["runtime_request_created"] is False
    assert output["processing_calls"] == output["payload_reads"] == 0
    assert output["execution_allowed"] is False
    assert "--retired-at" not in cli.build_parser().format_help()
