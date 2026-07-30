from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import zipfile

import pytest
import yaml

from scripts.datasets.process_aihub_71748_sft import metadata_preflight
from src.data.processing import (
    AIHub71748ProcessingError,
    AIHub71748ReaderError,
    DatasetMappingError,
    OutputWriterError,
    ProcessingRunContract,
    RunContractError,
    RuntimeBudget,
    RuntimeMonitor,
    RuntimeMonitorError,
    SourceArchive,
    SourceRecord,
    canonical_mapping_contract,
    discover_sft_sources,
    execute_approved_processing,
    iter_source_records,
    join_source_records,
    process_joined_records,
    recompute_record_signals,
    resolve_dataset_mapping,
    validate_mapping_contract,
    write_atomic_outputs,
)
from src.data.processing.approval import (
    ProcessingApprovalError,
    consume_approval,
    approval_fingerprint,
    issue_approval,
    load_approval,
    new_approval,
    validate_approval_file,
)
from src.data.processing.run_contract import RuntimeExecutionRequest, new_runtime_execution_request


MANIFEST = Path("configs/data/aihub-71748-sft-processing-v1.yaml")
STAMP = "2026-07-29T10:00:00+09:00"


@pytest.fixture
def external_tmp_path() -> Path:
    """Keep synthetic external-Dataset fixtures outside the repository."""

    with tempfile.TemporaryDirectory(prefix="dohalm-aihub-71748-") as directory:
        yield Path(directory)


def _contract() -> ProcessingRunContract:
    return ProcessingRunContract(
        "AIHUB-71748-SFT-PROCESSING-20990101-9999",
        "AIHUB-71748-SFT-PROCESSING-APPROVAL-20990101-9999",
        processing_allowed=True,
        payload_read_allowed=True,
        output_write_allowed=True,
        execution_allowed=True,
    )


def _approval(contract: ProcessingRunContract):
    return new_approval(
        contract,
        immutable_git_commit="b" * 40,
        governance_record_commit="e" * 40,
        manifest_sha256="a" * 64,
        backend_fingerprint="c" * 64,
        preflight_evidence_fingerprint="d" * 64,
        approved_by="synthetic-test",
        approved_at=STAMP,
    )


def _runtime_request(contract: ProcessingRunContract) -> RuntimeExecutionRequest:
    approval = _approval(contract)
    return new_runtime_execution_request(
        contract,
        request_id="SYNTHETIC-RUNTIME-REQUEST-V1",
        approval_fingerprint=approval_fingerprint(approval),
        preflight_evidence_fingerprint=approval.preflight_evidence_fingerprint,
        execution_source_commit=approval.execution_source_commit,
        governance_record_commit=approval.governance_record_commit,
        manifest_sha256=approval.manifest_sha256,
        backend_fingerprint=approval.backend_fingerprint,
        requested_by="synthetic-test",
        requested_at=STAMP,
        expires_at="2026-07-29T11:00:00+09:00",
        nonce="synthetic-nonce",
    )


def _local_config(root: Path) -> dict[str, object]:
    return {
        "datasets": {
            "external_root": str(root.parent),
            "entries": {
                "AIHUB-71748": {
                    "root": root.name,
                    "dataset_id": "AIHUB-71748",
                    "component": "SFT",
                    "root_type": "external",
                    "repository_internal": False,
                    "read_only": True,
                    "raw_immutable": True,
                    "processed_root": "processed/instruct/AIHUB-71748",
                }
            },
        }
    }


def _write_zip(path: Path, component: str, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"payload/{component}.json", json.dumps({"data_info": records}))


def _package(root: Path) -> Path:
    data = [{"data_id": "one", "question": "synthetic question", "question_count": 1, "question_type": "qa", "data_category": "test"}]
    label = [{"data_id": "one", "question": "synthetic question", "answer": {"contents": "synthetic answer", "answer_count": 1}}]
    validation_data = [{"data_id": "two", "question": "validation prompt", "question_count": 1, "question_type": "qa", "data_category": "test"}]
    validation_label = [{"data_id": "two", "question": "validation prompt", "answer": {"contents": "validation response", "answer_count": 1}}]
    _write_zip(root / "Training" / "TS_02.synthetic.zip", "sftdata", data)
    _write_zip(root / "Training" / "TL_02.synthetic.zip", "sftlabel", label)
    _write_zip(root / "Validation" / "VS_02.synthetic.zip", "sftdata", validation_data)
    _write_zip(root / "Validation" / "VL.zip", "sftlabel", validation_label)
    return root


