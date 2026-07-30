from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import json
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import pytest

import scripts.datasets.refresh_aihub_71748_sft_approval_run as refresh_cli
from src.data.aihub_71748_approval_refresh import (
    ACTIVE_RUN_STATUS,
    ActiveRunRegistryState,
    ApprovalRefreshEvidence,
    approval_refresh_evidence_fingerprint,
    build_refresh_approval_draft,
    canonical_approval_refresh_evidence_path,
    deserialize_approval_refresh_evidence,
    validate_active_run_for_approval_refresh,
    validate_approval_refresh_evidence,
    validate_governance_refresh_checkout,
    validate_previous_preflight_evidence,
    write_approval_refresh_evidence_file,
)
from src.data.aihub_71748_processing_preflight import (
    BACKEND_PATHS,
    MANIFEST_PATH,
    PreflightEvidence,
    ProcessingPreflightError,
    preflight_evidence_fingerprint,
)
from src.data.processing.aihub_71748_mapping import ResolvedDatasetMapping


RUN_ID = "SYNTHETIC-RUN-0001"
APPROVAL_ID = "SYNTHETIC-APPROVAL-0001"
STAMP = datetime(2099, 1, 1, tzinfo=timezone.utc)


class Registry:
    def __init__(self, state: ActiveRunRegistryState | None) -> None:
        self.state = state

    def read_active_run(self, run_id: str, approval_id: str) -> ActiveRunRegistryState:
        if self.state is None:
            raise KeyError(run_id)
        return self.state


def _state(**changes: object) -> ActiveRunRegistryState:
    state = ActiveRunRegistryState(
        run_id=RUN_ID, approval_id=APPROVAL_ID, run_status=ACTIVE_RUN_STATUS,
        previous_preflight_evidence_fingerprint="1" * 64,
        approval_id_unused=True, approval_artifact_exists=False,
        approval_issue_calls=0, approval_consume_calls=0,
        runtime_request_exists=False, processing_started=False,
        payload_reads=0, processing_calls=0, output_writes=0,
        conflicting_evidence_count=0,
    )
    return replace(state, **changes)


def _mapping(tmp_path: Path) -> ResolvedDatasetMapping:
    source = tmp_path / "external" / "AIHUB-71748"
    source.mkdir(parents=True)
    return ResolvedDatasetMapping(
        dataset_id="AIHUB-71748", component="SFT", source_root=source,
        processed_root=tmp_path / "processed", resolution_source="synthetic",
    )


