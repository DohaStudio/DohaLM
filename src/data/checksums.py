"""SHA-256과 결정론적 JSON 직렬화."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any


def _reject_nonfinite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("NaN과 Infinity는 허용되지 않습니다.")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object key는 문자열이어야 합니다.")
            _reject_nonfinite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_nonfinite(item)


def canonical_json_bytes(value: Any) -> bytes:
    """결정론적 JSON bytes를 반환한다. 끝에는 LF 하나를 둔다."""

    _reject_nonfinite(value)
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (rendered + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def checksum_value(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def artifact_checksum(path: Path) -> str:
    return file_checksum(path)