def _records() -> tuple[SourceRecord, ...]:
    return (
        SourceRecord("training", "sftdata", "t1", "alpha question", 1, "qa", "test"),
        SourceRecord("training", "sftlabel", "t1", "alpha question", answer_contents="alpha answer", answer_count=1),
        SourceRecord("validation", "sftdata", "v1", "beta question", 1, "qa", "test"),
        SourceRecord("validation", "sftlabel", "v1", "beta question", answer_contents="beta answer", answer_count=1),
    )


def test_canonical_mapping_contract_is_valid() -> None:
    validate_mapping_contract(canonical_mapping_contract())


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("root_type", "internal", "DATASET_ROOT_TYPE_INVALID"),
        ("repository_internal", True, "REPOSITORY_INTERNAL_FLAG_INVALID"),
        ("read_only", False, "SOURCE_NOT_READ_ONLY"),
        ("component", "GENERAL", "DATASET_COMPONENT_MISMATCH"),
    ],
)
def test_mapping_contract_fails_closed(field: str, value: object, code: str) -> None:
    contract = canonical_mapping_contract()
    contract[field] = value
    with pytest.raises(DatasetMappingError, match=f"^{code}$"):
        validate_mapping_contract(contract)


def test_mapping_resolution_precedence_and_repository_rejection(external_tmp_path: Path) -> None:
    external = _package(external_tmp_path / "AIHUB-71748")
    local = _local_config(external)
    explicit = resolve_dataset_mapping(repository_root=Path.cwd(), explicit_root=external, local_config={})
    configured = resolve_dataset_mapping(repository_root=Path.cwd(), local_config=local, environment={})
    environment = resolve_dataset_mapping(
        repository_root=Path.cwd(), environment={"DOHALM_DATASET_ROOT": str(external_tmp_path)},
    )
    assert explicit.resolution_source == "explicit_cli"
    assert configured.resolution_source == "local_config"
    assert environment.resolution_source == "environment"
    inside = Path.cwd() / "AIHUB-71748"
    inside.mkdir(exist_ok=True)
    try:
        with pytest.raises(DatasetMappingError, match="^DATASET_ROOT_INSIDE_REPOSITORY$"):
            resolve_dataset_mapping(repository_root=Path.cwd(), explicit_root=inside)
    finally:
        inside.rmdir()


def test_unresolved_mapping_fails_closed() -> None:
    with pytest.raises(DatasetMappingError, match="^DATASET_ROOT_UNRESOLVED$"):
        resolve_dataset_mapping(repository_root=Path.cwd(), environment={})


def test_source_discovery_and_streaming_parser(tmp_path: Path) -> None:
    sources = discover_sft_sources(_package(tmp_path / "AIHUB-71748"))
    assert [(source.split, source.component) for source in sources] == [
        ("training", "sftdata"), ("training", "sftlabel"),
        ("validation", "sftdata"), ("validation", "sftlabel"),
    ]
    records = list(iter_source_records(sources[0]))
    assert len(records) == 1
    assert records[0].question_count == 1


def test_missing_split_and_component_fail_closed(tmp_path: Path) -> None:
    root = _package(tmp_path / "AIHUB-71748")
    (root / "Validation" / "VL.zip").unlink()
    with pytest.raises(AIHub71748ReaderError, match="^SOURCE_COMPONENT_MISSING$"):
        discover_sft_sources(root)
    (root / "Validation" / "VS_02.synthetic.zip").unlink()
    with pytest.raises(AIHub71748ReaderError, match="^SOURCE_SPLIT_MISSING$"):
        discover_sft_sources(root)


def test_duplicate_source_and_unsupported_zip_fail_closed(tmp_path: Path) -> None:
    root = _package(tmp_path / "AIHUB-71748")
    _write_zip(root / "Training" / "TS_02.second.zip", "sftdata", [])
    with pytest.raises(AIHub71748ReaderError, match="^SOURCE_ENTRY_DUPLICATED$"):
        discover_sft_sources(root)
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(AIHub71748ReaderError, match="^SOURCE_ARCHIVE_UNSUPPORTED$"):
        list(iter_source_records(SourceArchive("training", "sftdata", bad)))