def _evidence(**changes: object) -> ApprovalRefreshEvidence:
    evidence = ApprovalRefreshEvidence(
        schema_version=1, validation_phase="approval_refresh",
        run_id=RUN_ID, approval_id=APPROVAL_ID,
        previous_preflight_evidence_fingerprint="1" * 64,
        execution_source_commit="2" * 40, governance_record_commit="3" * 40,
        manifest_sha256="4" * 64, backend_fingerprint="5" * 64,
        lineage={
            "result_code": "DIRECT_ANCESTRY_VALID", "direct_ancestry": True,
            "squash_merge_mode": False, "execution_surface_file_count": 10,
            "execution_surface_paths_equal": True, "execution_surface_blobs_equal": True,
            "manifest_fingerprint_equal": True, "backend_fingerprint_equal": True,
            "governance_reachable_from_origin_develop": True, "valid": True,
        },
        mapping_identity={
            "dataset_id": "AIHUB-71748", "component": "SFT", "root_type": "external",
            "repository_internal": False, "read_only": True,
        },
        source_snapshot={
            "zip_count": 55, "total_bytes": 17_256_335_769,
            "filename_aggregate": "6" * 64, "modified_time_aggregate": "7" * 64,
        },
        registry_state={
            "run_status": "preflight_passed", "run_id_unused": False,
            "approval_id_unused": True, "conflicting_evidence_count": 0,
        },
        runtime_state={
            "approval_artifact_exists": False, "approval_issue_calls": 0,
            "approval_consume_calls": 0, "runtime_request_exists": False,
            "processing_started": False, "payload_reads": 0,
            "processing_calls": 0, "output_writes": 0,
        },
        output_state={
            "final_exists": False, "staging_exists": False, "failed_exists": False,
            "quarantine_exists": False, "parent_probe_passed": True,
            "parent_probe_residue_count": 0,
        },
        resource_state={
            "free_disk_bytes": 5_000_000_000, "memory_provider_available": True,
            "runtime_provider_available": True, "current_rss_bytes": 1,
        },
        runtime_budget={"soft_limit_seconds": 1200, "hard_limit_seconds": 1800},
        memory_budget={"soft_limit_mib": 1536, "hard_limit_mib": 2048},
        disk_budget={"minimum_free_bytes": 4_294_967_296, "staging_multiplier": 2, "safety_margin_ratio": 0.25},
        record_budget={"expected_training": 10580, "expected_validation": 1322, "expected_total": 11902, "maximum_total": 11902},
        output_budget={"expected_files": 6, "maximum_files": 6, "maximum_total_bytes": 536_870_912},
        zero_call_state={
            "approval_issue_calls": 0, "approval_consume_calls": 0,
            "runtime_request_creations": 0, "runtime_execution_gate_activations": 0,
            "processing_engine_calls": 0, "payload_sessions": 0, "zip_entry_opens": 0,
            "archive_member_enumerations": 0, "json_parser_calls": 0,
            "record_parser_calls": 0, "join_calls": 0, "policy_dispatch_calls": 0,
            "output_writer_calls": 0, "checksum_calls": 0, "atomic_finalization_calls": 0,
        },
        generated_at=STAMP.isoformat(), expires_at=(STAMP + timedelta(hours=1)).isoformat(),
    )
    return replace(evidence, **changes)


def _validate(evidence: ApprovalRefreshEvidence, *, now: datetime = STAMP) -> None:
    validate_approval_refresh_evidence(
        evidence, expected_fingerprint=approval_refresh_evidence_fingerprint(evidence),
        expected_run_id=RUN_ID, expected_approval_id=APPROVAL_ID,
        expected_execution_source_commit="2" * 40,
        expected_governance_record_commit="3" * 40,
        expected_manifest_sha256="4" * 64, expected_backend_fingerprint="5" * 64,
        expected_previous_preflight_fingerprint="1" * 64, now=now,
    )


def _writer_document() -> dict[str, object]:
    generated = datetime.now(timezone.utc)
    evidence = _evidence(
        generated_at=generated.isoformat(),
        expires_at=(generated + timedelta(hours=1)).isoformat(),
    )
    fingerprint = approval_refresh_evidence_fingerprint(evidence)
    return {
        **asdict(evidence),
        "fingerprint": fingerprint,
        "approval_draft": build_refresh_approval_draft(
            evidence, evidence_fingerprint=fingerprint,
        ),
        "status": "approval_refresh_validated",
        "approval_issued": False,
        "approval_consumed": False,
        "runtime_request_created": False,
        "payload_reads": 0,
        "processing_calls": 0,
        "output_writes": 0,
        "execution_allowed": False,
    }


def test_refresh_writer_publishes_and_reloads_canonical_document(tmp_path: Path) -> None:
    document = _writer_document()
    target = canonical_approval_refresh_evidence_path(tmp_path, RUN_ID)
    result = write_approval_refresh_evidence_file(
        target, document, expected_fingerprint=str(document["fingerprint"]),
    )
    assert result == target
    assert json.loads(target.read_text(encoding="utf-8")) == document
    assert len(hashlib.sha256(target.read_bytes()).hexdigest()) == 64
    assert not target.with_name(target.name + ".tmp").exists()


def test_refresh_writer_preserves_existing_final(tmp_path: Path) -> None:
    document = _writer_document()
    target = canonical_approval_refresh_evidence_path(tmp_path, RUN_ID)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"existing-final")
    with pytest.raises(ProcessingPreflightError, match="ALREADY_EXISTS"):
        write_approval_refresh_evidence_file(
            target, document, expected_fingerprint=str(document["fingerprint"]),
        )
    assert target.read_bytes() == b"existing-final"


