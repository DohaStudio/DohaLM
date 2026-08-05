from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from src.training import v03_run_identity as identity_module
from src.training.v03_run_identity import (
    V03IdentityInventory,
    V03RunIdentityError,
    abandon_v03_run_reservation,
    build_v03_identity_inventory,
    commit_v03_run_identity,
    compute_next_v03_run_identity,
    format_v03_tokenization_run_id,
    initialize_v03_identity_ledger,
    load_v03_identity_ledger,
    load_v03_reservations,
    make_v03_historical_predecessor_entry,
    parse_v03_tokenization_run_id,
    reserve_v03_run_identity,
    retire_v03_run_identity,
)

SYNTHETIC_FIXTURE_MARKERS = frozenset(
    {
        "fake_dataset",
        "fake_git",
        "fake_predecessor",
        "fake_date",
        "fake_token",
        "no_real_artifact",
        "not_for_runtime",
        "not_approved",
    }
)
SOURCE_COMMIT = "1" * 40  # fake_git: schema requires an exact lowercase hex commit.
DATASET_ID = "synthetic_fake_dataset_no_real_artifact_not_for_runtime_not_approved"
DATASET_FINGERPRINT = "sha256:" + "2" * 64
OWNER_TOKEN = "synthetic_fake_token_not_for_runtime_not_approved_0000000000000000"
NOW = datetime(2026, 8, 5, 3, 0, tzinfo=timezone.utc)


@pytest.fixture
def ledger_root() -> Path:
    path = Path.cwd() / "tests" / f".v03-r3-synthetic-{uuid4().hex}"
    path.mkdir()
    initialize_v03_identity_ledger(path)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def inventory(root: Path, **external: tuple[str, ...]) -> V03IdentityInventory:
    return build_v03_identity_inventory(
        load_v03_identity_ledger(root).entries,
        load_v03_reservations(root),
        **external,
    )


def reserve(root: Path, sequence: int = 1, **kwargs: object):
    return reserve_v03_run_identity(
        root,
        parse_v03_tokenization_run_id(
            format_v03_tokenization_run_id(date(2026, 8, 5), sequence)
        ),
        inventory(root),
        source_commit=SOURCE_COMMIT,
        dataset_id=DATASET_ID,
        dataset_fingerprint=DATASET_FINGERPRINT,
        owner_token=OWNER_TOKEN,
        reserved_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        **kwargs,
    )


def assert_code(code: str, action) -> None:
    with pytest.raises(V03RunIdentityError) as caught:
        action()
    assert caught.value.code == code
    assert str(caught.value) == code


def test_fixture_declares_all_synthetic_only_markers() -> None:
    assert SYNTHETIC_FIXTURE_MARKERS == {
        "fake_dataset",
        "fake_git",
        "fake_predecessor",
        "fake_date",
        "fake_token",
        "no_real_artifact",
        "not_for_runtime",
        "not_approved",
    }


@pytest.mark.parametrize(
    "value",
    [
        "DOHALM-V0.3-TOKENIZATION-20260805-0001 ",
        "DOHALM-V0.3-TOKENIZATION-20260230-0001",
        "DOHALM-V0.3-TOKENIZATION-20260805-0000",
        "dohalm-v0.3-tokenization-20260805-0001",
    ],
)
def test_run_id_parser_is_strict(value: str) -> None:
    assert_code("V03_RUN_ID_INVALID", lambda: parse_v03_tokenization_run_id(value))


def test_run_id_format_and_sequence_exhaustion() -> None:
    value = format_v03_tokenization_run_id(date(2026, 8, 5), 7)
    parsed = parse_v03_tokenization_run_id(value)
    assert (parsed.local_date, parsed.sequence, parsed.value) == (
        date(2026, 8, 5),
        7,
        value,
    )
    assert_code(
        "V03_RUN_ID_SEQUENCE_EXHAUSTED",
        lambda: format_v03_tokenization_run_id(date(2026, 8, 5), 10000),
    )


def test_next_identity_does_not_reuse_abandoned_or_retired_sequence(
    ledger_root: Path,
) -> None:
    first = reserve(ledger_root)
    abandon_v03_run_reservation(
        ledger_root,
        first.reservation.reservation_id,
        reason_code="SYNTHETIC_ABANDON",
        abandoned_at=NOW + timedelta(minutes=1),
    )
    second_identity = compute_next_v03_run_identity(
        date(2026, 8, 5),
        load_v03_identity_ledger(ledger_root).entries,
        load_v03_reservations(ledger_root),
        inventory(ledger_root),
    )
    assert second_identity.sequence == 2
    assert (
        compute_next_v03_run_identity(
            date(2026, 8, 6), (), (), V03IdentityInventory()
        ).sequence
        == 1
    )


