"""Tokenizer artifact의 경로·시각 독립 SHA-256 fingerprint."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


FINGERPRINT_SCHEMA_VERSION = "1.0"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def build_fingerprint(
    model_path: str | Path,
    trainer_config: Mapping[str, Any],
    special_tokens: Mapping[str, int],
    sentencepiece_version: str,
) -> dict[str, Any]:
    payload = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "model_checksum": sha256_file(model_path),
        "trainer_config": dict(trainer_config),
        "special_tokens": dict(special_tokens),
        "sentencepiece_version": sentencepiece_version,
    }
    fingerprint = f"sha256:{hashlib.sha256(canonical_json(payload)).hexdigest()}"
    return {**payload, "fingerprint": fingerprint}