def test_refresh_writer_concurrent_publishers_allow_one_success(tmp_path: Path) -> None:
    document = _writer_document()
    target = canonical_approval_refresh_evidence_path(tmp_path, RUN_ID)

    def publish() -> str:
        try:
            write_approval_refresh_evidence_file(
                target, document, expected_fingerprint=str(document["fingerprint"]),
            )
        except ProcessingPreflightError as exc:
            return str(exc)
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: publish(), range(2)))
    assert results.count("success") == 1
    assert target.is_file()


def test_refresh_writer_preserves_competing_final(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import src.data.aihub_71748_approval_refresh as refresh

    document = _writer_document()
    target = canonical_approval_refresh_evidence_path(tmp_path, RUN_ID)
    original = refresh._publish_approval_refresh_no_replace

    def compete(temporary: Path, final: Path) -> None:
        final.write_bytes(b"competing-final")
        original(temporary, final)

    monkeypatch.setattr(refresh, "_publish_approval_refresh_no_replace", compete)
    with pytest.raises(ProcessingPreflightError, match="ALREADY_EXISTS"):
        write_approval_refresh_evidence_file(
            target, document, expected_fingerprint=str(document["fingerprint"]),
        )
    assert target.read_bytes() == b"competing-final"
    assert not target.with_name(target.name + ".tmp").exists()


def test_refresh_writer_parent_failure_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    document = _writer_document()
    target = canonical_approval_refresh_evidence_path(tmp_path, RUN_ID)
    original = Path.mkdir

    def fail(path: Path, *args: object, **kwargs: object) -> None:
        if path == target.parent:
            raise OSError("synthetic")
        original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail)
    with pytest.raises(ProcessingPreflightError, match="PARENT_CREATE_FAILED"):
        write_approval_refresh_evidence_file(
            target, document, expected_fingerprint=str(document["fingerprint"]),
        )
    assert not target.exists()


def test_refresh_writer_foreign_temp_is_preserved(tmp_path: Path) -> None:
    document = _writer_document()
    target = canonical_approval_refresh_evidence_path(tmp_path, RUN_ID)
    temporary = target.with_name(target.name + ".tmp")
    temporary.parent.mkdir(parents=True)
    temporary.write_bytes(b"foreign-temp")
    with pytest.raises(ProcessingPreflightError, match="TEMPORARY_COLLISION"):
        write_approval_refresh_evidence_file(
            target, document, expected_fingerprint=str(document["fingerprint"]),
        )
    assert temporary.read_bytes() == b"foreign-temp"
    assert not target.exists()


@pytest.mark.parametrize("failure", ["short_write", "flush"])
def test_refresh_writer_stream_failures_leave_no_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str,
) -> None:
    import src.data.aihub_71748_approval_refresh as refresh

    document = _writer_document()
    target = canonical_approval_refresh_evidence_path(tmp_path, RUN_ID)
    original_fdopen = refresh.os.fdopen

    class FailingStream:
        def __init__(self, descriptor: int) -> None:
            self.stream = original_fdopen(descriptor, "wb")

        def __enter__(self) -> "FailingStream":
            return self

        def __exit__(self, *args: object) -> None:
            self.stream.close()

        def write(self, payload: bytes) -> int:
            return 0 if failure == "short_write" else self.stream.write(payload)

        def flush(self) -> None:
            if failure == "flush":
                raise OSError("synthetic")
            self.stream.flush()

        def fileno(self) -> int:
            return self.stream.fileno()

    monkeypatch.setattr(
        refresh.os, "fdopen", lambda descriptor, _mode: FailingStream(descriptor),
    )
    with pytest.raises(ProcessingPreflightError, match="ATOMIC_WRITE_FAILED"):
        write_approval_refresh_evidence_file(
            target, document, expected_fingerprint=str(document["fingerprint"]),
        )
    assert not target.exists()
    assert not target.with_name(target.name + ".tmp").exists()