def test_predecessor_reference_is_excluded_from_sequence_calculation(
    ledger_root: Path,
) -> None:
    predecessor = make_v03_historical_predecessor_entry(
        "DOHALM-V0.3-TOKENIZATION-20260805-0042",
        source_commit=SOURCE_COMMIT,
        dataset_id=DATASET_ID,
        dataset_fingerprint=DATASET_FINGERPRINT,
        created_at=NOW,
    )
    other = Path.cwd() / "tests" / f".v03-r3-history-{uuid4().hex}"
    other.mkdir()
    try:
        initialize_v03_identity_ledger(other, [predecessor])
        next_identity = compute_next_v03_run_identity(
            date(2026, 8, 5),
            load_v03_identity_ledger(other).entries,
            load_v03_reservations(other),
            inventory(other),
        )
        assert next_identity.sequence == 1
    finally:
        shutil.rmtree(other, ignore_errors=True)


def test_reserve_writes_immutable_artifact_and_append_only_entry(
    ledger_root: Path,
) -> None:
    result = reserve(ledger_root)
    artifact = (
        ledger_root / "reservations" / f"{result.reservation.reservation_id}.json"
    )
    before = artifact.read_bytes()
    assert artifact.exists()
    assert load_v03_reservations(ledger_root) == (result.reservation,)
    assert load_v03_identity_ledger(ledger_root).entries == (result.ledger_entry,)
    assert artifact.read_bytes() == before
    assert result.reservation.status == "active"


def test_stale_inventory_and_cross_category_collision_fail_closed(
    ledger_root: Path,
) -> None:
    candidate = parse_v03_tokenization_run_id("DOHALM-V0.3-TOKENIZATION-20260805-0001")
    stale = inventory(ledger_root)
    reserve(ledger_root)
    assert_code(
        "V03_IDENTITY_INVENTORY_STALE",
        lambda: reserve_v03_run_identity(
            ledger_root,
            parse_v03_tokenization_run_id("DOHALM-V0.3-TOKENIZATION-20260805-0002"),
            stale,
            source_commit=SOURCE_COMMIT,
            dataset_id=DATASET_ID,
            dataset_fingerprint=DATASET_FINGERPRINT,
            owner_token=OWNER_TOKEN,
            reserved_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        ),
    )
    fresh_with_collision = inventory(ledger_root, approval_run_ids=(candidate.value,))
    assert_code(
        "V03_RUN_ID_CONFLICT",
        lambda: reserve_v03_run_identity(
            ledger_root,
            candidate,
            fresh_with_collision,
            source_commit=SOURCE_COMMIT,
            dataset_id=DATASET_ID,
            dataset_fingerprint=DATASET_FINGERPRINT,
            owner_token=OWNER_TOKEN,
            reserved_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        ),
    )


def test_reserve_requires_exact_next_sequence_and_seoul_date(
    ledger_root: Path,
) -> None:
    assert_code("V03_RUN_ID_CONFLICT", lambda: reserve(ledger_root, sequence=2))
    candidate = parse_v03_tokenization_run_id("DOHALM-V0.3-TOKENIZATION-20260804-0001")
    assert_code(
        "V03_RUN_ID_INVALID",
        lambda: reserve_v03_run_identity(
            ledger_root,
            candidate,
            inventory(ledger_root),
            source_commit=SOURCE_COMMIT,
            dataset_id=DATASET_ID,
            dataset_fingerprint=DATASET_FINGERPRINT,
            owner_token=OWNER_TOKEN,
            reserved_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        ),
    )


