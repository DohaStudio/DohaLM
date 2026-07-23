"""Record-level validation and canonicalization."""

from __future__ import annotations

import math
import unicodedata
from datetime import datetime, timezone
from typing import Any

from .checksums import checksum_value
from .config import DataConfig
from .identifiers import generated_group_id, record_id
from .models import CanonicalRecord, RawRecord, RejectedRecord
from .normalization import normalize_text
from .readers import ALLOWED_FIELDS


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _depth(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + max((_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_depth(item) for item in value), default=0)
    return 0


def _json_safe(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_json_safe(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_safe(item) for key, item in value.items())
    return False


def _valid_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value.strip()) <= 256
        and all(unicodedata.category(char) != "Cc" for char in value)
    )


def _reject(record: RawRecord, code: str, message: str, raw_checksum: str | None = None) -> RejectedRecord:
    return RejectedRecord(
        source_path=record.source_path,
        source_record_id=record.source_record_id if isinstance(record.source_record_id, str) else None,
        record_id=None,
        stage="validation",
        reason_code=code,
        reason_message=message,
        raw_record_checksum=raw_checksum,
        created_at=utc_now(),
    )


def canonicalize(record: RawRecord, config: DataConfig) -> CanonicalRecord | RejectedRecord:
    unknown = record.provided_fields - ALLOWED_FIELDS
    if unknown:
        return _reject(record, "UNKNOWN_FIELD", f"알 수 없는 필드: {sorted(unknown)[0]}")
    missing = {"id", "text", "source"} - record.provided_fields
    if missing:
        return _reject(record, "MISSING_REQUIRED_FIELD", f"필수 필드 누락: {sorted(missing)[0]}")
    if not _valid_identifier(record.source_record_id) or not _valid_identifier(record.source_name):
        return _reject(record, "INVALID_FIELD_TYPE", "id와 source는 1~256자의 유효한 문자열이어야 합니다.")
    source_record_id = record.source_record_id.strip()
    source_name = record.source_name.strip()
    if source_name != config.dataset_id:
        return _reject(record, "UNAPPROVED_SOURCE", "source가 승인된 dataset_id와 일치하지 않습니다.")
    if not isinstance(record.text, str):
        return _reject(record, "INVALID_FIELD_TYPE", "text는 문자열이어야 합니다.")
    try:
        raw_checksum = checksum_value(
            {
                "source_record_id": source_record_id,
                "source_name": source_name,
                "group_id": record.group_id,
                "text_raw": record.text,
                "metadata": record.metadata,
            }
        )
    except (TypeError, ValueError, UnicodeError):
        return _reject(record, "INVALID_FIELD_TYPE", "record를 canonical UTF-8 JSON으로 직렬화할 수 없습니다.")
    if "\x00" in record.text:
        return _reject(record, "NUL_CHARACTER", "text에 NUL 문자가 있습니다.", raw_checksum)
    try:
        normalized = normalize_text(record.text)
    except ValueError:
        return _reject(record, "EMPTY_TEXT", "정규화 후 text가 비어 있습니다.", raw_checksum)
    if len(normalized) > config.max_text_chars:
        return _reject(record, "TEXT_TOO_LONG", "정규화 후 text 길이가 제한을 초과합니다.", raw_checksum)
    if record.group_id is not None and not isinstance(record.group_id, str):
        return _reject(record, "INVALID_FIELD_TYPE", "group_id 형식이 유효하지 않습니다.", raw_checksum)
    if isinstance(record.group_id, str) and record.group_id.strip() and not _valid_identifier(record.group_id):
        return _reject(record, "INVALID_FIELD_TYPE", "group_id 형식이 유효하지 않습니다.", raw_checksum)
    if not isinstance(record.metadata, dict) or not _json_safe(record.metadata) or _depth(record.metadata) > config.metadata_max_depth:
        return _reject(record, "INVALID_FIELD_TYPE", "metadata가 JSON object 계약을 위반합니다.", raw_checksum)
    group_id = record.group_id.strip() if isinstance(record.group_id, str) and record.group_id.strip() else generated_group_id(source_name, record.source_path)
    normalized_checksum = checksum_value({"text_normalized": normalized})
    identifier = record_id(source_name, record.source_path, source_record_id, raw_checksum)
    return CanonicalRecord(
        record_id=identifier,
        source_record_id=source_record_id,
        source_name=source_name,
        source_path=record.source_path,
        group_id=group_id,
        text_raw=record.text,
        text_normalized=normalized,
        file_checksum=record.file_checksum,
        raw_record_checksum=raw_checksum,
        normalized_record_checksum=normalized_checksum,
        metadata=record.metadata,
        license_status=config.license_status,
        approval_status=config.approval_status,
        pii_status=config.pii_status,
    )
