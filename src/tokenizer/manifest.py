"""Tokenizer smoke manifest 생성·호환성 비교."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .errors import TokenizerError
from .fingerprint import build_fingerprint, sha256_file


MANIFEST_SCHEMA_VERSION = "1.0"


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def build_manifest(
    *,
    requested_vocab_size: int,
    actual_piece_count: int,
    trainer_config: Mapping[str, Any],
    special_tokens: Mapping[str, int],
    sentencepiece_version: str,
    corpus_fingerprint: str,
    corpus_record_count: int,
    corpus_character_count: int,
    corpus_byte_count: int,
    model_path: str | Path,
    vocab_path: str | Path,
    tokenizer_fingerprint: str,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "artifact_kind": "synthetic_tokenizer_smoke",
        "status": "smoke_only_not_approved",
        "created_at": (created_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
        "model_type": "unigram",
        "vocab_size": requested_vocab_size,
        "actual_piece_count": actual_piece_count,
        "trainer_config": dict(trainer_config),
        "special_tokens": dict(special_tokens),
        "sentencepiece_version": sentencepiece_version,
        "corpus": {
            "kind": "synthetic_fixture",
            "fingerprint": corpus_fingerprint,
            "record_count": corpus_record_count,
            "character_count": corpus_character_count,
            "byte_count": corpus_byte_count,
        },
        "model_checksum": sha256_file(model_path),
        "vocab_checksum": sha256_file(vocab_path),
        "tokenizer_fingerprint": tokenizer_fingerprint,
        "approval_effect": "none",
        "gate3_effect": "none",
    }


def load_manifest(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenizerError("TOKENIZER_MANIFEST_ERROR", "manifest를 읽을 수 없습니다.") from exc
    if not isinstance(value, dict) or value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise TokenizerError("TOKENIZER_MANIFEST_ERROR", "지원하지 않는 manifest입니다.")
    return value


def compare_manifests(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    if first.get("tokenizer_fingerprint") == second.get("tokenizer_fingerprint"):
        return {"status": "compatible", "reasons": []}
    breaking_fields = (
        "model_type",
        "actual_piece_count",
        "special_tokens",
    )
    reasons = [field for field in breaking_fields if first.get(field) != second.get(field)]
    first_config = first.get("trainer_config", {})
    second_config = second.get("trainer_config", {})
    for field in ("normalization_rule_name", "byte_fallback"):
        if isinstance(first_config, dict) and isinstance(second_config, dict) and first_config.get(field) != second_config.get(field):
            reasons.append(f"trainer_config.{field}")
    if reasons:
        return {"status": "incompatible", "reasons": reasons}
    return {"status": "warning", "reasons": ["fingerprint_changed"]}


def validate_bundle(model_path: str | Path) -> dict[str, Any]:
    model = Path(model_path).resolve()
    root = model.parent
    required = {
        "tokenizer.model",
        "tokenizer.vocab",
        "manifest.json",
        "fingerprint.json",
        "statistics.json",
    }
    missing = sorted(name for name in required if not (root / name).is_file())
    if model.name != "tokenizer.model" or missing:
        raise TokenizerError("TOKENIZER_ARTIFACT_ERROR", "필수 smoke artifact가 누락됐습니다.")
    manifest = load_manifest(root / "manifest.json")
    try:
        fingerprint_document = json.loads((root / "fingerprint.json").read_text(encoding="utf-8"))
        statistics = json.loads((root / "statistics.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TokenizerError("TOKENIZER_ARTIFACT_ERROR", "JSON artifact를 읽을 수 없습니다.") from exc
    if not isinstance(fingerprint_document, dict) or not isinstance(statistics, dict):
        raise TokenizerError("TOKENIZER_ARTIFACT_ERROR", "JSON artifact 형식이 올바르지 않습니다.")
    if manifest.get("model_checksum") != sha256_file(model):
        raise TokenizerError("TOKENIZER_CHECKSUM_MISMATCH", "tokenizer.model checksum이 일치하지 않습니다.")
    if manifest.get("vocab_checksum") != sha256_file(root / "tokenizer.vocab"):
        raise TokenizerError("TOKENIZER_CHECKSUM_MISMATCH", "tokenizer.vocab checksum이 일치하지 않습니다.")
    expected = build_fingerprint(
        model,
        manifest.get("trainer_config", {}),
        manifest.get("special_tokens", {}),
        str(manifest.get("sentencepiece_version")),
    )
    if expected != fingerprint_document or manifest.get("tokenizer_fingerprint") != expected["fingerprint"]:
        raise TokenizerError("TOKENIZER_FINGERPRINT_MISMATCH", "tokenizer fingerprint가 일치하지 않습니다.")
    from .tokenizer import DohaTokenizer

    tokenizer = DohaTokenizer(model)
    if tokenizer.vocab_size != manifest.get("actual_piece_count"):
        raise TokenizerError("TOKENIZER_VOCAB_SIZE_MISMATCH", "manifest piece 수가 model과 다릅니다.")
    return {
        "success": True,
        "status": "valid_smoke_bundle",
        "actual_piece_count": tokenizer.vocab_size,
        "fingerprint": expected["fingerprint"],
        "artifact_count": len(required),
        "approval_effect": "none",
        "gate3_effect": "none",
    }
