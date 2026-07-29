from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
import json
import subprocess

import pytest

import scripts.datasets.process_aihub_71748_sft as process_cli
from src.data.aihub_71748_processing_preflight import (
    BACKEND_PATHS,
    MANIFEST_PATH,
    ProcessingPreflightError,
    validate_immutable_lineage,
)
from src.data.processing.approval import (
    ProcessingApprovalError,
    approval_checksum,
    consume_approval,
    deserialize_approval,
    issue_approval,
    load_approval,
    load_legacy_approval,
    new_approval,
    validate_approval,
)
from src.data.processing.run_contract import (
    ProcessingRunContract,
    RunContractError,
    RuntimeExecutionRequest,
    RunRegistry,
    runtime_request_fingerprint,
    validate_run_contract,
    validate_runtime_request,
)


STAMP = "2026-07-30T05:00:00+09:00"
RUN_ID = "AIHUB-71748-SFT-PROCESSING-20990101-9999"
APPROVAL_ID = "AIHUB-71748-SFT-PROCESSING-APPROVAL-20990101-9999"


def _contract(*, capability: bool = True, execution: bool = False) -> ProcessingRunContract:
    return ProcessingRunContract(
        run_id=RUN_ID,
        approval_id=APPROVAL_ID,
        processing_allowed=capability,
        payload_read_allowed=capability,
        output_write_allowed=capability,
        execution_allowed=execution,
    )


def _approval(contract: ProcessingRunContract | None = None):
    return new_approval(
        contract or _contract(),
        immutable_git_commit="1" * 40,
        governance_record_commit="2" * 40,
        manifest_sha256="3" * 64,
        backend_fingerprint="4" * 64,
        preflight_evidence_fingerprint="5" * 64,
        approved_by="synthetic-user",
        approved_at=STAMP,
    )


def _runtime(contract: ProcessingRunContract, *, allowed: bool = True) -> RuntimeExecutionRequest:
    request = RuntimeExecutionRequest(
        run_id=contract.run_id,
        approval_id=contract.approval_id,
        execution_allowed=allowed,
        maximum_processing_calls=1,
        maximum_payload_open_sessions=1,
        requested_at=STAMP,
    )
    return replace(request, request_fingerprint=runtime_request_fingerprint(request))


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=repository, text=True).strip()


def _commit(repository: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repository, check=True)
    return _git(repository, "rev-parse", "HEAD")


def _lineage_repository(root: Path) -> tuple[Path, str, str]:
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "synthetic@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=root, check=True)
    for relative in (MANIFEST_PATH, *BACKEND_PATHS):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"surface:{relative}\n", encoding="utf-8")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    base = _commit(root, "base")
    subprocess.run(["git", "checkout", "-q", "-b", "execution"], cwd=root, check=True)
    (root / "execution.txt").write_text("execution\n", encoding="utf-8")
    execution = _commit(root, "execution")
    subprocess.run(["git", "checkout", "-q", "-b", "governance", base], cwd=root, check=True)
    (root / "governance.txt").write_text("governance\n", encoding="utf-8")
    governance = _commit(root, "governance")
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/develop", governance], cwd=root, check=True,
    )
    return root, execution, governance


def test_issued_approval_capability_is_separate_from_runtime_gate(tmp_path: Path) -> None:
    contract = _contract()
    created = _approval(contract)
    assert created.execution_allowed is False and created.consumed is False
    path = tmp_path / "approval.json"
    issued = issue_approval(path, created, issued_at=STAMP, contract=contract)
    assert issued.status == "issued"
    assert issued.execution_allowed is False and issued.consumed is False
    assert all((issued.processing_allowed, issued.payload_read_allowed, issued.output_write_allowed))
    assert load_approval(path) == issued


def test_consumption_requires_separate_runtime_request(tmp_path: Path) -> None:
    issuance_contract = _contract()
    path = tmp_path / "approval.json"
    issued = issue_approval(path, _approval(), issued_at=STAMP, contract=issuance_contract)
    execution_contract = _contract(execution=True)
    consumed = consume_approval(
        path, issued, consumed_at=STAMP, contract=execution_contract,
        runtime_request=_runtime(execution_contract),
    )
    assert consumed.status == "consumed" and consumed.consumed is True
    assert consumed.execution_allowed is False


