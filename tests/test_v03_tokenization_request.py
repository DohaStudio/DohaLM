from __future__ import annotations

import json
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.data.v03_evidence import V03EvidenceBundleResult
from src.training import v03_tokenization_approval as approval_module
from src.training import v03_tokenization_request as request_module
from src.training.v03_run_identity import (
    build_v03_identity_inventory,
    initialize_v03_identity_ledger,
    parse_v03_tokenization_run_id,
    reserve_v03_run_identity,
)

NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)
RUN_ID = "DOHALM-V0.3-TOKENIZATION-20260805-0001"
DATASET_ID = "synthetic_fake_no_real_dataset_not_for_runtime"
APPROVAL_ID = "synthetic_fake_no_real_approval_not_for_runtime_not_approved"
REQUEST_ID = "synthetic_fake_no_real_request_not_for_runtime_not_approved"
SOURCE_COMMIT = "1" * 40
HASH = "sha256:" + "2" * 64
OTHER_HASH = "sha256:" + "3" * 64
ISSUE_NONCE = "4" * 64
REQUEST_NONCE = "5" * 64
FAKE_SECRET = "synthetic-fake-secret-not-for-runtime-000000000000"


@pytest.fixture
def synthetic_context() -> dict[str, object]:
    root = Path(__file__).parent / f".v03-r5-synthetic-{uuid.uuid4().hex}"
    root.mkdir()
    try:
        ledger_root = root / "ledger"
        approval_root = root / "approvals"
        request_root = root / "requests"
        lifecycle_root = root / "lifecycle"
        for path in (ledger_root, approval_root, request_root, lifecycle_root):
            path.mkdir()
        snapshot = initialize_v03_identity_ledger(ledger_root)
        inventory = build_v03_identity_inventory(snapshot.entries, ())
        reservation = reserve_v03_run_identity(
            ledger_root,
            parse_v03_tokenization_run_id(RUN_ID),
            inventory,
            source_commit=SOURCE_COMMIT,
            dataset_id=DATASET_ID,
            dataset_fingerprint=HASH,
            owner_token="synthetic-fake-owner-token-not-for-runtime",
            expires_at=NOW + timedelta(hours=2),
            reserved_at=NOW,
        )
        expected = request_module.calculate_v03_expected_artifact_set_fingerprint(
            request_module.canonical_v03_expected_artifact_set()
        )
        bundle = V03EvidenceBundleResult(
            schema_version=1,
            run_id="synthetic_fake_evidence_not_for_runtime",
            dataset_id=DATASET_ID,
            overall_decision="ready",
            evidence_bundle_fingerprint=HASH,
            readiness_artifact_checksum=HASH,
            artifact_checksums=(),
        )
        decision = approval_module.make_v03_approval_evidence_decision(
            bundle_result=bundle,
            canonical_dataset_fingerprint=HASH,
            effective_dataset_fingerprint=HASH,
            tokenization_config_fingerprint=HASH,
            tokenizer_identity="synthetic/fake-tokenizer-not-for-runtime",
            tokenizer_inventory_fingerprint=HASH,
            chat_template_fingerprint=HASH,
            backend_fingerprint=HASH,
            dependency_fingerprint=HASH,
            source_commit=SOURCE_COMMIT,
            expected_artifact_set_fingerprint=expected,
            license_decision="ready",
            unresolved_pii=0,
            unresolved_safety=0,
            unresolved_leakage=0,
            approval_issue_allowed=True,
        )
        draft = approval_module.new_v03_tokenization_approval_draft(
            approval_id=APPROVAL_ID,
            run_id=RUN_ID,
            reservation_id=reservation.reservation.reservation_id,
            dataset_id=DATASET_ID,
            canonical_dataset_fingerprint=HASH,
            effective_dataset_fingerprint=HASH,
            evidence_bundle_fingerprint=HASH,
            tokenization_config_fingerprint=HASH,
            tokenizer_identity="synthetic/fake-tokenizer-not-for-runtime",
            tokenizer_inventory_fingerprint=HASH,
            chat_template_fingerprint=HASH,
            backend_fingerprint=HASH,
            dependency_fingerprint=HASH,
            source_commit=SOURCE_COMMIT,
            allowed_input_root_id="synthetic/input-no-real-dataset",
            allowed_output_root_id="synthetic/output-not-approved",
            expected_artifact_set_fingerprint=expected,
            predecessor_run_id=None,
            expires_at=NOW + timedelta(minutes=90),
            approver_id="synthetic_fake_approver_not_approved",
        )
        approval_path = approval_root / f"{APPROVAL_ID}.json"
        approval = approval_module.issue_v03_tokenization_approval(
            destination=approval_path,
            draft=draft,
            reservation=reservation,
            evidence_decision=decision,
            issued_at=NOW,
            issue_nonce=ISSUE_NONCE,
        )
        request = _new_request(approval)
        yield {
            "root": root.resolve(),
            "approval": approval,
            "approval_path": approval_path.resolve(),
            "request": request,
            "reservation": reservation,
            "request_root": request_root.resolve(),
            "lifecycle_root": lifecycle_root.resolve(),
        }
    finally:
        shutil.rmtree(root)