def test_refresh_writer_fsync_failure_leaves_no_final(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import src.data.aihub_71748_approval_refresh as refresh

    document = _writer_document()
    target = canonical_approval_refresh_evidence_path(tmp_path, RUN_ID)
    monkeypatch.setattr(
        refresh.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(ProcessingPreflightError, match="ATOMIC_WRITE_FAILED"):
        write_approval_refresh_evidence_file(
            target, document, expected_fingerprint=str(document["fingerprint"]),
        )
    assert not target.exists()


@pytest.mark.parametrize(
    "error_number,error_code",
    [(errno.EIO, "ATOMIC_WRITE_FAILED"), (errno.EXDEV, "NO_REPLACE_UNSUPPORTED")],
)
def test_refresh_writer_publish_failures_have_no_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error_number: int,
    error_code: str,
) -> None:
    import src.data.aihub_71748_approval_refresh as refresh

    document = _writer_document()
    target = canonical_approval_refresh_evidence_path(tmp_path, RUN_ID)
    monkeypatch.setattr(
        refresh.os, "link",
        lambda *_args: (_ for _ in ()).throw(OSError(error_number, "synthetic")),
    )
    with pytest.raises(ProcessingPreflightError, match=error_code):
        write_approval_refresh_evidence_file(
            target, document, expected_fingerprint=str(document["fingerprint"]),
        )
    assert not target.exists()
    assert not target.with_name(target.name + ".tmp").exists()


def test_refresh_writer_directory_sync_failure_preserves_incomplete_final(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import src.data.aihub_71748_approval_refresh as refresh

    document = _writer_document()
    target = canonical_approval_refresh_evidence_path(tmp_path, RUN_ID)
    monkeypatch.setattr(
        refresh, "_sync_approval_refresh_parent_directory",
        lambda _path: (_ for _ in ()).throw(
            ProcessingPreflightError(
                "APPROVAL_REFRESH_EVIDENCE_DIRECTORY_SYNC_FAILED"
            )
        ),
    )
    with pytest.raises(ProcessingPreflightError, match="DIRECTORY_SYNC_FAILED"):
        write_approval_refresh_evidence_file(
            target, document, expected_fingerprint=str(document["fingerprint"]),
        )
    assert target.is_file()
    with pytest.raises(ProcessingPreflightError, match="ALREADY_EXISTS"):
        write_approval_refresh_evidence_file(
            target, document, expected_fingerprint=str(document["fingerprint"]),
        )


def test_refresh_writer_reload_failure_preserves_incomplete_final(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import src.data.aihub_71748_approval_refresh as refresh

    document = _writer_document()
    target = canonical_approval_refresh_evidence_path(tmp_path, RUN_ID)
    monkeypatch.setattr(
        refresh, "_read_approval_refresh_document",
        lambda _path: (_ for _ in ()).throw(
            ProcessingPreflightError("APPROVAL_REFRESH_EVIDENCE_INCOMPLETE")
        ),
    )
    with pytest.raises(ProcessingPreflightError, match="INCOMPLETE"):
        write_approval_refresh_evidence_file(
            target, document, expected_fingerprint=str(document["fingerprint"]),
        )
    assert target.is_file()


def test_refresh_writer_rejects_fingerprint_mismatch_without_artifact(tmp_path: Path) -> None:
    document = _writer_document()
    target = canonical_approval_refresh_evidence_path(tmp_path, RUN_ID)
    with pytest.raises(ProcessingPreflightError, match="FINGERPRINT_MISMATCH"):
        write_approval_refresh_evidence_file(
            target, document, expected_fingerprint="0" * 64,
        )
    assert not target.exists()


@pytest.mark.parametrize(
    "target_factory",
    [
        lambda root: root / "runtime-evidence" / RUN_ID / "preflight-evidence.json",
        lambda root: root / "approvals" / f"{APPROVAL_ID}.json",
        lambda root: root / "wrong" / "approval-refresh-evidence.json",
    ],
)
def test_refresh_writer_rejects_noncanonical_paths(
    tmp_path: Path, target_factory: Callable[[Path], Path],
) -> None:
    document = _writer_document()
    target = target_factory(tmp_path)
    with pytest.raises(ProcessingPreflightError, match="PATH_INVALID"):
        write_approval_refresh_evidence_file(
            target, document, expected_fingerprint=str(document["fingerprint"]),
        )
    assert not target.exists()


def test_active_run_refresh_accepts_only_explicit_preflight_passed_state(tmp_path: Path) -> None:
    result = validate_active_run_for_approval_refresh(
        _mapping(tmp_path), run_id=RUN_ID, approval_id=APPROVAL_ID,
        expected_preflight_fingerprint="1" * 64,
        expected_run_status="preflight_passed", registry=Registry(_state()),
    )
    assert result.run_status == "preflight_passed"
    assert result.approval_id_unused is True


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"run_status": "reserved_preflight"}, "ACTIVE_RUN_STATUS_INVALID"),
        ({"run_status": "approval_issued"}, "ACTIVE_RUN_STATUS_INVALID"),
        ({"run_status": "retired"}, "ACTIVE_RUN_STATUS_INVALID"),
        ({"run_status": "processing_started"}, "ACTIVE_RUN_STATUS_INVALID"),
        ({"approval_artifact_exists": True}, "APPROVAL_ID_ALREADY_USED"),
        ({"approval_issue_calls": 1}, "APPROVAL_ALREADY_ISSUED"),
        ({"approval_consume_calls": 1}, "APPROVAL_ALREADY_CONSUMED"),
        ({"runtime_request_exists": True}, "RUNTIME_REQUEST_ALREADY_EXISTS"),
        ({"payload_reads": 1}, "PROCESSING_ALREADY_STARTED"),
        ({"processing_calls": 1}, "PROCESSING_ALREADY_STARTED"),
        ({"output_writes": 1}, "PROCESSING_ALREADY_STARTED"),
        ({"conflicting_evidence_count": 1}, "PREFLIGHT_REGISTRY_STATE_MISMATCH"),
        ({"previous_preflight_evidence_fingerprint": "0" * 64}, "PREFLIGHT_EVIDENCE_FINGERPRINT_MISMATCH"),
    ],
)
def test_active_run_refresh_fails_closed_by_registry_state(
    tmp_path: Path, changes: dict[str, object], error: str,
) -> None:
    with pytest.raises(ProcessingPreflightError, match=f"^{error}$"):
        validate_active_run_for_approval_refresh(
            _mapping(tmp_path), run_id=RUN_ID, approval_id=APPROVAL_ID,
            expected_preflight_fingerprint="1" * 64,
            expected_run_status="preflight_passed", registry=Registry(_state(**changes)),
        )


