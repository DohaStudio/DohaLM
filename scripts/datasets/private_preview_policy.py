"""비공개 최소 record preview의 사용자 승인 정책을 검증한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from src.config.loader import load_yaml

from .safe_sampler import SamplerError, _canonical_fingerprint


PREVIEW_POLICY_SCHEMA_VERSION = "1.0"
PREVIEW_PURPOSE = "manual_pii_and_quality_review"
PREVIEW_OUTPUT_ROOT_TOKEN = "external_private_review_root"
ALLOWED_PREVIEW_FIELDS = frozenset({"text"})
MAX_PREVIEW_RECORDS = 10
MAX_CHARACTERS_PER_RECORD = 500
MAX_RETENTION_DAYS = 7


@dataclass(frozen=True)
class PreviewApproval:
    status: str
    approved_by: str | None
    approved_at: str | None
    expires_at: str | None


@dataclass(frozen=True)
class PreviewScope:
    purpose: str
    max_records: int
    allowed_fields: tuple[str, ...]
    max_characters_per_record: int
    retention_days: int
    allow_unredacted: bool


@dataclass(frozen=True)
class PrivatePreviewPolicy:
    dataset_id: str
    approval: PreviewApproval
    scope: PreviewScope
    reviewer: str | None
    output_root: str
    fingerprint: str


def _timestamp(value: Any, field: str, *, allow_null: bool) -> str | None:
    if value is None and allow_null:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise SamplerError(f"{field}은 timezone을 포함한 ISO-8601 시각이어야 합니다.") from exc
    else:
        raise SamplerError(f"{field}은 비어 있지 않은 ISO-8601 시각이어야 합니다.")
    if parsed.tzinfo is None:
        raise SamplerError(f"{field}에는 timezone이 필요합니다.")
    return parsed.astimezone(UTC).isoformat()


def _positive_bounded_int(value: Any, field: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise SamplerError(f"{field}은 1 이상 {maximum} 이하 정수여야 합니다.")
    return value


def load_private_preview_policy(
    path: str | Path,
    expected_dataset_id: str,
    *,
    require_approved: bool,
    now: datetime | None = None,
) -> PrivatePreviewPolicy:
    raw = load_yaml(path)
    if set(raw) != {"schema_version", "dataset_id", "approval", "scope", "review"}:
        raise SamplerError("preview 정책 최상위 key가 계약과 일치하지 않습니다.")
    if raw["schema_version"] != PREVIEW_POLICY_SCHEMA_VERSION:
        raise SamplerError("지원하지 않는 preview 정책 schema_version입니다.")
    if raw["dataset_id"] != expected_dataset_id:
        raise SamplerError("preview 정책 dataset_id가 CLI dataset과 일치하지 않습니다.")

    approval_raw = raw["approval"]
    if not isinstance(approval_raw, dict) or set(approval_raw) != {
        "status", "approved_by", "approved_at", "expires_at",
    }:
        raise SamplerError("preview approval key가 계약과 일치하지 않습니다.")
    status = approval_raw["status"]
    if status not in {"pending_user_review", "approved"}:
        raise SamplerError("preview approval.status는 pending_user_review 또는 approved여야 합니다.")
    approved_by = approval_raw["approved_by"]
    if approved_by is not None and (not isinstance(approved_by, str) or not approved_by.strip()):
        raise SamplerError("approved_by는 null 또는 비어 있지 않은 문자열이어야 합니다.")
    approved_at = _timestamp(approval_raw["approved_at"], "approved_at", allow_null=status != "approved")
    expires_at = _timestamp(approval_raw["expires_at"], "expires_at", allow_null=status != "approved")
    if status == "approved" and (not isinstance(approved_by, str) or not approved_by.strip()):
        raise SamplerError("approved 정책에는 approved_by가 필요합니다.")

    scope_raw = raw["scope"]
    if not isinstance(scope_raw, dict) or set(scope_raw) != {
        "purpose", "max_records", "allowed_fields", "max_characters_per_record",
        "retention_days", "allow_unredacted",
    }:
        raise SamplerError("preview scope key가 계약과 일치하지 않습니다.")
    if scope_raw["purpose"] != PREVIEW_PURPOSE:
        raise SamplerError("preview purpose가 수동 PII·품질 검토 계약과 일치하지 않습니다.")
    max_records = _positive_bounded_int(scope_raw["max_records"], "max_records", MAX_PREVIEW_RECORDS)
    max_characters = _positive_bounded_int(
        scope_raw["max_characters_per_record"],
        "max_characters_per_record",
        MAX_CHARACTERS_PER_RECORD,
    )
    retention_days = _positive_bounded_int(scope_raw["retention_days"], "retention_days", MAX_RETENTION_DAYS)
    fields_raw = scope_raw["allowed_fields"]
    if not isinstance(fields_raw, list) or not fields_raw or any(
        not isinstance(field, str) or field not in ALLOWED_PREVIEW_FIELDS for field in fields_raw
    ):
        raise SamplerError("preview allowed_fields에는 정책상 허용된 text만 사용할 수 있습니다.")
    if len(set(fields_raw)) != len(fields_raw):
        raise SamplerError("preview allowed_fields는 중복될 수 없습니다.")
    if scope_raw["allow_unredacted"] is not False:
        raise SamplerError("비식별 처리되지 않은 preview는 허용하지 않습니다.")

    review_raw = raw["review"]
    if not isinstance(review_raw, dict) or set(review_raw) != {"reviewer", "output_root"}:
        raise SamplerError("preview review key가 계약과 일치하지 않습니다.")
    reviewer = review_raw["reviewer"]
    if reviewer is not None and (not isinstance(reviewer, str) or not reviewer.strip()):
        raise SamplerError("reviewer는 null 또는 비어 있지 않은 문자열이어야 합니다.")
    if review_raw["output_root"] != PREVIEW_OUTPUT_ROOT_TOKEN:
        raise SamplerError("preview output_root는 외부 private review root token이어야 합니다.")

    current = (now or datetime.now(UTC)).astimezone(UTC)
    if require_approved:
        if status != "approved":
            raise SamplerError("사용자가 approved로 승인한 preview 정책만 실제 preview를 생성할 수 있습니다.")
        if reviewer is None:
            raise SamplerError("실제 preview 생성에는 reviewer가 필요합니다.")
        assert expires_at is not None
        if current >= datetime.fromisoformat(expires_at):
            raise SamplerError("preview 승인이 만료됐습니다.")

    canonical = {
        "schema_version": PREVIEW_POLICY_SCHEMA_VERSION,
        "dataset_id": expected_dataset_id,
        "approval": {
            "status": status,
            "approved_by": approved_by.strip() if isinstance(approved_by, str) else None,
            "approved_at": approved_at,
            "expires_at": expires_at,
        },
        "scope": {
            "purpose": PREVIEW_PURPOSE,
            "max_records": max_records,
            "allowed_fields": sorted(fields_raw),
            "max_characters_per_record": max_characters,
            "retention_days": retention_days,
            "allow_unredacted": False,
        },
        "review": {
            "reviewer": reviewer.strip() if isinstance(reviewer, str) else None,
            "output_root": PREVIEW_OUTPUT_ROOT_TOKEN,
        },
    }
    return PrivatePreviewPolicy(
        dataset_id=expected_dataset_id,
        approval=PreviewApproval(
            status=status,
            approved_by=canonical["approval"]["approved_by"],
            approved_at=approved_at,
            expires_at=expires_at,
        ),
        scope=PreviewScope(
            purpose=PREVIEW_PURPOSE,
            max_records=max_records,
            allowed_fields=tuple(sorted(fields_raw)),
            max_characters_per_record=max_characters,
            retention_days=retention_days,
            allow_unredacted=False,
        ),
        reviewer=canonical["review"]["reviewer"],
        output_root=PREVIEW_OUTPUT_ROOT_TOKEN,
        fingerprint=_canonical_fingerprint(canonical),
    )