@pytest.mark.parametrize(
    "contract,error",
    [
        (ProcessingRunContract(RUN_ID, APPROVAL_ID, execution_allowed=True), "APPROVAL_CAPABILITY_INSUFFICIENT"),
        (
            ProcessingRunContract(
                RUN_ID, APPROVAL_ID, processing_allowed=True,
                payload_read_allowed=False, output_write_allowed=True,
            ),
            "APPROVAL_CAPABILITY_INSUFFICIENT",
        ),
    ],
)
def test_invalid_permission_combinations_fail_closed(
    contract: ProcessingRunContract,
    error: str,
) -> None:
    with pytest.raises(RunContractError, match=f"^{error}$"):
        validate_run_contract(contract)


def test_runtime_execution_false_and_insufficient_capability_are_distinct() -> None:
    contract = _contract()
    with pytest.raises(RunContractError, match="^RUNTIME_EXECUTION_NOT_APPROVED$"):
        validate_runtime_request(_runtime(contract, allowed=False), contract)
    insufficient = _contract(capability=False, execution=True)
    with pytest.raises(RunContractError, match="^APPROVAL_CAPABILITY_INSUFFICIENT$"):
        validate_runtime_request(_runtime(insufficient), insufficient)


def test_approval_serialization_round_trip_and_fingerprint_cover_security_fields() -> None:
    record = _approval()
    restored = deserialize_approval(json.loads(json.dumps(asdict(record))))
    assert restored == record
    assert isinstance(restored.consumed, bool) and isinstance(restored.execution_allowed, bool)
    changed = replace(record, governance_record_commit="6" * 40, checksum="")
    assert approval_checksum(changed) != approval_checksum(record)


@pytest.mark.parametrize(
    "field,error",
    [
        ("governance_record_commit", "APPROVAL_GOVERNANCE_COMMIT_REQUIRED"),
        ("consumed", "APPROVAL_CONSUMED_FIELD_REQUIRED"),
        ("execution_allowed", "APPROVAL_EXECUTION_ALLOWED_FIELD_REQUIRED"),
    ],
)
def test_required_approval_security_fields_fail_closed(field: str, error: str) -> None:
    value = asdict(_approval())
    value.pop(field)
    with pytest.raises(ProcessingApprovalError, match=f"^{error}$"):
        deserialize_approval(value)


def test_unknown_and_invalid_boolean_approval_fields_fail_closed() -> None:
    value = asdict(_approval())
    value["unknown"] = True
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_UNKNOWN_FIELD$"):
        deserialize_approval(value)
    record = replace(_approval(), consumed=0)  # type: ignore[arg-type]
    record = replace(record, checksum=approval_checksum(record))
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_CONSUMED_FIELD_REQUIRED$"):
        validate_approval(record, _contract())


def test_legacy_approval_is_readable_but_not_executable(tmp_path: Path) -> None:
    value = asdict(_approval())
    for field in ("governance_record_commit", "consumed", "execution_allowed"):
        value.pop(field)
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    legacy = load_legacy_approval(path)
    assert legacy.executable is False and legacy.values["approval_id"] == APPROVAL_ID
    with pytest.raises(ProcessingApprovalError, match="^LEGACY_APPROVAL_NOT_EXECUTABLE$"):
        load_approval(path)


def test_run_0006_and_approval_0006_are_permanently_retired() -> None:
    contract = ProcessingRunContract(
        "AIHUB-71748-SFT-PROCESSING-20260730-0006",
        "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260730-0006",
    )
    with pytest.raises(RunContractError, match="^RUN_ID_RETIRED$"):
        validate_run_contract(contract)
    assert RunRegistry().snapshot()[contract.run_id] == "retired_approval_contract_failure"


def test_squash_merge_surface_equivalence_is_valid(tmp_path: Path) -> None:
    repository, execution, governance = _lineage_repository(tmp_path / "repository")
    result = validate_immutable_lineage(
        repository, execution_source_commit=execution,
        governance_record_commit=governance,
    )
    assert result.valid is True and result.direct_ancestry is False
    assert result.result_code == "SQUASH_MERGE_EXECUTION_SURFACE_EQUIVALENT"
    assert result.execution_surface_file_count == 10