def test_active_run_refresh_requires_canonical_registry(tmp_path: Path) -> None:
    with pytest.raises(ProcessingPreflightError, match="^ACTIVE_RUN_REGISTRY_NOT_FOUND$"):
        validate_active_run_for_approval_refresh(
            _mapping(tmp_path), run_id=RUN_ID, approval_id=APPROVAL_ID,
            expected_preflight_fingerprint="1" * 64,
            expected_run_status="preflight_passed", registry=Registry(None),
        )


@pytest.mark.parametrize("suffix", ["", ".staging", ".failed"])
def test_active_run_refresh_rejects_output_collision(tmp_path: Path, suffix: str) -> None:
    mapping = _mapping(tmp_path)
    (mapping.processed_root / f"{RUN_ID}{suffix}").mkdir(parents=True)
    with pytest.raises(ProcessingPreflightError, match="^RUN_OUTPUT_ALREADY_EXISTS$"):
        validate_active_run_for_approval_refresh(
            mapping, run_id=RUN_ID, approval_id=APPROVAL_ID,
            expected_preflight_fingerprint="1" * 64,
            expected_run_status="preflight_passed", registry=Registry(_state()),
        )


def test_refresh_evidence_round_trip_and_freshness() -> None:
    evidence = _evidence()
    restored = deserialize_approval_refresh_evidence(json.loads(json.dumps(asdict(evidence))))
    assert restored == evidence
    _validate(evidence)
    with pytest.raises(ProcessingPreflightError, match="^APPROVAL_REFRESH_EVIDENCE_STALE$"):
        _validate(evidence, now=STAMP + timedelta(hours=1, seconds=1))