def _new_request(approval, **changes):
    arguments = {
        "request_id": REQUEST_ID,
        "approval": approval,
        "requested_staging_root_id": "synthetic/staging-no-real-request",
        "requested_failure_root_id": "synthetic/failure-no-real-request",
        "execution_environment_fingerprint": HASH,
        "created_at": NOW + timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=30),
        "request_nonce": REQUEST_NONCE,
        "anti_replay_token": FAKE_SECRET,
    }
    arguments.update(changes)
    return request_module.new_v03_tokenization_execution_request(**arguments)


def _write(context: dict[str, object], request=None, **changes):
    value = request or context["request"]
    arguments = {
        "destination": context["request_root"] / f"{value.request_id}.json",
        "approval_path": context["approval_path"],
        "lifecycle_root": context["lifecycle_root"],
        "request": value,
        "approval": context["approval"],
        "reservation": context["reservation"],
        "current_time": NOW + timedelta(minutes=2),
    }
    arguments.update(changes)
    return request_module.write_v03_tokenization_execution_request(**arguments)


def _assert_code(code: str, call) -> None:
    with pytest.raises(request_module.V03TokenizationRequestError) as error:
        call()
    assert error.value.code == code
    assert str(error.value) == code


def test_request_schema_and_recovery_artifact_set_are_exact(
    synthetic_context: dict[str, object],
) -> None:
    request = synthetic_context["request"]
    assert request.status == "created"
    assert tuple(item.relative_name for item in request.expected_artifact_set) == (
        "train",
        "validation",
        "row-alignment.json",
        "lineage-alignment.json",
        "tokenization-manifest.yaml",
        "tokenization-statistics.json",
        "sampler-readiness.yaml",
        "checksums.sha256",
    )
    encoded = request_module.serialize_v03_tokenization_execution_request(request)
    assert FAKE_SECRET.encode() not in encoded
    assert (
        request_module.deserialize_v03_tokenization_execution_request(
            json.loads(encoded)
        )
        == request
    )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("schema_version", True, request_module.REQUEST_INVALID),
        ("requested_staging_root_id", "../escape", request_module.REQUEST_INVALID),
        ("request_nonce", "bad", request_module.REQUEST_INVALID),
        ("anti_replay_token_hash", HASH, request_module.REQUEST_INVALID),
        ("status", "approved", request_module.REQUEST_INVALID),
        (
            "execution_environment_fingerprint",
            float("nan"),
            request_module.REQUEST_INVALID,
        ),
        (
            "execution_environment_fingerprint",
            float("inf"),
            request_module.REQUEST_INVALID,
        ),
        (
            "expected_artifact_set_fingerprint",
            OTHER_HASH,
            request_module.EXPECTED_SET_INVALID,
        ),
    ],
)
def test_request_schema_rejects_invalid_fields(
    synthetic_context: dict[str, object], field: str, value: object, code: str
) -> None:
    request = synthetic_context["request"]
    _assert_code(
        code,
        lambda: request_module._seal_request(replace(request, **{field: value})),
    )


