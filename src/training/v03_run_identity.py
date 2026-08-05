"""Synthetic-only V0.3 tokenization run identity ledger.

This module defines and validates identity records.  It never discovers a
ledger, reads payload data, or authorizes tokenization/training execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.data.processing.approval import (
    ProcessingApprovalError,
    approval_lifecycle_lock,
)


class V03RunIdentityError(RuntimeError):
    """A fail-closed identity error whose message exposes only a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


RUN_ID_INVALID = "V03_RUN_ID_INVALID"
SEQUENCE_EXHAUSTED = "V03_RUN_ID_SEQUENCE_EXHAUSTED"
RUN_ID_CONFLICT = "V03_RUN_ID_CONFLICT"
LEDGER_NOT_FOUND = "V03_LEDGER_NOT_FOUND"
LEDGER_INVALID = "V03_LEDGER_INVALID"
LEDGER_INCONSISTENT = "V03_LEDGER_INCONSISTENT"
RESERVATION_INVALID = "V03_RESERVATION_INVALID"
RESERVATION_EXISTS = "V03_RESERVATION_ALREADY_EXISTS"
RESERVATION_EXPIRED = "V03_RESERVATION_EXPIRED"
RESERVATION_STATE_INVALID = "V03_RESERVATION_STATE_INVALID"
RESERVATION_CHECKSUM_MISMATCH = "V03_RESERVATION_CHECKSUM_MISMATCH"
PREDECESSOR_INVALID = "V03_PREDECESSOR_INVALID"
INVENTORY_STALE = "V03_IDENTITY_INVENTORY_STALE"
LOCK_FAILED = "V03_IDENTITY_LOCK_FAILED"

SCHEMA_VERSION = 1
RUN_ID_PREFIX = "DOHALM-V0.3-TOKENIZATION-"
RUN_ID_RE = re.compile(r"^DOHALM-V0\.3-TOKENIZATION-(\d{8})-(\d{4})$")
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,255}$")
REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
RUN_KINDS = frozenset({"canonical_execution", "predecessor_failure_reference"})
LEDGER_STATES = frozenset(
    {"reserved", "committed", "abandoned", "retired", "completed", "failed"}
)
RESERVATION_STATES = frozenset(
    {"active", "committed", "abandoned", "expired", "retired"}
)
PURPOSES = frozenset({"canonical_recovery_execution", "historical_failure_reference"})
_TRANSITIONS = {
    "reserved": frozenset({"committed", "abandoned", "retired"}),
    "committed": frozenset({"completed", "failed", "retired"}),
    "failed": frozenset({"retired"}),
    "completed": frozenset(),
    "abandoned": frozenset(),
    "retired": frozenset(),
}


@dataclass(frozen=True)
class V03RunIdentity:
    local_date: date
    sequence: int
    value: str


@dataclass(frozen=True)
class V03LedgerEntry:
    schema_version: int
    ledger_entry_id: str
    run_id: str
    run_kind: str
    status: str
    created_at: str
    reserved_at: str | None
    committed_at: str | None
    retired_at: str | None
    predecessor_run_id: str | None
    replacement_run_id: str | None
    source_commit: str
    dataset_id: str
    dataset_fingerprint: str
    purpose: str
    reservation_id: str
    reservation_checksum: str
    reason_code: str | None
    metadata_fingerprint: str
    entry_checksum: str


@dataclass(frozen=True)
class V03Reservation:
    schema_version: int
    reservation_id: str
    run_id: str
    ledger_root_id: str
    source_commit: str
    dataset_id: str
    dataset_fingerprint: str
    predecessor_run_id: str | None
    reserved_at: str
    expires_at: str
    owner_token_hash: str
    reservation_nonce: str
    reservation_fingerprint: str
    reservation_checksum: str
    status: str


@dataclass(frozen=True)
class V03CommittedIdentity:
    schema_version: int
    reservation_id: str
    run_id: str
    approval_id: str | None
    request_id: str | None
    committed_at: str
    reservation_checksum: str
    commit_fingerprint: str
    commit_checksum: str


@dataclass(frozen=True)
class V03IdentityInventory:
    ledger_run_ids: tuple[str, ...] = ()
    active_reservation_run_ids: tuple[str, ...] = ()
    committed_run_ids: tuple[str, ...] = ()
    retired_run_ids: tuple[str, ...] = ()
    final_path_run_ids: tuple[str, ...] = ()
    staging_path_run_ids: tuple[str, ...] = ()
    failure_path_run_ids: tuple[str, ...] = ()
    emergency_artifact_run_ids: tuple[str, ...] = ()
    approval_run_ids: tuple[str, ...] = ()
    runtime_request_run_ids: tuple[str, ...] = ()
    history_run_ids: tuple[str, ...] = ()
    ledger_fingerprint: str = ""
    reservations_fingerprint: str = ""

    def __post_init__(self) -> None:
        for name, values in asdict(self).items():
            if not name.endswith("_run_ids"):
                continue
            if not isinstance(values, tuple) or values != tuple(sorted(set(values))):
                _fail(INVENTORY_STALE)
            for run_id in values:
                parse_v03_tokenization_run_id(run_id)
        for value in (self.ledger_fingerprint, self.reservations_fingerprint):
            if value and HASH_RE.fullmatch(value) is None:
                _fail(INVENTORY_STALE)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(asdict(self))

    def all_run_ids(self) -> frozenset[str]:
        values: set[str] = set()
        for key, item in asdict(self).items():
            if key.endswith("_run_ids"):
                values.update(item)
        return frozenset(values)


