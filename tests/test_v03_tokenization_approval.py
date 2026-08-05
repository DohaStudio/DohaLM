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
def synthetic_root() -> Path:
    root = Path(__file__).parent / f".v03-r45-synthetic-{uuid.uuid4().hex}"
    root.mkdir()
    try:
        yield root.resolve()
    finally:
        shutil.rmtree(root)


def _context(root: Path) -> dict[str, object]:
    ledger_root = root / "ledger"
    approval_root = root / "approvals"
    lifecycle_root = root / "lifecycle"
    ledger_root.mkdir()
    approval_root.mkdir()
    lifecycle_root.mkdir()
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
    path = approval_root / f"{APPROVAL_ID}.json"
    return {
        "approval_root": approval_root,
        "lifecycle_root": lifecycle_root,
        "reservation": reservation,
        "decision": decision,
        "draft": draft,
        "path": path,
    }


def _issue(context: dict[str, object]):
    return approval_module.issue_v03_tokenization_approval(
        destination=context["path"],
        draft=context["draft"],
        reservation=context["reservation"],
        evidence_decision=context["decision"],
        issued_at=NOW,
        issue_nonce=ISSUE_NONCE,
    )


def _request(approval):
    return request_module.new_v03_tokenization_execution_request(
        request_id=REQUEST_ID,
        approval=approval,
        requested_staging_root_id="synthetic/staging-no-real-request",
        requested_failure_root_id="synthetic/failure-no-real-request",
        execution_environment_fingerprint=HASH,
        created_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        request_nonce=REQUEST_NONCE,
        anti_replay_token=FAKE_SECRET,
    )


def _assert_code(code: str, call) -> None:
    with pytest.raises(approval_module.V03TokenizationApprovalError) as error:
        call()
    assert error.value.code == code
    assert str(error.value) == code


def test_synthetic_fixture_markers_are_explicit() -> None:
    fixtures = " ".join((DATASET_ID, APPROVAL_ID, REQUEST_ID, FAKE_SECRET))
    for marker in (
        "synthetic",
        "fake",
        "not_for_runtime",
        "not_approved",
        "no_real_dataset",
        "no_real_approval",
        "no_real_request",
    ):
        assert marker in fixtures


def test_valid_draft_and_issue_are_canonical_and_immutable(
    synthetic_root: Path,
) -> None:
    context = _context(synthetic_root)
    draft = context["draft"]
    assert draft.status == "draft"
    issued = _issue(context)
    before = context["path"].read_bytes()
    assert issued.status == "issued"
    assert issued.issued_at == "2026-08-05T00:00:00.000000Z"
    assert approval_module.load_v03_tokenization_approval(context["path"]) == issued
    assert before == approval_module.serialize_v03_tokenization_approval(issued)
    assert context["reservation"].reservation.status == "active"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("status", "approved"),
        ("run_id", "invalid"),
        ("source_commit", "A" * 40),
        ("backend_fingerprint", "sha256:BAD"),
        ("backend_fingerprint", float("nan")),
        ("backend_fingerprint", float("inf")),
        ("expires_at", "2026-08-05T00:00:00+00:00"),
        ("consumed_at", "2026-08-05T00:01:00.000000Z"),
    ],
)
def test_draft_rejects_invalid_contract_fields(
    synthetic_root: Path, field: str, value: object
) -> None:
    draft = _context(synthetic_root)["draft"]
    _assert_code(
        approval_module.APPROVAL_INVALID,
        lambda: approval_module._seal_approval(replace(draft, **{field: value})),
    )


def test_schema_rejects_unknown_field_and_checksum_mismatch(
    synthetic_root: Path,
) -> None:
    draft = _context(synthetic_root)["draft"]
    mapping = json.loads(approval_module.serialize_v03_tokenization_approval(draft))
    mapping["unknown"] = True
    _assert_code(
        approval_module.APPROVAL_INVALID,
        lambda: approval_module.deserialize_v03_tokenization_approval(mapping),
    )
    _assert_code(
        approval_module.APPROVAL_CHECKSUM,
        lambda: approval_module.validate_v03_tokenization_approval(
            replace(draft, approval_checksum=OTHER_HASH)
        ),
    )


def test_issue_rejects_not_ready_and_exact_match_drift(synthetic_root: Path) -> None:
    context = _context(synthetic_root)
    decision = replace(
        context["decision"], overall_decision="blocked", decision_fingerprint=""
    )
    decision = replace(
        decision,
        decision_fingerprint=approval_module._fingerprint(
            approval_module._without(decision, "decision_fingerprint")
        ),
    )
    _assert_code(
        approval_module.APPROVAL_NOT_ISSUABLE,
        lambda: approval_module.issue_v03_tokenization_approval(
            destination=context["path"],
            draft=context["draft"],
            reservation=context["reservation"],
            evidence_decision=decision,
            issued_at=NOW,
            issue_nonce=ISSUE_NONCE,
        ),
    )
    for field in ("dataset_id", "backend_fingerprint"):
        changed = replace(
            context["draft"],
            **{
                field: "synthetic_other_dataset"
                if field == "dataset_id"
                else OTHER_HASH
            },
        )
        changed = approval_module._seal_approval(changed)
        _assert_code(
            approval_module.APPROVAL_NOT_ISSUABLE,
            lambda changed=changed: approval_module.issue_v03_tokenization_approval(
                destination=context["path"],
                draft=changed,
                reservation=context["reservation"],
                evidence_decision=context["decision"],
                issued_at=NOW,
                issue_nonce=ISSUE_NONCE,
            ),
        )


