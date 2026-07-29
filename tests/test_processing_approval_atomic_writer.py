from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path

import pytest

import src.data.processing.approval as approval_module
from src.data.processing.approval import (
    ProcessingApprovalError,
    issue_approval,
    load_approval,
    new_approval,
)
from src.data.processing.run_contract import ProcessingRunContract


STAMP = "2099-01-01T00:00:00+00:00"
RUN_ID = "AIHUB-71748-SFT-PROCESSING-20990101-9998"
APPROVAL_ID = "AIHUB-71748-SFT-PROCESSING-APPROVAL-20990101-9998"


def _contract() -> ProcessingRunContract:
    return ProcessingRunContract(
        RUN_ID, APPROVAL_ID, processing_allowed=True,
        payload_read_allowed=True, output_write_allowed=True,
    )


def _record():
    return new_approval(
        _contract(), execution_source_commit="1" * 40,
        governance_record_commit="2" * 40, manifest_sha256="3" * 64,
        backend_fingerprint="4" * 64, preflight_evidence_fingerprint="5" * 64,
        approved_by="synthetic-user", approved_at=STAMP,
    )


def test_atomic_issue_writes_canonical_json_and_preserves_checksum(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    issued = issue_approval(path, _record(), issued_at=STAMP, contract=_contract())
    assert path.read_bytes() == json.dumps(
        asdict(issued), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    assert load_approval(path) == issued
    assert not path.with_name(path.name + ".tmp").exists()


def test_atomic_issue_never_overwrites_final(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    first = issue_approval(path, _record(), issued_at=STAMP, contract=_contract())
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_ALREADY_ISSUED$"):
        issue_approval(path, _record(), issued_at=STAMP, contract=_contract())
    assert load_approval(path) == first


def test_atomic_issue_rejects_temporary_collision(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    path.with_name(path.name + ".tmp").write_text("occupied", encoding="utf-8")
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_TEMPORARY_COLLISION$"):
        issue_approval(path, _record(), issued_at=STAMP, contract=_contract())
    assert not path.exists()


def test_atomic_issue_allows_exactly_one_concurrent_success(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    def attempt() -> str:
        try:
            issue_approval(path, _record(), issued_at=STAMP, contract=_contract())
            return "issued"
        except ProcessingApprovalError as exc:
            return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert results.count("issued") == 1
    assert len(results) == 2
    assert load_approval(path).status == "issued"


def test_file_fsync_failure_is_not_success_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "approval.json"
    monkeypatch.setattr(approval_module.os, "fsync", lambda _: (_ for _ in ()).throw(OSError()))
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_ATOMIC_WRITE_FAILED$"):
        issue_approval(path, _record(), issued_at=STAMP, contract=_contract())
    assert not path.exists() and not path.with_name(path.name + ".tmp").exists()


def test_replace_failure_is_not_success_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "approval.json"
    monkeypatch.setattr(approval_module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError()))
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_ATOMIC_WRITE_FAILED$"):
        issue_approval(path, _record(), issued_at=STAMP, contract=_contract())
    assert not path.exists() and not path.with_name(path.name + ".tmp").exists()


def test_serialization_failure_creates_no_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "approval.json"
    monkeypatch.setattr(
        approval_module, "_canonical_record_bytes",
        lambda _: (_ for _ in ()).throw(ProcessingApprovalError("APPROVAL_ATOMIC_WRITE_FAILED")),
    )
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_ATOMIC_WRITE_FAILED$"):
        issue_approval(path, _record(), issued_at=STAMP, contract=_contract())
    assert not path.exists() and not path.with_name(path.name + ".tmp").exists()


def test_cleanup_failure_is_reported_as_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "approval.json"
    monkeypatch.setattr(approval_module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(
        approval_module.Path, "unlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_ISSUANCE_INCOMPLETE$"):
        issue_approval(path, _record(), issued_at=STAMP, contract=_contract())
    assert not path.exists()


def test_directory_sync_failure_is_incomplete_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "approval.json"
    monkeypatch.setattr(
        approval_module, "_sync_parent_directory",
        lambda _: (_ for _ in ()).throw(ProcessingApprovalError("APPROVAL_DIRECTORY_SYNC_FAILED")),
    )
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_DIRECTORY_SYNC_FAILED$"):
        issue_approval(path, _record(), issued_at=STAMP, contract=_contract())
    assert path.exists() and not path.with_name(path.name + ".tmp").exists()


def test_windows_directory_sync_policy_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(approval_module, "_directory_fsync_supported", lambda: False)
    monkeypatch.setattr(
        approval_module.os, "open",
        lambda *_: (_ for _ in ()).throw(AssertionError("directory open must not occur")),
    )
    approval_module._sync_parent_directory(tmp_path / "approval.json")