@dataclass(frozen=True)
class V03LedgerSnapshot:
    entries: tuple[V03LedgerEntry, ...]
    ledger_fingerprint: str


@dataclass(frozen=True)
class V03ReservationResult:
    reservation: V03Reservation
    ledger_entry: V03LedgerEntry
    ledger_fingerprint: str


def _fail(code: str) -> None:
    raise V03RunIdentityError(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        _fail(LEDGER_INVALID)


def _fingerprint(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        _fail(RESERVATION_INVALID)
    return (
        current.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _parse_timestamp(value: object, code: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _fail(code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _fail(code)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(code)
    return parsed.astimezone(timezone.utc)


def parse_v03_tokenization_run_id(value: str) -> V03RunIdentity:
    if not isinstance(value, str):
        _fail(RUN_ID_INVALID)
    match = RUN_ID_RE.fullmatch(value)
    if match is None:
        _fail(RUN_ID_INVALID)
    try:
        compact_date = match.group(1)
        local_date = date(
            int(compact_date[:4]), int(compact_date[4:6]), int(compact_date[6:])
        )
    except ValueError:
        _fail(RUN_ID_INVALID)
    sequence = int(match.group(2))
    if sequence < 1:
        _fail(RUN_ID_INVALID)
    return V03RunIdentity(local_date=local_date, sequence=sequence, value=value)


def format_v03_tokenization_run_id(local_date: date, sequence: int) -> str:
    if (
        not isinstance(local_date, date)
        or isinstance(local_date, datetime)
        or not isinstance(sequence, int)
    ):
        _fail(RUN_ID_INVALID)
    if sequence < 1 or sequence > 9999:
        _fail(SEQUENCE_EXHAUSTED if sequence > 9999 else RUN_ID_INVALID)
    return f"{RUN_ID_PREFIX}{local_date:%Y%m%d}-{sequence:04d}"


def _strict_object(data: object, fields: set[str], code: str) -> Mapping[str, object]:
    if not isinstance(data, dict) or set(data) != fields:
        _fail(code)
    return data


def _load_json(data: bytes, code: str) -> Mapping[str, object]:
    def reject_duplicates(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail(code)
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(code)
    if not isinstance(value, dict):
        _fail(code)
    return value


def _validate_common(
    source_commit: object, dataset_id: object, dataset_fingerprint: object, code: str
) -> None:
    if not isinstance(source_commit, str) or HEX40_RE.fullmatch(source_commit) is None:
        _fail(code)
    if not isinstance(dataset_id, str) or IDENTIFIER_RE.fullmatch(dataset_id) is None:
        _fail(code)
    if (
        not isinstance(dataset_fingerprint, str)
        or HASH_RE.fullmatch(dataset_fingerprint) is None
    ):
        _fail(code)


def _without(value: object, field: str) -> dict[str, object]:
    result = asdict(value)  # type: ignore[arg-type]
    result.pop(field)
    return result


def validate_v03_reservation(value: V03Reservation) -> None:
    if value.schema_version != SCHEMA_VERSION or value.status not in RESERVATION_STATES:
        _fail(RESERVATION_INVALID)
    parse_v03_tokenization_run_id(value.run_id)
    _validate_common(
        value.source_commit,
        value.dataset_id,
        value.dataset_fingerprint,
        RESERVATION_INVALID,
    )
    if any(
        IDENTIFIER_RE.fullmatch(item) is None
        for item in (value.reservation_id, value.ledger_root_id)
    ):
        _fail(RESERVATION_INVALID)
    if value.predecessor_run_id is not None:
        parse_v03_tokenization_run_id(value.predecessor_run_id)
        if value.predecessor_run_id == value.run_id:
            _fail(PREDECESSOR_INVALID)
    reserved_at = _parse_timestamp(value.reserved_at, RESERVATION_INVALID)
    expires_at = _parse_timestamp(value.expires_at, RESERVATION_INVALID)
    if expires_at <= reserved_at or HASH_RE.fullmatch(value.owner_token_hash) is None:
        _fail(RESERVATION_INVALID)
    if re.fullmatch(r"[0-9a-f]{64}", value.reservation_nonce) is None:
        _fail(RESERVATION_INVALID)
    stable = {
        key: item
        for key, item in asdict(value).items()
        if key not in {"reservation_fingerprint", "reservation_checksum", "status"}
    }
    if value.reservation_fingerprint != _fingerprint(stable):
        _fail(RESERVATION_CHECKSUM_MISMATCH)
    if value.reservation_checksum != _fingerprint(
        _without(value, "reservation_checksum")
    ):
        _fail(RESERVATION_CHECKSUM_MISMATCH)


def validate_v03_ledger_entry(value: V03LedgerEntry) -> None:
    if (
        value.schema_version != SCHEMA_VERSION
        or value.run_kind not in RUN_KINDS
        or value.status not in LEDGER_STATES
    ):
        _fail(LEDGER_INVALID)
    parse_v03_tokenization_run_id(value.run_id)
    _validate_common(
        value.source_commit, value.dataset_id, value.dataset_fingerprint, LEDGER_INVALID
    )
    if any(
        IDENTIFIER_RE.fullmatch(item) is None
        for item in (value.ledger_entry_id, value.reservation_id)
    ):
        _fail(LEDGER_INVALID)
    if (
        HASH_RE.fullmatch(value.reservation_checksum) is None
        or value.purpose not in PURPOSES
    ):
        _fail(LEDGER_INVALID)
    _parse_timestamp(value.created_at, LEDGER_INVALID)
    for item in (value.reserved_at, value.committed_at, value.retired_at):
        if item is not None:
            _parse_timestamp(item, LEDGER_INVALID)
    if value.status == "reserved" and value.reserved_at is None:
        _fail(LEDGER_INVALID)
    if value.status in {"committed", "completed"} and value.committed_at is None:
        _fail(LEDGER_INVALID)
    if value.status in {"abandoned", "retired"} and (
        value.retired_at is None or value.reason_code is None
    ):
        _fail(LEDGER_INVALID)
    if value.replacement_run_id is not None and value.status != "retired":
        _fail(LEDGER_INVALID)
    for item in (value.predecessor_run_id, value.replacement_run_id):
        if item is not None:
            parse_v03_tokenization_run_id(item)
            if item == value.run_id:
                _fail(PREDECESSOR_INVALID)
    if value.reason_code is not None and REASON_RE.fullmatch(value.reason_code) is None:
        _fail(LEDGER_INVALID)
    stable = {
        "run_id": value.run_id,
        "run_kind": value.run_kind,
        "predecessor_run_id": value.predecessor_run_id,
        "source_commit": value.source_commit,
        "dataset_id": value.dataset_id,
        "dataset_fingerprint": value.dataset_fingerprint,
        "purpose": value.purpose,
        "reservation_id": value.reservation_id,
        "reservation_checksum": value.reservation_checksum,
    }
    if value.metadata_fingerprint != _fingerprint(stable):
        _fail(LEDGER_INCONSISTENT)
    if value.entry_checksum != _fingerprint(_without(value, "entry_checksum")):
        _fail(LEDGER_INCONSISTENT)


def _entry_from_mapping(data: Mapping[str, object]) -> V03LedgerEntry:
    fields = set(V03LedgerEntry.__dataclass_fields__)
    strict = _strict_object(data, fields, LEDGER_INVALID)
    try:
        entry = V03LedgerEntry(**strict)  # type: ignore[arg-type]
    except TypeError:
        _fail(LEDGER_INVALID)
    validate_v03_ledger_entry(entry)
    return entry


def _reservation_from_mapping(data: Mapping[str, object]) -> V03Reservation:
    fields = set(V03Reservation.__dataclass_fields__)
    strict = _strict_object(data, fields, RESERVATION_INVALID)
    try:
        reservation = V03Reservation(**strict)  # type: ignore[arg-type]
    except TypeError:
        _fail(RESERVATION_INVALID)
    validate_v03_reservation(reservation)
    return reservation


def _validate_root(root: str | Path, *, require_ledger: bool = True) -> Path:
    path = Path(root)
    if (
        not path.is_absolute()
        or not path.exists()
        or not path.is_dir()
        or path.is_symlink()
    ):
        _fail(LEDGER_NOT_FOUND)
    ledger = path / "ledger.jsonl"
    if require_ledger and (
        not ledger.exists() or not ledger.is_file() or ledger.is_symlink()
    ):
        _fail(LEDGER_NOT_FOUND)
    return path


def _validate_ledger_sequence(entries: Sequence[V03LedgerEntry]) -> None:
    entry_ids: set[str] = set()
    latest: dict[str, V03LedgerEntry] = {}
    predecessors: dict[str, str] = {}
    for entry in entries:
        if entry.ledger_entry_id in entry_ids:
            _fail(LEDGER_INCONSISTENT)
        entry_ids.add(entry.ledger_entry_id)
        previous = latest.get(entry.run_id)
        if previous is None:
            allowed_initial = (
                {"reserved"}
                if entry.run_kind == "canonical_execution"
                else {"failed", "retired"}
            )
            if entry.status not in allowed_initial:
                _fail(LEDGER_INCONSISTENT)
        else:
            if entry.status not in _TRANSITIONS[previous.status]:
                _fail(LEDGER_INCONSISTENT)
            immutable = (
                "run_kind",
                "predecessor_run_id",
                "reserved_at",
                "source_commit",
                "dataset_id",
                "dataset_fingerprint",
                "purpose",
                "reservation_id",
                "reservation_checksum",
                "metadata_fingerprint",
            )
            if any(
                getattr(entry, name) != getattr(previous, name) for name in immutable
            ):
                _fail(LEDGER_INCONSISTENT)
            if _parse_timestamp(entry.created_at, LEDGER_INVALID) < _parse_timestamp(
                previous.created_at, LEDGER_INVALID
            ):
                _fail(LEDGER_INCONSISTENT)
        latest[entry.run_id] = entry
        if entry.predecessor_run_id is not None:
            predecessors[entry.run_id] = entry.predecessor_run_id
    for start in predecessors:
        seen = {start}
        current = start
        while current in predecessors:
            current = predecessors[current]
            if current in seen:
                _fail(PREDECESSOR_INVALID)
            seen.add(current)
    for entry in entries:
        if entry.predecessor_run_id is not None:
            predecessor = latest.get(entry.predecessor_run_id)
            if predecessor is None or predecessor.status not in {"failed", "retired"}:
                _fail(PREDECESSOR_INVALID)


def load_v03_identity_ledger(ledger_root: str | Path) -> V03LedgerSnapshot:
    root = _validate_root(ledger_root)
    ledger = root / "ledger.jsonl"
    try:
        payload = ledger.read_bytes()
    except OSError:
        _fail(LEDGER_INVALID)
    if payload and not payload.endswith(b"\n"):
        _fail(LEDGER_INVALID)
    entries: list[V03LedgerEntry] = []
    for raw_line in payload.splitlines():
        if not raw_line:
            _fail(LEDGER_INVALID)
        data = _load_json(raw_line, LEDGER_INVALID)
        if _canonical(data) != raw_line:
            _fail(LEDGER_INVALID)
        entries.append(_entry_from_mapping(data))
    _validate_ledger_sequence(entries)
    return V03LedgerSnapshot(
        tuple(entries), _fingerprint([entry.entry_checksum for entry in entries])
    )


def load_v03_reservations(ledger_root: str | Path) -> tuple[V03Reservation, ...]:
    root = _validate_root(ledger_root)
    directory = root / "reservations"
    if not directory.exists() or not directory.is_dir() or directory.is_symlink():
        _fail(RESERVATION_INVALID)
    reservations: list[V03Reservation] = []
    try:
        paths = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError:
        _fail(RESERVATION_INVALID)
    for path in paths:
        if path.suffix != ".json" or path.is_symlink() or not path.is_file():
            _fail(RESERVATION_INVALID)
        try:
            payload = path.read_bytes()
        except OSError:
            _fail(RESERVATION_INVALID)
        data = _load_json(payload, RESERVATION_INVALID)
        if _canonical(data) + b"\n" != payload:
            _fail(RESERVATION_INVALID)
        reservation = _reservation_from_mapping(data)
        if path.name != f"{reservation.reservation_id}.json":
            _fail(RESERVATION_INVALID)
        reservations.append(reservation)
    ids = [item.reservation_id for item in reservations]
    runs = [item.run_id for item in reservations]
    if len(ids) != len(set(ids)) or len(runs) != len(set(runs)):
        _fail(RESERVATION_INVALID)
    return tuple(reservations)


def reservations_fingerprint(reservations: Iterable[V03Reservation]) -> str:
    return _fingerprint(sorted(item.reservation_checksum for item in reservations))


def build_v03_identity_inventory(
    entries: Sequence[V03LedgerEntry],
    reservations: Sequence[V03Reservation],
    **external: tuple[str, ...],
) -> V03IdentityInventory:
    permitted = set(V03IdentityInventory.__dataclass_fields__) - {
        "ledger_run_ids",
        "active_reservation_run_ids",
        "ledger_fingerprint",
        "reservations_fingerprint",
    }
    if not set(external) <= permitted:
        _fail(INVENTORY_STALE)
    values: dict[str, object] = {}
    for name in permitted:
        run_ids = tuple(sorted(set(external.get(name, ()))))
        for run_id in run_ids:
            parse_v03_tokenization_run_id(run_id)
        values[name] = run_ids
    return V03IdentityInventory(
        ledger_run_ids=tuple(sorted({item.run_id for item in entries})),
        active_reservation_run_ids=tuple(
            sorted({item.run_id for item in reservations})
        ),
        ledger_fingerprint=_fingerprint([item.entry_checksum for item in entries]),
        reservations_fingerprint=reservations_fingerprint(reservations),
        **values,  # type: ignore[arg-type]
    )


def compute_next_v03_run_identity(
    local_date: date,
    entries: Sequence[V03LedgerEntry],
    reservations: Sequence[V03Reservation],
    inventory: V03IdentityInventory,
) -> V03RunIdentity:
    if not isinstance(local_date, date) or isinstance(local_date, datetime):
        _fail(RUN_ID_INVALID)
    values = [
        item.run_id
        for item in entries
        if item.run_kind != "predecessor_failure_reference"
    ]
    values.extend(item.run_id for item in reservations)
    inventory_values = inventory.all_run_ids() - set(inventory.ledger_run_ids)
    inventory_values -= set(inventory.active_reservation_run_ids)
    inventory_values -= set(inventory.history_run_ids)
    values.extend(inventory_values)
    sequences = [
        parsed.sequence
        for value in values
        if (parsed := parse_v03_tokenization_run_id(value)).local_date == local_date
    ]
    next_sequence = max(sequences, default=0) + 1
    if next_sequence > 9999:
        _fail(SEQUENCE_EXHAUSTED)
    value = format_v03_tokenization_run_id(local_date, next_sequence)
    return V03RunIdentity(local_date, next_sequence, value)


def _metadata(entry: V03LedgerEntry) -> dict[str, object]:
    return {
        "run_id": entry.run_id,
        "run_kind": entry.run_kind,
        "predecessor_run_id": entry.predecessor_run_id,
        "source_commit": entry.source_commit,
        "dataset_id": entry.dataset_id,
        "dataset_fingerprint": entry.dataset_fingerprint,
        "purpose": entry.purpose,
        "reservation_id": entry.reservation_id,
        "reservation_checksum": entry.reservation_checksum,
    }


def _make_entry(**values: object) -> V03LedgerEntry:
    base = V03LedgerEntry(
        schema_version=SCHEMA_VERSION,
        metadata_fingerprint="",
        entry_checksum="",
        **values,
    )  # type: ignore[arg-type]
    base = replace(base, metadata_fingerprint=_fingerprint(_metadata(base)))
    base = replace(base, entry_checksum=_fingerprint(_without(base, "entry_checksum")))
    validate_v03_ledger_entry(base)
    return base


def _transition(
    previous: V03LedgerEntry,
    status: str,
    at: str,
    *,
    reason_code: str | None = None,
    replacement_run_id: str | None = None,
) -> V03LedgerEntry:
    values = asdict(previous)
    values.update(
        {
            "ledger_entry_id": "entry-v1-" + secrets.token_hex(32),
            "status": status,
            "created_at": at,
            "committed_at": at if status == "committed" else previous.committed_at,
            "retired_at": at
            if status in {"retired", "abandoned"}
            else previous.retired_at,
            "reason_code": reason_code,
            "replacement_run_id": replacement_run_id,
            "entry_checksum": "",
        }
    )
    entry = V03LedgerEntry(**values)
    entry = replace(
        entry, entry_checksum=_fingerprint(_without(entry, "entry_checksum"))
    )
    validate_v03_ledger_entry(entry)
    return entry


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_no_replace(path: Path, payload: bytes, exists_code: str) -> None:
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(12))
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        _fsync_directory(path.parent)
    except FileExistsError:
        _fail(exists_code)
    except OSError:
        _fail(RESERVATION_INVALID)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _append_ledger_entry_locked(
    root: Path, expected: V03LedgerSnapshot, entry: V03LedgerEntry
) -> V03LedgerSnapshot:
    ledger = root / "ledger.jsonl"
    temporary: Path | None = None
    try:
        original = ledger.read_bytes()
        if (
            load_v03_identity_ledger(root).ledger_fingerprint
            != expected.ledger_fingerprint
        ):
            _fail(INVENTORY_STALE)
        updated = original + _canonical(asdict(entry)) + b"\n"
        temporary = root / (".ledger-" + secrets.token_hex(12) + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if ledger.read_bytes() != original:
            temporary.unlink(missing_ok=True)
            _fail(INVENTORY_STALE)
        os.replace(temporary, ledger)
        _fsync_directory(root)
    except V03RunIdentityError:
        raise
    except OSError:
        _fail(LEDGER_INCONSISTENT)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    reloaded = load_v03_identity_ledger(root)
    if (
        not reloaded.entries
        or reloaded.entries[-1].entry_checksum != entry.entry_checksum
    ):
        _fail(LEDGER_INCONSISTENT)
    return reloaded


@contextmanager
def _ledger_lock(root: Path) -> Iterator[None]:
    try:
        with approval_lifecycle_lock(root / "ledger.jsonl"):
            yield
    except V03RunIdentityError:
        raise
    except (ProcessingApprovalError, OSError):
        _fail(LOCK_FAILED)


def initialize_v03_identity_ledger(
    ledger_root: str | Path, historical_entries: Sequence[V03LedgerEntry] = ()
) -> V03LedgerSnapshot:
    root = _validate_root(ledger_root, require_ledger=False)
    try:
        if any(root.iterdir()):
            _fail(LEDGER_INCONSISTENT)
    except OSError:
        _fail(LEDGER_INCONSISTENT)
    _validate_ledger_sequence(historical_entries)
    for entry in historical_entries:
        validate_v03_ledger_entry(entry)
    payload = b"".join(
        _canonical(asdict(entry)) + b"\n" for entry in historical_entries
    )
    try:
        for name in ("reservations", "committed", "retired"):
            (root / name).mkdir()
        descriptor = os.open(
            root / "ledger.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(root)
    except OSError:
        _fail(LEDGER_INCONSISTENT)
    return load_v03_identity_ledger(root)


def _latest(entries: Sequence[V03LedgerEntry]) -> dict[str, V03LedgerEntry]:
    return {entry.run_id: entry for entry in entries}


def _entry_is_visible(root: Path, entry_checksum: str) -> bool:
    try:
        snapshot = load_v03_identity_ledger(root)
    except V03RunIdentityError:
        _fail(LEDGER_INCONSISTENT)
    return any(entry.entry_checksum == entry_checksum for entry in snapshot.entries)


def _validate_predecessor(
    run_id: str, predecessor_run_id: str | None, entries: Sequence[V03LedgerEntry]
) -> None:
    if predecessor_run_id is None:
        return
    if predecessor_run_id == run_id:
        _fail(PREDECESSOR_INVALID)
    latest = _latest(entries)
    predecessor = latest.get(predecessor_run_id)
    if predecessor is None or predecessor.status not in {"failed", "retired"}:
        _fail(PREDECESSOR_INVALID)
    current = predecessor
    seen = {run_id}
    while current.predecessor_run_id is not None:
        if current.run_id in seen:
            _fail(PREDECESSOR_INVALID)
        seen.add(current.run_id)
        parent = latest.get(current.predecessor_run_id)
        if parent is None:
            _fail(PREDECESSOR_INVALID)
        current = parent


def reserve_v03_run_identity(
    ledger_root: str | Path,
    identity: V03RunIdentity,
    inventory: V03IdentityInventory,
    *,
    source_commit: str,
    dataset_id: str,
    dataset_fingerprint: str,
    owner_token: str,
    expires_at: datetime,
    predecessor_run_id: str | None = None,
    reserved_at: datetime | None = None,
) -> V03ReservationResult:
    root = _validate_root(ledger_root)
    if (
        parse_v03_tokenization_run_id(identity.value) != identity
        or not isinstance(owner_token, str)
        or len(owner_token.encode()) < 32
    ):
        _fail(RESERVATION_INVALID)
    _validate_common(
        source_commit, dataset_id, dataset_fingerprint, RESERVATION_INVALID
    )
    reserved_text = _timestamp(reserved_at)
    expires_text = _timestamp(expires_at)
    reserved_instant = _parse_timestamp(reserved_text, RESERVATION_INVALID)
    if (
        identity.local_date
        != reserved_instant.astimezone(ZoneInfo("Asia/Seoul")).date()
    ):
        _fail(RUN_ID_INVALID)
    if _parse_timestamp(expires_text, RESERVATION_INVALID) <= _parse_timestamp(
        reserved_text, RESERVATION_INVALID
    ):
        _fail(RESERVATION_INVALID)
    with _ledger_lock(root):
        snapshot = load_v03_identity_ledger(root)
        reservations = load_v03_reservations(root)
        actual_ledger_run_ids = tuple(
            sorted({item.run_id for item in snapshot.entries})
        )
        actual_reservation_run_ids = tuple(
            sorted({item.run_id for item in reservations})
        )
        if (
            snapshot.ledger_fingerprint != inventory.ledger_fingerprint
            or reservations_fingerprint(reservations)
            != inventory.reservations_fingerprint
            or inventory.ledger_run_ids != actual_ledger_run_ids
            or inventory.active_reservation_run_ids != actual_reservation_run_ids
        ):
            _fail(INVENTORY_STALE)
        expected_identity = compute_next_v03_run_identity(
            identity.local_date, snapshot.entries, reservations, inventory
        )
        if identity != expected_identity:
            _fail(RUN_ID_CONFLICT)
        if (
            identity.value in inventory.all_run_ids()
            or identity.value in {item.run_id for item in reservations}
            or identity.value in {item.run_id for item in snapshot.entries}
        ):
            _fail(RUN_ID_CONFLICT)
        _validate_predecessor(identity.value, predecessor_run_id, snapshot.entries)
        nonce = secrets.token_hex(32)
        reservation_id = (
            "reservation-v1-"
            + hashlib.sha256((identity.value + ":" + nonce).encode()).hexdigest()
        )
        values: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "reservation_id": reservation_id,
            "run_id": identity.value,
            "ledger_root_id": "ledger-v1-"
            + hashlib.sha256(b"dohalm-v03-run-identity-ledger-v1").hexdigest(),
            "source_commit": source_commit,
            "dataset_id": dataset_id,
            "dataset_fingerprint": dataset_fingerprint,
            "predecessor_run_id": predecessor_run_id,
            "reserved_at": reserved_text,
            "expires_at": expires_text,
            "owner_token_hash": _fingerprint(
                {"domain": "v03-owner-token-v1", "token": owner_token}
            ),
            "reservation_nonce": nonce,
            "reservation_fingerprint": "",
            "reservation_checksum": "",
            "status": "active",
        }
        stable = {
            key: item
            for key, item in values.items()
            if key not in {"reservation_fingerprint", "reservation_checksum", "status"}
        }
        values["reservation_fingerprint"] = _fingerprint(stable)
        reservation = V03Reservation(**values)  # type: ignore[arg-type]
        reservation = replace(
            reservation,
            reservation_checksum=_fingerprint(
                _without(reservation, "reservation_checksum")
            ),
        )
        validate_v03_reservation(reservation)
        entry = _make_entry(
            ledger_entry_id="entry-v1-" + secrets.token_hex(32),
            run_id=identity.value,
            run_kind="canonical_execution",
            status="reserved",
            created_at=reserved_text,
            reserved_at=reserved_text,
            committed_at=None,
            retired_at=None,
            predecessor_run_id=predecessor_run_id,
            replacement_run_id=None,
            source_commit=source_commit,
            dataset_id=dataset_id,
            dataset_fingerprint=dataset_fingerprint,
            purpose="canonical_recovery_execution",
            reservation_id=reservation_id,
            reservation_checksum=reservation.reservation_checksum,
            reason_code=None,
        )
        path = root / "reservations" / f"{reservation_id}.json"
        _publish_no_replace(
            path, _canonical(asdict(reservation)) + b"\n", RESERVATION_EXISTS
        )
        try:
            updated = _append_ledger_entry_locked(root, snapshot, entry)
        except Exception:
            if _entry_is_visible(root, entry.entry_checksum):
                _fail(LEDGER_INCONSISTENT)
            try:
                path.unlink()
                _fsync_directory(path.parent)
            except OSError:
                _fail(LEDGER_INCONSISTENT)
            raise
        return V03ReservationResult(reservation, entry, updated.ledger_fingerprint)


def _load_committed(path: Path) -> V03CommittedIdentity:
    try:
        payload = path.read_bytes()
    except OSError:
        _fail(RESERVATION_INVALID)
    data = _load_json(payload, RESERVATION_INVALID)
    strict = _strict_object(
        data, set(V03CommittedIdentity.__dataclass_fields__), RESERVATION_INVALID
    )
    try:
        value = V03CommittedIdentity(**strict)  # type: ignore[arg-type]
    except TypeError:
        _fail(RESERVATION_INVALID)
    if value.commit_checksum != _fingerprint(_without(value, "commit_checksum")):
        _fail(RESERVATION_CHECKSUM_MISMATCH)
    stable = {
        "reservation_id": value.reservation_id,
        "run_id": value.run_id,
        "approval_id": value.approval_id,
        "request_id": value.request_id,
        "reservation_checksum": value.reservation_checksum,
    }
    if value.commit_fingerprint != _fingerprint(stable):
        _fail(RESERVATION_CHECKSUM_MISMATCH)
    return value


def commit_v03_run_identity(
    ledger_root: str | Path,
    reservation_id: str,
    run_id: str,
    *,
    approval_id: str | None = None,
    request_id: str | None = None,
    committed_at: datetime | None = None,
) -> V03CommittedIdentity:
    root = _validate_root(ledger_root)
    parse_v03_tokenization_run_id(run_id)
    for identifier in (approval_id, request_id):
        if identifier is not None and IDENTIFIER_RE.fullmatch(identifier) is None:
            _fail(RESERVATION_INVALID)
    with _ledger_lock(root):
        snapshot = load_v03_identity_ledger(root)
        reservation = next(
            (
                item
                for item in load_v03_reservations(root)
                if item.reservation_id == reservation_id
            ),
            None,
        )
        if (
            reservation is None
            or reservation.run_id != run_id
            or reservation.status != "active"
        ):
            _fail(RESERVATION_STATE_INVALID)
        path = root / "committed" / f"{run_id}.json"
        if path.exists():
            if path.is_symlink() or not path.is_file():
                _fail(RESERVATION_INVALID)
            existing = _load_committed(path)
            if (
                existing.reservation_id,
                existing.run_id,
                existing.approval_id,
                existing.request_id,
                existing.reservation_checksum,
            ) != (
                reservation_id,
                run_id,
                approval_id,
                request_id,
                reservation.reservation_checksum,
            ):
                _fail(RESERVATION_STATE_INVALID)
            return existing
        current = _latest(snapshot.entries).get(run_id)
        if current is None or current.status != "reserved":
            _fail(RESERVATION_STATE_INVALID)
        committed_text = _timestamp(committed_at)
        if _parse_timestamp(committed_text, RESERVATION_INVALID) >= _parse_timestamp(
            reservation.expires_at, RESERVATION_INVALID
        ):
            _fail(RESERVATION_EXPIRED)
        stable = {
            "reservation_id": reservation_id,
            "run_id": run_id,
            "approval_id": approval_id,
            "request_id": request_id,
            "reservation_checksum": reservation.reservation_checksum,
        }
        value = V03CommittedIdentity(
            SCHEMA_VERSION,
            reservation_id,
            run_id,
            approval_id,
            request_id,
            committed_text,
            reservation.reservation_checksum,
            _fingerprint(stable),
            "",
        )
        value = replace(
            value, commit_checksum=_fingerprint(_without(value, "commit_checksum"))
        )
        _publish_no_replace(
            path, _canonical(asdict(value)) + b"\n", RESERVATION_STATE_INVALID
        )
        entry = _transition(current, "committed", committed_text)
        try:
            _append_ledger_entry_locked(root, snapshot, entry)
        except Exception:
            if _entry_is_visible(root, entry.entry_checksum):
                _fail(LEDGER_INCONSISTENT)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                _fail(LEDGER_INCONSISTENT)
            raise
        return value


def abandon_v03_run_reservation(
    ledger_root: str | Path,
    reservation_id: str,
    *,
    reason_code: str,
    abandoned_at: datetime | None = None,
) -> V03LedgerEntry:
    if REASON_RE.fullmatch(reason_code) is None:
        _fail(RESERVATION_INVALID)
    root = _validate_root(ledger_root)
    with _ledger_lock(root):
        snapshot = load_v03_identity_ledger(root)
        reservation = next(
            (
                item
                for item in load_v03_reservations(root)
                if item.reservation_id == reservation_id
            ),
            None,
        )
        if reservation is None or reservation.status != "active":
            _fail(RESERVATION_STATE_INVALID)
        current = _latest(snapshot.entries).get(reservation.run_id)
        if current is None or current.status != "reserved":
            _fail(RESERVATION_STATE_INVALID)
        entry = _transition(
            current, "abandoned", _timestamp(abandoned_at), reason_code=reason_code
        )
        _append_ledger_entry_locked(root, snapshot, entry)
        return entry


def retire_v03_run_identity(
    ledger_root: str | Path,
    run_id: str,
    *,
    reason_code: str,
    replacement_run_id: str | None = None,
    retired_at: datetime | None = None,
) -> V03LedgerEntry:
    if REASON_RE.fullmatch(reason_code) is None:
        _fail(RESERVATION_INVALID)
    parse_v03_tokenization_run_id(run_id)
    if replacement_run_id is not None:
        parse_v03_tokenization_run_id(replacement_run_id)
        if replacement_run_id == run_id:
            _fail(PREDECESSOR_INVALID)
    root = _validate_root(ledger_root)
    with _ledger_lock(root):
        snapshot = load_v03_identity_ledger(root)
        latest = _latest(snapshot.entries)
        current = latest.get(run_id)
        if current is None or current.status not in {"reserved", "committed", "failed"}:
            _fail(RESERVATION_STATE_INVALID)
        if replacement_run_id is not None:
            replacement_entry = latest.get(replacement_run_id)
            if (
                replacement_entry is None
                or replacement_entry.predecessor_run_id != run_id
            ):
                _fail(PREDECESSOR_INVALID)
        entry = _transition(
            current,
            "retired",
            _timestamp(retired_at),
            reason_code=reason_code,
            replacement_run_id=replacement_run_id,
        )
        path = root / "retired" / f"{run_id}.json"
        _publish_no_replace(
            path, _canonical(asdict(entry)) + b"\n", RESERVATION_STATE_INVALID
        )
        try:
            _append_ledger_entry_locked(root, snapshot, entry)
        except Exception:
            if _entry_is_visible(root, entry.entry_checksum):
                _fail(LEDGER_INCONSISTENT)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                _fail(LEDGER_INCONSISTENT)
            raise
        return entry


def make_v03_historical_predecessor_entry(
    run_id: str,
    *,
    source_commit: str,
    dataset_id: str,
    dataset_fingerprint: str,
    created_at: datetime,
    status: str = "retired",
    reason_code: str = "RETIRED_UNRESOLVED_PUBLISH",
) -> V03LedgerEntry:
    parse_v03_tokenization_run_id(run_id)
    if status not in {"failed", "retired"} or REASON_RE.fullmatch(reason_code) is None:
        _fail(PREDECESSOR_INVALID)
    created = _timestamp(created_at)
    reference_hash = _fingerprint(
        {"run_id": run_id, "kind": "historical_failure_reference"}
    )
    return _make_entry(
        ledger_entry_id="entry-v1-" + secrets.token_hex(32),
        run_id=run_id,
        run_kind="predecessor_failure_reference",
        status=status,
        created_at=created,
        reserved_at=created,
        committed_at=None,
        retired_at=created if status == "retired" else None,
        predecessor_run_id=None,
        replacement_run_id=None,
        source_commit=source_commit,
        dataset_id=dataset_id,
        dataset_fingerprint=dataset_fingerprint,
        purpose="historical_failure_reference",
        reservation_id="historical-v1-" + reference_hash.removeprefix("sha256:"),
        reservation_checksum=reference_hash,
        reason_code=reason_code,
    )