def test_schema_drift_join_orphan_duplicate_and_question_mismatch_fail_closed() -> None:
    invalid = SourceRecord("training", "sftdata", "x", "q", 1, None, "test")
    with pytest.raises(AIHub71748ProcessingError, match="^INPUT_SCHEMA_MISMATCH$"):
        join_source_records((invalid, SourceRecord("training", "sftlabel", "x", "q", answer_contents="a")))
    with pytest.raises(AIHub71748ProcessingError, match="^JOIN_CONTRACT_MISMATCH$"):
        join_source_records((_records()[0],))
    with pytest.raises(AIHub71748ProcessingError, match="^JOIN_CONTRACT_MISMATCH$"):
        join_source_records((_records()[0], _records()[0], _records()[1]))
    mismatch = replace(_records()[1], question="different")
    with pytest.raises(AIHub71748ProcessingError, match="^JOIN_CONTRACT_MISMATCH$"):
        join_source_records((_records()[0], mismatch))


def test_record_level_signals_are_recomputed_and_not_exposed() -> None:
    joined = join_source_records(_records())
    signals = recompute_record_signals(joined, review_min=0.90, high_similarity_min=0.97)
    assert len(signals) == 2
    assert all(not hasattr(signal, "source_id") for signal in signals)


def test_manifest_dispatch_and_safe_output() -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    joined = join_source_records(_records())
    result = process_joined_records(joined, manifest, enforce_expected_statistics=False)
    assert result.record_level_signal_available is True
    assert result.execution_allowed is False
    assert set(result.train[0]) == {"instruction", "input", "output", "system"}
    assert "t1" not in json.dumps(result.train)


def test_real_statistics_contract_rejects_record_count_drift() -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    with pytest.raises(AIHub71748ProcessingError, match="^INPUT_RECORD_COUNT_MISMATCH$"):
        process_joined_records(
            join_source_records(_records()),
            manifest,
            blocked_prompts=frozenset({"unmatched synthetic prompt"}),
        )


def test_pii_exact_near_and_leakage_signals() -> None:
    base = join_source_records(_records())
    exact = replace(base[1], question=base[0].question, answer=base[0].answer)
    signals = recompute_record_signals((base[0], exact), review_min=0.90, high_similarity_min=0.97)
    assert signals[1].exact_duplicate == "duplicate"
    pii = replace(base[0], question="synthetic user test@example.com")
    assert recompute_record_signals((pii,), review_min=0.90, high_similarity_min=0.97)[0].pii == "exclude"


def test_atomic_output_writer_success_checksum_and_no_id(tmp_path: Path) -> None:
    root = tmp_path / "synthetic-run"
    record = {"instruction": "q", "input": None, "output": "a", "system": None}
    result = write_atomic_outputs(
        root,
        train_records=[record], validation_records=[record],
        manifest={"synthetic": True}, statistics={"input_count": 2}, result={"status": "completed"},
    )
    assert result["finalized"] is True
    assert set(path.name for path in root.iterdir()) == {
        "train.jsonl", "validation.jsonl", "manifest.yaml", "statistics.json", "checksums.sha256", "processing-result.yaml"
    }
    assert "data_id" not in (root / "train.jsonl").read_text(encoding="utf-8")
    with pytest.raises(OutputWriterError, match="^RUN_ID_ALREADY_USED$"):
        write_atomic_outputs(root, train_records=[], validation_records=[], manifest={}, statistics={}, result={})


def test_atomic_output_writer_cleans_failed_staging(tmp_path: Path) -> None:
    root = tmp_path / "failed"
    with pytest.raises(OutputWriterError, match="^OUTPUT_SCHEMA_MISMATCH$"):
        write_atomic_outputs(root, train_records=[{"data_id": "forbidden"}], validation_records=[], manifest={}, statistics={}, result={})
    assert not root.exists()
    assert not root.with_name("failed.staging").exists()
    assert root.with_name("failed.failed").is_dir()