def test_refresh_evidence_unknown_field_and_version_fail_closed() -> None:
    value = asdict(_evidence())
    value["unknown"] = True
    with pytest.raises(ProcessingPreflightError, match="^APPROVAL_REFRESH_EVIDENCE_UNKNOWN_FIELD$"):
        deserialize_approval_refresh_evidence(value)
    with pytest.raises(ProcessingPreflightError, match="^APPROVAL_REFRESH_EVIDENCE_SCHEMA_INVALID$"):
        deserialize_approval_refresh_evidence({**asdict(_evidence()), "schema_version": 2})


def _previous_evidence(*, expires_at: str) -> PreflightEvidence:
    return PreflightEvidence(
        schema_version=2, run_id=RUN_ID, approval_id=APPROVAL_ID,
        execution_source_commit="2" * 40, governance_record_commit="2" * 40,
        manifest_sha256="4" * 64, backend_fingerprint="5" * 64,
        lineage={}, mapping_identity={}, source_snapshot={}, registry_state={},
        output_state={}, resource_state={}, runtime_budget={}, memory_budget={},
        disk_budget={}, record_budget={}, output_budget={}, zero_call_state={},
        generated_at=STAMP.isoformat(), expires_at=expires_at,
    )


def test_previous_preflight_is_historical_but_must_have_valid_freshness_contract() -> None:
    previous = _previous_evidence(expires_at=(STAMP + timedelta(hours=1)).isoformat())
    fingerprint = preflight_evidence_fingerprint(previous)
    value = {**asdict(previous), "status": "preflight_passed", "fingerprint": fingerprint}
    assert validate_previous_preflight_evidence(
        value, expected_fingerprint=fingerprint, run_id=RUN_ID,
        approval_id=APPROVAL_ID, execution_source_commit="2" * 40,
    ) == previous
    malformed = _previous_evidence(expires_at=(STAMP + timedelta(minutes=59)).isoformat())
    malformed_fingerprint = preflight_evidence_fingerprint(malformed)
    with pytest.raises(ProcessingPreflightError, match="^PREFLIGHT_EVIDENCE_STALE$"):
        validate_previous_preflight_evidence(
            {**asdict(malformed), "status": "preflight_passed", "fingerprint": malformed_fingerprint},
            expected_fingerprint=malformed_fingerprint, run_id=RUN_ID,
            approval_id=APPROVAL_ID, execution_source_commit="2" * 40,
        )


def _git(repository: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repository, text=True).strip()


def _commit(repository: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repository, check=True)
    return _git(repository, "rev-parse", "HEAD")


def test_governance_checkout_is_separate_from_execution_source(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "synthetic@example.invalid"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic"], cwd=repository, check=True)
    for relative in (MANIFEST_PATH, *BACKEND_PATHS):
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"surface:{relative}\n", encoding="utf-8")
    execution = _commit(repository, "execution")
    (repository / "governance.md").write_text("governance\n", encoding="utf-8")
    governance = _commit(repository, "governance")
    subprocess.run(["git", "update-ref", "refs/remotes/origin/develop", governance], cwd=repository, check=True)
    result = validate_governance_refresh_checkout(
        repository, execution_source_commit=execution,
        governance_record_commit=governance,
    )
    assert result.valid is True
    with pytest.raises(ProcessingPreflightError, match="^GOVERNANCE_CHECKOUT_MISMATCH$"):
        validate_governance_refresh_checkout(
            repository, execution_source_commit=execution,
            governance_record_commit=execution,
        )


