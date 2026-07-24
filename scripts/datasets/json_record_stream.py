"""제한된 byte 범위에서 JSON root array의 record 경계를 탐지한다."""

from __future__ import annotations

import codecs
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable


READ_CHUNK_BYTES = 64 * 1024

RECORD_OK = "RECORD_OK"
RECORD_TOO_LARGE = "RECORD_TOO_LARGE"
RECORD_PARSE_FAILED = "RECORD_PARSE_FAILED"
RECORD_TRUNCATED = "RECORD_TRUNCATED"
ENTRY_READ_LIMIT_REACHED = "ENTRY_READ_LIMIT_REACHED"
ROOT_NOT_ARRAY = "ROOT_NOT_ARRAY"
INVALID_UTF8 = "INVALID_UTF8"
MALFORMED_JSON_STRUCTURE = "MALFORMED_JSON_STRUCTURE"


@dataclass(frozen=True)
class RecordEvent:
    """경계가 확인된 단일 record의 일시적 분석 입력."""

    record_index: int
    status: str
    byte_size: int
    checksum: str
    record_type: str | None
    value: Any | None = None


@dataclass(frozen=True)
class StreamScanResult:
    """원문을 포함하지 않는 parser 최종 상태."""

    status: str
    array_started: bool
    in_string: bool
    escape: bool
    unicode_escape_remaining: int
    object_depth: int
    array_depth: int
    record_start: bool
    bytes_read: int
    record_bytes: int
    records_seen: int
    records_parsed: int
    records_rejected: int
    truncated: bool
    parse_error: bool
    root_closed: bool


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def scan_json_array_records(
    source: Any,
    *,
    max_record_bytes: int,
    max_read_bytes: int,
    on_record: Callable[[RecordEvent], None],
) -> StreamScanResult:
    """JSON array를 bounded stream으로 읽고 record 경계를 callback으로 전달한다.

    callback의 ``value``는 호출 중에만 사용해야 하며 manifest에 그대로 저장하면 안 된다.
    """

    if max_record_bytes <= 0 or max_read_bytes <= 0:
        raise ValueError("record와 read byte 제한은 0보다 커야 합니다.")

    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    array_started = False
    root_closed = False
    expecting_item = False
    after_comma = False
    in_string = False
    escape = False
    unicode_escape_remaining = 0
    object_depth = 0
    array_depth = 0
    record_active = False
    record_buffer: list[str] = []
    record_bytes = 0
    record_hash = hashlib.sha256()
    record_oversized = False
    bytes_read = 0
    records_seen = 0
    records_parsed = 0
    records_rejected = 0
    parse_error = False
    malformed = False
    invalid_utf8 = False
    reached_eof = False
    stop_processing = False
    first_decoded_character = True

    def reset_record() -> None:
        nonlocal record_active, record_buffer, record_bytes, record_hash, record_oversized
        nonlocal in_string, escape, unicode_escape_remaining, object_depth, array_depth
        record_active = False
        record_buffer = []
        record_bytes = 0
        record_hash = hashlib.sha256()
        record_oversized = False
        in_string = False
        escape = False
        unicode_escape_remaining = 0
        object_depth = 0
        array_depth = 0

    def append_record_character(character: str) -> None:
        nonlocal record_bytes, record_oversized, record_buffer
        encoded = character.encode("utf-8")
        record_bytes += len(encoded)
        record_hash.update(encoded)
        if not record_oversized and record_bytes <= max_record_bytes:
            record_buffer.append(character)
        elif not record_oversized:
            record_oversized = True
            record_buffer = []

    def finish_record(status_override: str | None = None) -> None:
        nonlocal records_seen, records_parsed, records_rejected, parse_error
        records_seen += 1
        checksum = "sha256:" + record_hash.hexdigest()
        status = status_override
        value: Any | None = None
        record_type: str | None = None
        if status is None and record_oversized:
            status = RECORD_TOO_LARGE
        elif status is None:
            try:
                value = json.loads("".join(record_buffer))
                record_type = _value_type(value)
                status = RECORD_OK
            except json.JSONDecodeError:
                status = RECORD_PARSE_FAILED
                parse_error = True
        if status == RECORD_OK:
            records_parsed += 1
        else:
            records_rejected += 1
        on_record(RecordEvent(
            record_index=records_seen - 1,
            status=status,
            byte_size=record_bytes,
            checksum=checksum,
            record_type=record_type,
            value=value,
        ))
        reset_record()

    def process_character(character: str) -> None:
        nonlocal array_started, root_closed, expecting_item, after_comma, malformed
        nonlocal record_active, in_string, escape, unicode_escape_remaining
        nonlocal object_depth, array_depth, stop_processing, first_decoded_character, parse_error

        if first_decoded_character:
            first_decoded_character = False
            if character == "\ufeff":
                return

        if root_closed:
            if not character.isspace():
                malformed = True
                stop_processing = True
            return

        if not array_started:
            if character.isspace():
                return
            if character != "[":
                stop_processing = True
                return
            array_started = True
            expecting_item = True
            return

        if not record_active:
            if character.isspace():
                return
            if character == "]":
                if after_comma:
                    malformed = True
                root_closed = True
                stop_processing = True
                return
            if character == ",":
                malformed = True
                stop_processing = True
                return
            record_active = True
            expecting_item = False
            after_comma = False

        if in_string:
            append_record_character(character)
            if unicode_escape_remaining:
                if character not in "0123456789abcdefABCDEF":
                    parse_error = True
                unicode_escape_remaining -= 1
                return
            if escape:
                escape = False
                if character == "u":
                    unicode_escape_remaining = 4
                return
            if character == "\\":
                escape = True
            elif character == '"':
                in_string = False
            return

        if character == '"':
            append_record_character(character)
            in_string = True
            return
        if character == "{":
            append_record_character(character)
            object_depth += 1
            return
        if character == "}":
            if object_depth <= 0:
                malformed = True
                stop_processing = True
                return
            append_record_character(character)
            object_depth -= 1
            return
        if character == "[":
            append_record_character(character)
            array_depth += 1
            return
        if character == "]":
            if array_depth > 0:
                append_record_character(character)
                array_depth -= 1
                return
            if object_depth > 0:
                malformed = True
                stop_processing = True
                return
            finish_record()
            root_closed = True
            stop_processing = True
            return
        if character == "," and object_depth == 0 and array_depth == 0:
            finish_record()
            expecting_item = True
            after_comma = True
            return
        append_record_character(character)

    while bytes_read < max_read_bytes and not stop_processing:
        request = min(READ_CHUNK_BYTES, max_read_bytes - bytes_read)
        chunk = source.read(request)
        if not chunk:
            reached_eof = True
            break
        bytes_read += len(chunk)
        try:
            text = decoder.decode(chunk, final=False)
        except UnicodeDecodeError:
            invalid_utf8 = True
            break
        for character in text:
            process_character(character)
            if stop_processing:
                break

    if not invalid_utf8 and reached_eof and not stop_processing:
        try:
            tail = decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            invalid_utf8 = True
        else:
            for character in tail:
                process_character(character)
                if stop_processing:
                    break

    truncated = False
    if invalid_utf8:
        status = INVALID_UTF8
    elif not array_started:
        status = ROOT_NOT_ARRAY
    elif malformed:
        status = MALFORMED_JSON_STRUCTURE
    elif root_closed:
        status = RECORD_OK
    elif record_active:
        truncated = True
        finish_record(RECORD_TRUNCATED)
        status = ENTRY_READ_LIMIT_REACHED if not reached_eof else RECORD_TRUNCATED
    elif not reached_eof:
        truncated = True
        status = ENTRY_READ_LIMIT_REACHED
    else:
        status = MALFORMED_JSON_STRUCTURE

    return StreamScanResult(
        status=status,
        array_started=array_started,
        in_string=in_string,
        escape=escape,
        unicode_escape_remaining=unicode_escape_remaining,
        object_depth=object_depth,
        array_depth=array_depth,
        record_start=record_active,
        bytes_read=bytes_read,
        record_bytes=record_bytes,
        records_seen=records_seen,
        records_parsed=records_parsed,
        records_rejected=records_rejected,
        truncated=truncated,
        parse_error=parse_error,
        root_closed=root_closed,
    )