def test_direct_ancestry_surface_equivalence_is_valid(tmp_path: Path) -> None:
    repository, execution, governance = _lineage_repository(tmp_path / "repository")
    base = _git(repository, "rev-parse", f"{execution}^")
    result = validate_immutable_lineage(
        repository, execution_source_commit=base,
        governance_record_commit=governance,
    )
    assert result.valid is True and result.direct_ancestry is True
    assert result.result_code == "DIRECT_ANCESTRY_VALID"


@pytest.mark.parametrize(
    "relative,error",
    [
        ("scripts/datasets/process_aihub_71748_sft.py", "BACKEND_FINGERPRINT_MISMATCH"),
        (MANIFEST_PATH, "MANIFEST_FINGERPRINT_MISMATCH"),
        ("src/data/processing/approval.py", "BACKEND_FINGERPRINT_MISMATCH"),
    ],
)
def test_squash_merge_surface_drift_fails_closed(
    tmp_path: Path,
    relative: str,
    error: str,
) -> None:
    repository, execution, _ = _lineage_repository(tmp_path / "repository")
    (repository / relative).write_text("drift\n", encoding="utf-8")
    governance = _commit(repository, "surface drift")
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/develop", governance], cwd=repository, check=True,
    )
    with pytest.raises(ProcessingPreflightError, match=f"^{error}$"):
        validate_immutable_lineage(
            repository, execution_source_commit=execution,
            governance_record_commit=governance,
        )


def test_missing_surface_and_unreachable_commits_fail_closed(tmp_path: Path) -> None:
    repository, execution, governance = _lineage_repository(tmp_path / "repository")
    with pytest.raises(ProcessingPreflightError, match="^EXECUTION_SOURCE_COMMIT_NOT_FOUND$"):
        validate_immutable_lineage(
            repository, execution_source_commit="0" * 40,
            governance_record_commit=governance,
        )
    subprocess.run(["git", "update-ref", "-d", "refs/remotes/origin/develop"], cwd=repository, check=True)
    with pytest.raises(ProcessingPreflightError, match="^GOVERNANCE_COMMIT_NOT_REACHABLE$"):
        validate_immutable_lineage(
            repository, execution_source_commit=execution,
            governance_record_commit=governance,
        )


def test_missing_execution_surface_file_fails_closed(tmp_path: Path) -> None:
    repository, execution, _ = _lineage_repository(tmp_path / "repository")
    (repository / BACKEND_PATHS[0]).unlink()
    governance = _commit(repository, "missing surface")
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/develop", governance], cwd=repository, check=True,
    )
    with pytest.raises(ProcessingPreflightError, match="^EXECUTION_SURFACE_FILE_MISSING$"):
        validate_immutable_lineage(
            repository, execution_source_commit=execution,
            governance_record_commit=governance,
        )


def test_cli_commit_roles_and_legacy_alias_are_explicit() -> None:
    current = process_cli.build_parser().parse_args([
        "--execution-source-commit", "1" * 40,
        "--governance-record-commit", "2" * 40,
    ])
    legacy = process_cli.build_parser().parse_args([
        "--immutable-commit", "1" * 40,
        "--governance-record-commit", "2" * 40,
    ])
    assert current.execution_source_commit == legacy.execution_source_commit == "1" * 40
    assert current.governance_record_commit == "2" * 40


def test_processing_cli_requires_separate_runtime_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = process_cli.main([
        "--no-preflight-only",
        "--processing-allowed",
        "--execution-allowed",
        "--run-id", RUN_ID,
        "--approval-id", APPROVAL_ID,
        "--approval", "synthetic-approval.json",
        "--preflight-evidence", "synthetic-evidence.json",
        "--execution-source-commit", "1" * 40,
        "--governance-record-commit", "2" * 40,
    ])
    assert result == 2
    assert '"error_code": "PROCESSING_NOT_APPROVED"' in capsys.readouterr().out