def test_issue_rejects_inactive_reservation(synthetic_root: Path) -> None:
    context = _context(synthetic_root)
    reservation = context["reservation"]
    inactive = replace(
        reservation.reservation, status="committed", reservation_checksum=""
    )
    inactive = replace(
        inactive,
        reservation_checksum=approval_module._fingerprint(
            approval_module._without(inactive, "reservation_checksum")
        ),
    )
    result = replace(reservation, reservation=inactive)
    _assert_code(
        approval_module.APPROVAL_RESERVATION,
        lambda: approval_module.issue_v03_tokenization_approval(
            destination=context["path"],
            draft=context["draft"],
            reservation=result,
            evidence_decision=context["decision"],
            issued_at=NOW,
            issue_nonce=ISSUE_NONCE,
        ),
    )


def test_issue_rejects_existing_destination_and_lock(synthetic_root: Path) -> None:
    context = _context(synthetic_root)
    _issue(context)
    _assert_code(approval_module.APPROVAL_EXISTS, lambda: _issue(context))
    lock = Path(str(context["path"]) + ".lifecycle.lock")
    lock.mkdir()
    _assert_code(approval_module.LIFECYCLE_LOCK_FAILED, lambda: _issue(context))


def test_issue_rejects_symlink_destination(monkeypatch, synthetic_root: Path) -> None:
    context = _context(synthetic_root)
    path = context["path"]
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == path or original(self))
    _assert_code(approval_module.APPROVAL_INVALID, lambda: _issue(context))


def test_issue_write_failure_leaves_no_published_artifact(
    monkeypatch, synthetic_root: Path
) -> None:
    context = _context(synthetic_root)
    monkeypatch.setattr(
        approval_module,
        "_atomic_write_bytes",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            approval_module.V03TokenizationApprovalError(
                approval_module.APPROVAL_INVALID
            )
        ),
    )
    _assert_code(approval_module.APPROVAL_INVALID, lambda: _issue(context))
    assert not context["path"].exists()


def test_issue_no_replace_race_has_one_winner(synthetic_root: Path) -> None:
    context = _context(synthetic_root)

    def attempt():
        try:
            return _issue(context)
        except approval_module.V03TokenizationApprovalError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: attempt(), range(2)))
    assert sum(not isinstance(result, str) for result in results) == 1
    assert next(result for result in results if isinstance(result, str)) in {
        approval_module.APPROVAL_EXISTS,
        approval_module.LIFECYCLE_LOCK_FAILED,
    }


def test_issue_reload_failure_fails_closed(monkeypatch, synthetic_root: Path) -> None:
    context = _context(synthetic_root)
    monkeypatch.setattr(
        approval_module,
        "load_v03_tokenization_approval",
        lambda _path: context["draft"],
    )
    _assert_code(approval_module.APPROVAL_INVALID, lambda: _issue(context))
    assert context["path"].exists()


def test_consume_is_immutable_and_exactly_idempotent(synthetic_root: Path) -> None:
    context = _context(synthetic_root)
    issued = _issue(context)
    request = _request(issued)
    before = context["path"].read_bytes()
    first = approval_module.consume_v03_tokenization_approval(
        approval_path=context["path"],
        request=request,
        lifecycle_root=context["lifecycle_root"],
        consumed_at=NOW + timedelta(minutes=2),
    )
    second = approval_module.consume_v03_tokenization_approval(
        approval_path=context["path"],
        request=request,
        lifecycle_root=context["lifecycle_root"],
        consumed_at=NOW + timedelta(minutes=2),
    )
    assert first == second
    assert first.lifecycle_state.status == "consumed"
    assert context["path"].read_bytes() == before
    _assert_code(
        approval_module.APPROVAL_CONSUMED,
        lambda: approval_module.consume_v03_tokenization_approval(
            approval_path=context["path"],
            request=request,
            lifecycle_root=context["lifecycle_root"],
            consumed_at=NOW + timedelta(minutes=3),
        ),
    )