def test_request_rejects_unknown_field_checksum_and_long_ttl(
    synthetic_context: dict[str, object],
) -> None:
    request = synthetic_context["request"]
    mapping = json.loads(
        request_module.serialize_v03_tokenization_execution_request(request)
    )
    mapping["unknown"] = True
    _assert_code(
        request_module.REQUEST_INVALID,
        lambda: request_module.deserialize_v03_tokenization_execution_request(mapping),
    )
    _assert_code(
        request_module.REQUEST_CHECKSUM,
        lambda: request_module.validate_v03_tokenization_execution_request(
            replace(request, request_checksum=OTHER_HASH)
        ),
    )
    _assert_code(
        request_module.REQUEST_INVALID,
        lambda: _new_request(
            synthetic_context["approval"],
            expires_at=NOW + timedelta(minutes=62),
        ),
    )


def test_expected_artifact_set_rejects_duplicates_and_unsafe_paths() -> None:
    entries = request_module.canonical_v03_expected_artifact_set()
    _assert_code(
        request_module.EXPECTED_SET_INVALID,
        lambda: request_module.validate_v03_expected_artifact_set(
            entries + (entries[0],)
        ),
    )
    unsafe = (replace(entries[0], relative_name="../train"),) + entries[1:]
    _assert_code(
        request_module.EXPECTED_SET_INVALID,
        lambda: request_module.validate_v03_expected_artifact_set(unsafe),
    )


def test_anti_replay_is_deterministic_domain_separated_and_secret_safe() -> None:
    arguments = {
        "token": FAKE_SECRET,
        "approval_id": APPROVAL_ID,
        "request_id": REQUEST_ID,
        "run_id": RUN_ID,
        "request_nonce": REQUEST_NONCE,
    }
    first = request_module.make_v03_anti_replay_token_hash(**arguments)
    assert first == request_module.make_v03_anti_replay_token_hash(**arguments)
    assert FAKE_SECRET not in first
    for field in ("approval_id", "request_id", "run_id", "request_nonce"):
        changed = dict(arguments)
        changed[field] = "6" * 64 if field == "request_nonce" else changed[field] + "x"
        if field == "run_id":
            changed[field] = "DOHALM-V0.3-TOKENIZATION-20260805-0002"
        assert request_module.make_v03_anti_replay_token_hash(**changed) != first
    _assert_code(
        request_module.REQUEST_REPLAY,
        lambda: request_module.make_v03_anti_replay_token_hash(
            **{**arguments, "token": "short"}
        ),
    )


def test_request_writer_is_atomic_and_does_not_consume_approval(
    synthetic_context: dict[str, object],
) -> None:
    before = synthetic_context["approval_path"].read_bytes()
    result = _write(synthetic_context)
    assert result.request == synthetic_context["request"]
    assert result.lifecycle_state.status == "validated"
    assert synthetic_context["approval_path"].read_bytes() == before
    assert not approval_module.approval_consumption_path(
        synthetic_context["lifecycle_root"], APPROVAL_ID
    ).exists()


def test_request_writer_no_replace_race_has_one_winner(
    synthetic_context: dict[str, object],
) -> None:
    def attempt():
        try:
            return _write(synthetic_context)
        except request_module.V03TokenizationRequestError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: attempt(), range(2)))
    assert sum(not isinstance(result, str) for result in results) == 1
    assert next(result for result in results if isinstance(result, str)) in {
        request_module.REQUEST_EXISTS,
        approval_module.LIFECYCLE_LOCK_FAILED,
    }


def test_request_writer_rejects_approval_and_reservation_mismatch(
    synthetic_context: dict[str, object],
) -> None:
    request = request_module._seal_request(
        replace(synthetic_context["request"], backend_fingerprint=OTHER_HASH)
    )
    _assert_code(
        request_module.REQUEST_APPROVAL,
        lambda: _write(synthetic_context, request=request),
    )
    reservation = synthetic_context["reservation"]
    changed_reservation = replace(reservation.reservation, dataset_id="synthetic_other")
    changed_reservation = replace(
        changed_reservation,
        reservation_checksum=approval_module._fingerprint(
            approval_module._without(changed_reservation, "reservation_checksum")
        ),
    )
    _assert_code(
        request_module.REQUEST_RESERVATION,
        lambda: _write(
            synthetic_context,
            reservation=replace(reservation, reservation=changed_reservation),
        ),
    )


