"""Strict UTF-8 TXT and JSONL readers."""

from __future__ import annotations

import json
from typing import Any

from .errors import DataIssue, DataPipelineError
from .identifiers import txt_source_record_id
from .models import InputSource, RawRecord
from .normalization import decode_utf8


ALLOWED_FIELDS = frozenset({"id", "text", "source", "group_id", "metadata"})


def _fail(code: str, source: InputSource, message: str, line: int | None = None) -> DataPipelineError:
    return DataPipelineError(DataIssue(code, "read", message, source.relative_path, line_number=line))


def _read_bytes(source: InputSource) -> bytes:
    try:
        return source.path.read_bytes()
    except OSError as exc:
        raise _fail("FILE_READ_ERROR", source, str(exc)) from exc


def _decode(source: InputSource) -> str:
    try:
        return decode_utf8(_read_bytes(source))
    except UnicodeDecodeError as exc:
        raise _fail("INVALID_ENCODING", source, "입력은 strict UTF-8이어야 합니다.") from exc


def _pairs_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"중복 JSON key: {key}")
        result[key] = value
    return result


def read_source(source: InputSource, dataset_id: str) -> list[RawRecord]:
    text = _decode(source)
    if source.format == "txt":
        source_id = txt_source_record_id(source.relative_path, source.file_checksum)
        return [
            RawRecord(
                source_path=source.relative_path,
                source_record_id=source_id,
                source_name=dataset_id,
                text=text,
                file_checksum=source.file_checksum,
                line_number=1,
                provided_fields=frozenset({"id", "text", "source", "metadata"}),
            )
        ]
    if source.format != "jsonl":
        raise _fail("UNSUPPORTED_FORMAT", source, "지원하지 않는 입력 형식입니다.")

    records: list[RawRecord] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise _fail("INVALID_JSONL", source, "빈 JSONL 줄은 허용되지 않습니다.", line_number)
        try:
            value = json.loads(
                line,
                object_pairs_hook=_pairs_object,
                parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"비표준 수: {token}")),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise _fail("INVALID_JSONL", source, str(exc), line_number) from exc
        if not isinstance(value, dict):
            raise _fail("INVALID_JSONL", source, "각 줄은 JSON object여야 합니다.", line_number)
        records.append(
            RawRecord(
                source_path=source.relative_path,
                source_record_id=value.get("id"),
                source_name=value.get("source"),
                text=value.get("text"),
                group_id=value.get("group_id"),
                metadata=value.get("metadata", {}),
                file_checksum=source.file_checksum,
                line_number=line_number,
                provided_fields=frozenset(value),
            )
        )
    return records