def test_consume_rejects_request_mismatch_expiry_and_replay(
    synthetic_root: Path,
) -> None:
    context = _context(synthetic_root)
    issued = _issue(context)
    request = _request(issued)
    mismatch = request_module._seal_request(
        replace(request, backend_fingerprint=OTHER_HASH)
    )
    _assert_code(
        approval_module.REQUEST_APPROVAL,
        lambda: approval_module.consume_v03_tokenization_approval(
            approval_path=context["path"],
            request=mismatch,
            lifecycle_root=context["lifecycle_root"],
            consumed_at=NOW + timedelta(minutes=2),
        ),
    )
    _assert_code(
        approval_module.REQUEST_REPLAY,
        lambda: approval_module.consume_v03_tokenization_approval(
            approval_path=context["path"],
            request=request,
            lifecycle_root=context["lifecycle_root"],
            consumed_at=NOW + timedelta(minutes=2),
            consumed_anti_replay_token_hashes=frozenset(
                {request.anti_replay_token_hash}
            ),
        ),
    )
    _assert_code(
        approval_module.APPROVAL_EXPIRED,
        lambda: approval_module.consume_v03_tokenization_approval(
            approval_path=context["path"],
            request=request,
            lifecycle_root=context["lifecycle_root"],
            consumed_at=NOW + timedelta(hours=2),
        ),
    )


@pytest.mark.parametrize("reason", ["source_commit_drift", "user_revoked"])
def test_retirement_is_separate_and_blocks_consume(
    synthetic_root: Path, reason: str
) -> None:
    context = _context(synthetic_root)
    issued = _issue(context)
    before = context["path"].read_bytes()
    transition = approval_module.retire_v03_tokenization_approval(
        approval_path=context["path"],
        lifecycle_root=context["lifecycle_root"],
        reason_code=reason,
        evidence_fingerprint=HASH,
        retired_at=NOW + timedelta(minutes=2),
    )
    assert transition.status == "retired"
    assert context["path"].read_bytes() == before
    _assert_code(
        approval_module.APPROVAL_RETIRED,
        lambda: approval_module.consume_v03_tokenization_approval(
            approval_path=context["path"],
            request=_request(issued),
            lifecycle_root=context["lifecycle_root"],
            consumed_at=NOW + timedelta(minutes=3),
        ),
    )
    _assert_code(
        approval_module.APPROVAL_RETIRED,
        lambda: approval_module.retire_v03_tokenization_approval(
            approval_path=context["path"],
            lifecycle_root=context["lifecycle_root"],
            reason_code=reason,
            evidence_fingerprint=HASH,
            retired_at=NOW + timedelta(minutes=3),
        ),
    )


def test_consumed_approval_cannot_retire(synthetic_root: Path) -> None:
    context = _context(synthetic_root)
    issued = _issue(context)
    approval_module.consume_v03_tokenization_approval(
        approval_path=context["path"],
        request=_request(issued),
        lifecycle_root=context["lifecycle_root"],
        consumed_at=NOW + timedelta(minutes=2),
    )
    _assert_code(
        approval_module.APPROVAL_CONSUMED,
        lambda: approval_module.retire_v03_tokenization_approval(
            approval_path=context["path"],
            lifecycle_root=context["lifecycle_root"],
            reason_code="user_revoked",
            evidence_fingerprint=HASH,
            retired_at=NOW + timedelta(minutes=3),
        ),
    )


def test_expiration_requires_strictly_later_time(synthetic_root: Path) -> None:
    context = _context(synthetic_root)
    issued = _issue(context)
    _assert_code(
        approval_module.APPROVAL_INVALID,
        lambda: approval_module.expire_v03_tokenization_approval(
            approval_path=context["path"],
            lifecycle_root=context["lifecycle_root"],
            evidence_fingerprint=HASH,
            current_time=NOW + timedelta(minutes=90),
        ),
    )
    transition = approval_module.expire_v03_tokenization_approval(
        approval_path=context["path"],
        lifecycle_root=context["lifecycle_root"],
        evidence_fingerprint=HASH,
        current_time=NOW + timedelta(minutes=90, microseconds=1),
    )
    assert transition.status == "expired"
    state = approval_module.resolve_v03_approval_lifecycle(
        issued_approval=issued,
        retirement_artifact=transition,
        current_time=NOW + timedelta(hours=2),
    )
    assert state.status == "expired"


def test_lifecycle_detects_consumed_retired_conflict_and_checksum(
    synthetic_root: Path,
) -> None:
    context = _context(synthetic_root)
    issued = _issue(context)
    consumed = approval_module.consume_v03_tokenization_approval(
        approval_path=context["path"],
        request=_request(issued),
        lifecycle_root=context["lifecycle_root"],
        consumed_at=NOW + timedelta(minutes=2),
    ).transition
    retired = approval_module._new_transition(
        approval=issued,
        status="retired",
        occurred_at="2026-08-05T00:03:00.000000Z",
        request_id=None,
        reason_code="user_revoked",
        evidence_fingerprint=HASH,
        request_fingerprint=None,
        anti_replay_token_hash=None,
    )
    _assert_code(
        approval_module.APPROVAL_INCONSISTENT,
        lambda: approval_module.resolve_v03_approval_lifecycle(
            issued_approval=issued,
            consumption_artifact=consumed,
            retirement_artifact=retired,
            current_time=NOW + timedelta(minutes=4),
        ),
    )
    _assert_code(
        approval_module.APPROVAL_CHECKSUM,
        lambda: approval_module.resolve_v03_approval_lifecycle(
            issued_approval=issued,
            consumption_artifact=replace(consumed, transition_checksum=OTHER_HASH),
            current_time=NOW + timedelta(minutes=4),
        ),
    )