def test_request_writer_rejects_existing_symlink_and_lifecycle_drift(
    monkeypatch, synthetic_context: dict[str, object]
) -> None:
    _write(synthetic_context)
    _assert_code(request_module.REQUEST_EXISTS, lambda: _write(synthetic_context))
    destination = synthetic_context["request_root"] / f"{REQUEST_ID}.json"
    destination.unlink()
    original = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda self: self == destination or original(self)
    )
    _assert_code(request_module.REQUEST_INVALID, lambda: _write(synthetic_context))
    monkeypatch.undo()
    approval_module.retire_v03_tokenization_approval(
        approval_path=synthetic_context["approval_path"],
        lifecycle_root=synthetic_context["lifecycle_root"],
        reason_code="backend_fingerprint_drift",
        evidence_fingerprint=HASH,
        retired_at=NOW + timedelta(minutes=2),
    )
    _assert_code(request_module.REQUEST_APPROVAL, lambda: _write(synthetic_context))


def test_request_writer_rejects_expiry_and_replay_history(
    synthetic_context: dict[str, object],
) -> None:
    request = synthetic_context["request"]
    _assert_code(
        request_module.REQUEST_EXPIRED,
        lambda: _write(
            synthetic_context,
            current_time=NOW + timedelta(minutes=31),
        ),
    )
    for field, history in (
        ("used_request_ids", frozenset({request.request_id})),
        ("used_request_nonces", frozenset({request.request_nonce})),
        (
            "used_anti_replay_token_hashes",
            frozenset({request.anti_replay_token_hash}),
        ),
    ):
        _assert_code(
            request_module.REQUEST_REPLAY,
            lambda field=field, history=history: _write(
                synthetic_context, **{field: history}
            ),
        )


def test_request_writer_failure_does_not_leave_temp(
    monkeypatch, synthetic_context: dict[str, object]
) -> None:
    original = request_module._atomic_write_bytes

    def fail_after_temp(destination, payload, **kwargs):
        temp = destination.with_name(".synthetic-partial.tmp")
        temp.touch()
        try:
            raise request_module.V03TokenizationRequestError(
                request_module.REQUEST_INVALID
            )
        finally:
            temp.unlink()

    monkeypatch.setattr(request_module, "_atomic_write_bytes", fail_after_temp)
    _assert_code(request_module.REQUEST_INVALID, lambda: _write(synthetic_context))
    assert not tuple(synthetic_context["request_root"].glob("*.tmp"))
    monkeypatch.setattr(request_module, "_atomic_write_bytes", original)


def test_request_writer_reload_checksum_failure_is_closed(
    monkeypatch, synthetic_context: dict[str, object]
) -> None:
    request = synthetic_context["request"]
    monkeypatch.setattr(
        request_module,
        "load_v03_tokenization_execution_request",
        lambda _path: replace(request, request_checksum=OTHER_HASH),
    )
    _assert_code(request_module.REQUEST_INVALID, lambda: _write(synthetic_context))
    assert (synthetic_context["request_root"] / f"{REQUEST_ID}.json").exists()


def test_request_lifecycle_is_derived_from_immutable_approval_transitions(
    synthetic_context: dict[str, object],
) -> None:
    request = synthetic_context["request"]
    issued = request_module.resolve_v03_request_lifecycle(
        request=request,
        issued_approval=synthetic_context["approval"],
        current_time=NOW + timedelta(minutes=2),
    )
    assert issued.status == "created"
    consumed = approval_module.consume_v03_tokenization_approval(
        approval_path=synthetic_context["approval_path"],
        request=request,
        lifecycle_root=synthetic_context["lifecycle_root"],
        consumed_at=NOW + timedelta(minutes=2),
    ).transition
    state = request_module.resolve_v03_request_lifecycle(
        request=request,
        issued_approval=synthetic_context["approval"],
        consumption_artifact=consumed,
        current_time=NOW + timedelta(minutes=3),
    )
    assert state.status == "consumed"