def test_run_and_approval_reuse_are_fail_closed(tmp_path: Path) -> None:
    retired = ProcessingRunContract(
        "AIHUB-71748-SFT-PROCESSING-20260729-0001",
        "AIHUB-71748-SFT-PROCESSING-APPROVAL-20260729-0001",
    )
    with pytest.raises(RunContractError, match="^RUN_ID_RETIRED$"):
        new_approval(
            retired, immutable_git_commit="b" * 40, governance_record_commit="e" * 40,
            manifest_sha256="a" * 64,
            backend_fingerprint="c" * 64, preflight_evidence_fingerprint="d" * 64,
            approved_by="synthetic-test", approved_at=STAMP,
        )
    contract = _contract()
    path = tmp_path / "synthetic-approval.json"
    created = _approval(contract)
    issue_approval(path, created, issued_at=STAMP, contract=contract)
    record = validate_approval_file(path, contract)
    consumed = consume_approval(
        path, record, consumed_at=STAMP, contract=contract,
        runtime_request=_runtime_request(contract),
    )
    assert load_approval(path).state == "consumed"
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_ALREADY_CONSUMED$"):
        consume_approval(
            path, consumed, consumed_at=STAMP, contract=contract,
            runtime_request=_runtime_request(contract),
        )


def test_synthetic_full_flow_consumes_once_and_finalizes_atomically(tmp_path: Path) -> None:
    package = _package(tmp_path / "AIHUB-71748")
    contract = _contract()
    approval_path = tmp_path / "approval.json"
    issue_approval(approval_path, _approval(contract), issued_at=STAMP, contract=contract)
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    result = execute_approved_processing(
        package_root=package,
        run_root=tmp_path / "synthetic-run",
        repository_root=Path.cwd(),
        manifest=manifest,
        contract=contract,
        approval_path=approval_path,
        manifest_sha256="a" * 64,
        backend_git_commit="b" * 40,
        backend_fingerprint="c" * 64,
        preflight_evidence_fingerprint="d" * 64,
        runtime_request=_runtime_request(contract),
        enforce_expected_statistics=False,
        now=lambda: STAMP,
    )
    assert result["approval_consumed"] is True
    assert load_approval(approval_path).state == "completed"
    assert (tmp_path / "synthetic-run" / "checksums.sha256").is_file()


def test_approval_identity_mismatch_stops_before_consume(tmp_path: Path) -> None:
    package = _package(tmp_path / "AIHUB-71748")
    contract = _contract()
    approval_path = tmp_path / "approval.json"
    issue_approval(approval_path, _approval(contract), issued_at=STAMP, contract=contract)
    with pytest.raises(ProcessingApprovalError, match="^APPROVAL_NOT_FOUND$"):
        execute_approved_processing(
            package_root=package,
            run_root=tmp_path / "synthetic-run",
            repository_root=Path.cwd(),
            manifest=yaml.safe_load(MANIFEST.read_text(encoding="utf-8")),
            contract=contract,
            approval_path=approval_path,
            manifest_sha256="c" * 64,
            backend_git_commit="b" * 40,
            backend_fingerprint="c" * 64,
            preflight_evidence_fingerprint="d" * 64,
            runtime_request=_runtime_request(contract),
            enforce_expected_statistics=False,
        )
    assert load_approval(approval_path).state == "issued"
    assert not (tmp_path / "synthetic-run").exists()


def test_runtime_monitor_cancellation_and_budget() -> None:
    with pytest.raises(RuntimeMonitorError, match="^PROCESSING_CANCELLED$"):
        RuntimeMonitor(cancelled=lambda: True).check("synthetic")
    monitor = RuntimeMonitor(RuntimeBudget(maximum_records=0))
    with pytest.raises(RuntimeMonitorError, match="^RECORD_BUDGET_EXCEEDED$"):
        monitor.check("synthetic", source_records=1)


def test_metadata_preflight_does_not_open_payload_or_write_dataset(external_tmp_path: Path) -> None:
    package = _package(external_tmp_path / "AIHUB-71748")
    local = external_tmp_path / "local.yaml"
    local.write_text(yaml.safe_dump(_local_config(package)), encoding="utf-8")
    result = metadata_preflight(
        repository_root=Path.cwd(), manifest_path=MANIFEST,
        mapping_path=local, explicit_root=None,
    )
    assert result["payload_opened"] is False
    assert result["dataset_written"] is False
    assert result["processing_calls"] == 0
    assert result["execution_allowed"] is False