def test_racing_reservations_have_exactly_one_winner(ledger_root: Path) -> None:
    candidate = parse_v03_tokenization_run_id("DOHALM-V0.3-TOKENIZATION-20260805-0001")
    initial_inventory = inventory(ledger_root)

    def attempt() -> str:
        try:
            reserve_v03_run_identity(
                ledger_root,
                candidate,
                initial_inventory,
                source_commit=SOURCE_COMMIT,
                dataset_id=DATASET_ID,
                dataset_fingerprint=DATASET_FINGERPRINT,
                owner_token=OWNER_TOKEN,
                reserved_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            )
            return "winner"
        except V03RunIdentityError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: attempt(), range(2)))
    assert outcomes.count("winner") == 1
    assert (
        outcomes.count("V03_IDENTITY_LOCK_FAILED")
        + outcomes.count("V03_IDENTITY_INVENTORY_STALE")
        == 1
    )
    assert len(load_v03_identity_ledger(ledger_root).entries) == 1
    assert len(load_v03_reservations(ledger_root)) == 1


def test_lock_failure_has_stable_error_code(ledger_root: Path) -> None:
    (ledger_root / "ledger.jsonl.lifecycle.lock").write_text(
        "occupied", encoding="utf-8"
    )
    assert_code("V03_IDENTITY_LOCK_FAILED", lambda: reserve(ledger_root))