def test_refresh_cli_is_refresh_only_and_requires_all_identities() -> None:
    arguments = refresh_cli.build_parser().parse_args([
        "--execution-source-commit", "1" * 40,
        "--governance-record-commit", "2" * 40,
        "--run-id", RUN_ID, "--approval-id", APPROVAL_ID,
        "--preflight-evidence", "synthetic.json",
        "--preflight-evidence-fingerprint", "3" * 64,
        "--approval-refresh-only",
    ])
    assert arguments.approval_refresh_only is True
    assert arguments.execution_source_commit != arguments.governance_record_commit


def test_refresh_cli_never_issues_or_consumes_approval(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(refresh_cli, "run_approval_refresh", lambda **_: {
        "status": "approval_refresh_validated", "approval_issued": False,
        "approval_consumed": False, "runtime_request_created": False,
        "payload_reads": 0, "processing_calls": 0, "output_writes": 0,
        "execution_allowed": False,
    })
    assert refresh_cli.main([
        "--execution-source-commit", "1" * 40,
        "--governance-record-commit", "2" * 40,
        "--run-id", RUN_ID, "--approval-id", APPROVAL_ID,
        "--preflight-evidence", "synthetic.json",
        "--preflight-evidence-fingerprint", "3" * 64,
        "--approval-refresh-only",
    ]) == 0
    assert '"execution_allowed": false' in capsys.readouterr().out


def test_refresh_cli_uses_public_writer_at_canonical_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    document = _writer_document()
    processed = tmp_path / "processed"
    target = canonical_approval_refresh_evidence_path(processed, RUN_ID)
    calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(refresh_cli, "run_approval_refresh", lambda **_kwargs: document)
    monkeypatch.setattr(refresh_cli, "_yaml", lambda _path: {})
    monkeypatch.setattr(
        refresh_cli, "resolve_dataset_mapping",
        lambda **_kwargs: ResolvedDatasetMapping(
            dataset_id="AIHUB-71748", component="SFT",
            source_root=tmp_path / "source", processed_root=processed,
            resolution_source="synthetic",
        ),
    )
    monkeypatch.setattr(
        refresh_cli,
        "write_approval_refresh_evidence_file",
        lambda path, _document, *, expected_fingerprint: calls.append(
            (Path(path), expected_fingerprint)
        ) or Path(path),
    )
    assert refresh_cli.main([
        "--mapping", "synthetic.yaml",
        "--manifest", "synthetic-manifest.yaml",
        "--execution-source-commit", "1" * 40,
        "--governance-record-commit", "2" * 40,
        "--run-id", RUN_ID,
        "--approval-id", APPROVAL_ID,
        "--preflight-evidence", "synthetic.json",
        "--preflight-evidence-fingerprint", "3" * 64,
        "--approval-refresh-only",
        "--output-evidence", str(target),
    ]) == 0
    assert calls == [(target, str(document["fingerprint"]))]


def test_refresh_cli_rejects_noncanonical_output_without_writer_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    document = _writer_document()
    processed = tmp_path / "processed"
    calls: list[Path] = []
    monkeypatch.setattr(refresh_cli, "run_approval_refresh", lambda **_kwargs: document)
    monkeypatch.setattr(refresh_cli, "_yaml", lambda _path: {})
    monkeypatch.setattr(
        refresh_cli, "resolve_dataset_mapping",
        lambda **_kwargs: ResolvedDatasetMapping(
            dataset_id="AIHUB-71748", component="SFT",
            source_root=tmp_path / "source", processed_root=processed,
            resolution_source="synthetic",
        ),
    )
    monkeypatch.setattr(
        refresh_cli, "write_approval_refresh_evidence_file",
        lambda path, *_args, **_kwargs: calls.append(Path(path)),
    )
    assert refresh_cli.main([
        "--mapping", "synthetic.yaml",
        "--manifest", "synthetic-manifest.yaml",
        "--execution-source-commit", "1" * 40,
        "--governance-record-commit", "2" * 40,
        "--run-id", RUN_ID,
        "--approval-id", APPROVAL_ID,
        "--preflight-evidence", "synthetic.json",
        "--preflight-evidence-fingerprint", "3" * 64,
        "--approval-refresh-only",
        "--output-evidence", str(tmp_path / "wrong.json"),
    ]) == 2
    assert calls == []
