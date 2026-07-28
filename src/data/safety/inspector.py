"""Dataset 원문을 반환·출력·로그하지 않는 synthetic-first 검사 유틸리티."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import math
import re
import unicodedata
from typing import Any, Iterable, Mapping


_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]+$")
_TYPE_NAMES = {
    "array",
    "boolean",
    "bytes",
    "float",
    "integer",
    "null",
    "object",
    "string",
}
_FIXED_VALUES = {
    "blocked",
    "ok",
    "prohibited",
    "custom",
    "exception",
}
_MIN_LEAK_SUBSTRING = 16


def _digest(value: bytes) -> str:
    return f"sha256:{sha256(value).hexdigest()}"


def _safe_name(value: Any) -> str:
    if isinstance(value, str) and _SAFE_NAME.fullmatch(value):
        return value
    encoded = str(type(value).__name__).encode("utf-8")
    if isinstance(value, str):
        encoded = value.encode("utf-8")
    return f"key_sha256_{sha256(encoded).hexdigest()}"


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bytes):
        return "bytes"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple, set, frozenset)):
        return "array"
    return "object"


def _source_strings(value: Any, seen: set[int] | None = None) -> list[str]:
    seen = seen or set()
    if isinstance(value, str):
        return [value]
    if isinstance(value, (bytes, int, float, bool, type(None))):
        return []
    identity = id(value)
    if identity in seen:
        return []
    seen.add(identity)
    if isinstance(value, Mapping):
        result: list[str] = []
        for item in value.values():
            result.extend(_source_strings(item, seen))
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        result = []
        for item in value:
            result.extend(_source_strings(item, seen))
        return result
    try:
        attributes = vars(value)
    except Exception:
        return []
    return _source_strings(attributes, seen)


def _result_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _result_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _result_strings(item)


def _allowed_result_string(value: str) -> bool:
    if value in _TYPE_NAMES or value in _FIXED_VALUES:
        return True
    if _ERROR_CODE.fullmatch(value) or _SHA256.fullmatch(value):
        return True
    if value.startswith("$"):
        return True
    if _SAFE_NAME.fullmatch(value) or re.fullmatch(r"key_sha256_[0-9a-f]{64}", value):
        return True
    return False


def _blocked(error_code: str) -> dict[str, Any]:
    return {"status": "blocked", "error_code": error_code, "value_output": False}


def guard_safe_output(result: Any, source: Any) -> dict[str, Any] | None:
    """원문·긴 substring·비허용 문자열을 찾으면 고정 오류만 반환한다."""

    try:
        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
        for raw in _source_strings(source):
            if not raw:
                continue
            if raw in serialized:
                return _blocked("RAW_VALUE_LEAK_DETECTED")
            if len(raw) >= _MIN_LEAK_SUBSTRING:
                for offset in range(len(raw) - _MIN_LEAK_SUBSTRING + 1):
                    if raw[offset : offset + _MIN_LEAK_SUBSTRING] in serialized:
                        return _blocked("RAW_VALUE_LEAK_DETECTED")
        if any(not _allowed_result_string(item) for item in _result_strings(result)):
            return _blocked("UNSAFE_OUTPUT_STRING")
    except Exception:
        return _blocked("OUTPUT_GUARD_FAILED")
    return None


class SafeDatasetInspector:
    """Python value를 원문 없는 schema metadata로 변환한다."""

    def __init__(self, *, hash_strings: bool = False, max_depth: int = 32) -> None:
        if max_depth < 1:
            raise ValueError("INVALID_SAFE_INSPECTOR_POLICY")
        self.hash_strings = hash_strings
        self.max_depth = max_depth

    def inspect(self, value: Any, *, path: str = "$") -> dict[str, Any]:
        try:
            result = self._inspect(value, path=path, depth=0, seen=set())
            if result.get("status") == "blocked":
                return result
            guarded = guard_safe_output(result, value)
            if guarded is not None:
                return guarded
            return {"status": "ok", "result": result, "value_output": "prohibited"}
        except Exception:
            return _blocked("SAFE_INSPECTION_FAILED")

    def inspect_category(
        self,
        value: Any,
        *,
        path: str,
        canonical_values: frozenset[str],
    ) -> dict[str, Any]:
        try:
            if not isinstance(value, str):
                return {
                    "status": "blocked",
                    "error_code": "UNSUPPORTED_VALUE_TYPE",
                    "path": path,
                    "type": _type_name(value),
                    "value_output": False,
                }
            result: dict[str, Any] = {
                "status": "ok",
                "path": path,
                "type": "string",
                "length": len(value),
                "canonical_match": value in canonical_values,
                "value_output": "prohibited",
            }
            guarded = guard_safe_output(result, value)
            return guarded if guarded is not None else result
        except Exception:
            return _blocked("SAFE_INSPECTION_FAILED")

    def aggregate_strings(self, values: Iterable[Any], *, path: str) -> dict[str, Any]:
        count = 0
        total = 0
        minimum: int | None = None
        maximum: int | None = None
        empty = 0
        whitespace = 0
        try:
            for value in values:
                if not isinstance(value, str):
                    return _blocked("UNSUPPORTED_VALUE_TYPE")
                length = len(value)
                count += 1
                total += length
                minimum = length if minimum is None else min(minimum, length)
                maximum = length if maximum is None else max(maximum, length)
                empty += length == 0
                whitespace += length > 0 and value.isspace()
            return {
                "status": "ok",
                "path": path,
                "type": "string",
                "count": count,
                "minimum_length": minimum,
                "maximum_length": maximum,
                "average_length": 0.0 if count == 0 else total / count,
                "empty_count": empty,
                "whitespace_only_count": whitespace,
                "value_output": "prohibited",
            }
        except Exception:
            return _blocked("SAFE_INSPECTION_FAILED")

    def _inspect(self, value: Any, *, path: str, depth: int, seen: set[int]) -> dict[str, Any]:
        if depth > self.max_depth:
            return {"path": path, "error_code": "MAX_DEPTH_EXCEEDED", "value_output": "prohibited"}
        if value is None:
            return {"path": path, "type": "null", "null": True}
        if isinstance(value, str):
            categories = Counter(unicodedata.category(character) for character in value)
            return {
                "path": path,
                "type": "string",
                "length": len(value),
                "empty": len(value) == 0,
                "whitespace_only": len(value) > 0 and value.isspace(),
                "sha256": _digest(value.encode("utf-8")) if self.hash_strings else None,
                "unicode_category_counts": dict(sorted(categories.items())),
            }
        if isinstance(value, bytes):
            return {
                "path": path,
                "type": "bytes",
                "length": len(value),
                "sha256": _digest(value) if self.hash_strings else None,
            }
        if isinstance(value, bool):
            return {"path": path, "type": "boolean"}
        if isinstance(value, int):
            return {"path": path, "type": "integer"}
        if isinstance(value, float):
            return {
                "path": path,
                "type": "float",
                "finite": math.isfinite(value),
            }

        identity = id(value)
        if identity in seen:
            return {"path": path, "error_code": "CYCLE_DETECTED", "value_output": "prohibited"}
        seen.add(identity)
        try:
            if isinstance(value, Mapping):
                fields: dict[str, Any] = {}
                keys: list[str] = []
                for key, item in value.items():
                    safe_key = _safe_name(key)
                    keys.append(safe_key)
                    fields[safe_key] = self._inspect(
                        item,
                        path=f"{path}.{safe_key}",
                        depth=depth + 1,
                        seen=seen,
                    )
                return {
                    "path": path,
                    "type": "object",
                    "keys": sorted(keys),
                    "fields": fields,
                    "value_output": "prohibited",
                }
            if isinstance(value, (list, tuple, set, frozenset)):
                items = [
                    self._inspect(item, path=f"{path}[]", depth=depth + 1, seen=seen)
                    for item in value
                ]
                element_types = Counter(_type_name(item) for item in value)
                return {
                    "path": path,
                    "type": "array",
                    "length": len(value),
                    "element_types": dict(sorted(element_types.items())),
                    "items": items,
                    "value_output": "prohibited",
                }
            try:
                attributes = vars(value)
            except Exception:
                return _blocked("UNSUPPORTED_VALUE_TYPE")
            object_kind = "exception" if isinstance(value, BaseException) else "custom"
            return {
                "path": path,
                "type": "object",
                "object_kind": object_kind,
                "attributes": self._inspect(
                    attributes,
                    path=f"{path}.attributes",
                    depth=depth + 1,
                    seen=seen,
                ),
                "value_output": "prohibited",
            }
        finally:
            seen.discard(identity)