def test_reservation_is_cleaned_if_ledger_append_fails(
    ledger_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_append(*args: object, **kwargs: object) -> None:
        raise V03RunIdentityError("V03_LEDGER_INCONSISTENT")

    monkeypatch.setattr(identity_module, "_append_ledger_entry_locked", fail_append)
    assert_code("V03_LEDGER_INCONSISTENT", lambda: reserve(ledger_root))
    assert list((ledger_root / "reservations").iterdir()) == []
    assert load_v03_identity_ledger(ledger_root).entries == ()


def test_commit_is_exact_idempotent_and_reservation_remains_immutable(
    ledger_root: Path,
) -> None:
    reserved = reserve(ledger_root)
    reservation_path = (
        ledger_root / "reservations" / f"{reserved.reservation.reservation_id}.json"
    )
    original = reservation_path.read_bytes()
    committed = commit_v03_run_identity(
        ledger_root,
        reserved.reservation.reservation_id,
        reserved.reservation.run_id,
        approval_id="synthetic-approval-not-approved",
        request_id="synthetic-request-not-for-runtime",
        committed_at=NOW + timedelta(minutes=1),
    )
    repeated = commit_v03_run_identity(
        ledger_root,
        reserved.reservation.reservation_id,
        reserved.reservation.run_id,
        approval_id="synthetic-approval-not-approved",
        request_id="synthetic-request-not-for-runtime",
        committed_at=NOW + timedelta(minutes=2),
    )
    assert repeated == committed
    assert reservation_path.read_bytes() == original
    assert [
        entry.status for entry in load_v03_identity_ledger(ledger_root).entries
    ] == ["reserved", "committed"]
    assert_code(
        "V03_RESERVATION_STATE_INVALID",
        lambda: commit_v03_run_identity(
            ledger_root,
            reserved.reservation.reservation_id,
            reserved.reservation.run_id,
            approval_id="conflicting-synthetic-approval",
            request_id="synthetic-request-not-for-runtime",
            committed_at=NOW + timedelta(minutes=2),
        ),
    )


def test_expired_commit_fails(ledger_root: Path) -> None:
    reserved = reserve(ledger_root)
    assert_code(
        "V03_RESERVATION_EXPIRED",
        lambda: commit_v03_run_identity(
            ledger_root,
            reserved.reservation.reservation_id,
            reserved.reservation.run_id,
            committed_at=NOW + timedelta(hours=2),
        ),
    )


def test_retire_validates_replacement_lineage_and_is_terminal(
    ledger_root: Path,
) -> None:
    reserved = reserve(ledger_root)
    committed = commit_v03_run_identity(
        ledger_root,
        reserved.reservation.reservation_id,
        reserved.reservation.run_id,
        committed_at=NOW + timedelta(minutes=1),
    )
    assert committed.run_id == reserved.reservation.run_id
    assert_code(
        "V03_PREDECESSOR_INVALID",
        lambda: retire_v03_run_identity(
            ledger_root,
            reserved.reservation.run_id,
            reason_code="SYNTHETIC_RETIRE",
            replacement_run_id="DOHALM-V0.3-TOKENIZATION-20260805-0002",
            retired_at=NOW + timedelta(minutes=2),
        ),
    )
    retired = retire_v03_run_identity(
        ledger_root,
        reserved.reservation.run_id,
        reason_code="SYNTHETIC_RETIRE",
        retired_at=NOW + timedelta(minutes=2),
    )
    assert retired.status == "retired"
    assert_code(
        "V03_RESERVATION_STATE_INVALID",
        lambda: retire_v03_run_identity(
            ledger_root,
            reserved.reservation.run_id,
            reason_code="SYNTHETIC_RETIRE_AGAIN",
            retired_at=NOW + timedelta(minutes=3),
        ),
    )


def test_completed_run_retirement_is_forbidden(ledger_root: Path) -> None:
    reserved = reserve(ledger_root)
    commit_v03_run_identity(
        ledger_root,
        reserved.reservation.reservation_id,
        reserved.reservation.run_id,
        committed_at=NOW + timedelta(minutes=1),
    )
    with identity_module._ledger_lock(ledger_root):
        snapshot = load_v03_identity_ledger(ledger_root)
        completed = identity_module._transition(
            snapshot.entries[-1],
            "completed",
            identity_module._timestamp(NOW + timedelta(minutes=2)),
        )
        identity_module._append_ledger_entry_locked(ledger_root, snapshot, completed)
    assert_code(
        "V03_RESERVATION_STATE_INVALID",
        lambda: retire_v03_run_identity(
            ledger_root,
            reserved.reservation.run_id,
            reason_code="SYNTHETIC_COMPLETED_RETIRE_FORBIDDEN",
            retired_at=NOW + timedelta(minutes=3),
        ),
    )


def test_valid_historical_predecessor_can_be_referenced() -> None:
    root = Path.cwd() / "tests" / f".v03-r3-predecessor-{uuid4().hex}"
    root.mkdir()
    try:
        predecessor_id = "DOHALM-V0.3-TOKENIZATION-20260804-0001"
        predecessor = make_v03_historical_predecessor_entry(
            predecessor_id,
            source_commit=SOURCE_COMMIT,
            dataset_id=DATASET_ID,
            dataset_fingerprint=DATASET_FINGERPRINT,
            created_at=NOW - timedelta(days=1),
        )
        initialize_v03_identity_ledger(root, [predecessor])
        result = reserve(root, predecessor_run_id=predecessor_id)
        assert result.ledger_entry.predecessor_run_id == predecessor_id
        assert result.ledger_entry.purpose == "canonical_recovery_execution"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_missing_or_self_predecessor_is_rejected(ledger_root: Path) -> None:
    missing = "DOHALM-V0.3-TOKENIZATION-20260804-0001"
    assert_code(
        "V03_PREDECESSOR_INVALID",
        lambda: reserve(ledger_root, predecessor_run_id=missing),
    )


@pytest.mark.parametrize(
    "mutation", ["noncanonical", "duplicate_key", "checksum", "truncated"]
)
def test_ledger_corruption_is_rejected(ledger_root: Path, mutation: str) -> None:
    reserve(ledger_root)
    ledger = ledger_root / "ledger.jsonl"
    data = json.loads(ledger.read_text(encoding="utf-8"))
    if mutation == "noncanonical":
        ledger.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    elif mutation == "duplicate_key":
        raw = ledger.read_text(encoding="utf-8")
        ledger.write_text(raw.replace("{", '{"schema_version":1,', 1), encoding="utf-8")
    elif mutation == "checksum":
        data["entry_checksum"] = "sha256:" + "0" * 64
        ledger.write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
    else:
        ledger.write_bytes(ledger.read_bytes().removesuffix(b"\n"))
    expected = (
        "V03_LEDGER_INCONSISTENT" if mutation == "checksum" else "V03_LEDGER_INVALID"
    )
    assert_code(expected, lambda: load_v03_identity_ledger(ledger_root))


def test_symlinked_ledger_is_rejected(
    ledger_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = ledger_root / "ledger.jsonl"
    original = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda path: path == ledger or original(path)
    )
    assert_code("V03_LEDGER_NOT_FOUND", lambda: load_v03_identity_ledger(ledger_root))


def test_reservation_checksum_mismatch_is_rejected(ledger_root: Path) -> None:
    result = reserve(ledger_root)
    path = ledger_root / "reservations" / f"{result.reservation.reservation_id}.json"
    data = asdict(result.reservation)
    data["owner_token_hash"] = "sha256:" + "9" * 64
    path.write_bytes(
        json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        + b"\n"
    )
    assert_code(
        "V03_RESERVATION_CHECKSUM_MISMATCH", lambda: load_v03_reservations(ledger_root)
    )
