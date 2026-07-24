"""Synthetic-contract adapter for AIHUB-71748 records."""

from __future__ import annotations

import unicodedata
from typing import Any

from src.data.checksums import checksum_value, sha256_bytes
from src.data.normalization import normalize_text

from .contracts import AdapterOutcome, AdapterPolicy


DATASET_ID = "AIHUB-71748"
ADAPTER_VERSION = "1.0.0"
ADAPTER_SCHEMA_VERSION = "1.0"
ALLOWED_VISIBLE_KEYS = frozenset({"text", "metadata", "source"})
PII_LIKE_FIELD_TOKENS = ("address", "email", "name", "phone", "resident", "rrn", "주소", "이름", "전화")


def _hash_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def _json_type(value: Any) -> str:
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
    return "unsupported"


def _safe_source_hash(value: Any) -> str:
    try:
        return checksum_value(value)
    except (TypeError, ValueError, UnicodeEncodeError):
        descriptor = {"python_type": type(value).__name__}
        return checksum_value(descriptor)


def _schema_node(value: Any, *, depth: int = 0, key: str | None = None) -> dict[str, Any]:
    if depth > 32:
        raise ValueError("schema nesting exceeds the supported depth")
    value_type = _json_type(value)
    if value_type == "unsupported":
        raise ValueError("schema contains a non-JSON value")
    node: dict[str, Any] = {"type": value_type}
    if key is not None:
        if key in ALLOWED_VISIBLE_KEYS:
            node["key"] = key
        else:
            node["key_hash"] = _hash_text(key)
    if isinstance(value, dict):
        node["fields"] = [
            _schema_node(value[item], depth=depth + 1, key=item)
            for item in sorted(value)
        ]
    elif isinstance(value, list):
        variants = {_schema_signature_value(item, depth=depth + 1) for item in value}
        node["item_schema_hashes"] = sorted(variants)
    return node


def _schema_signature_value(value: Any, *, depth: int) -> str:
    return checksum_value(_schema_node(value, depth=depth))


def _schema_warnings(record: dict[str, Any]) -> list[str]:
    warnings: set[str] = set()
    for key in record:
        if key not in ALLOWED_VISIBLE_KEYS:
            warnings.add("UNKNOWN_FIELD_IGNORED")
            folded = unicodedata.normalize("NFC", key).casefold()
            if any(token in folded for token in PII_LIKE_FIELD_TOKENS):
                warnings.add("PII_LIKE_FIELD_NAME")
    return sorted(warnings)


class AIHub71748Adapter:
    """Transform the observed minimum schema using synthetic records only."""

    dataset_id = DATASET_ID
    name = "aihub_71748_corpus_adapter"
    version = ADAPTER_VERSION
    license_status = "pending_terms_review"
    approval_status = "pending"
    pii_status = "review_required"
    usage_status = "blocked_pending_approval"
    usage_block_reasons = (
        "LICENSE_NOT_APPROVED",
        "APPROVAL_NOT_APPROVED",
        "PII_REVIEW_REQUIRED",
    )
    normalization_policy = {
        "encoding": "UTF-8",
        "unicode_normalization": "NFC",
        "newline": "LF",
        "line_trailing_whitespace": "removed",
        "consecutive_spaces": "preserved",
        "nfkc": False,
        "normalization_version": "phase1-v1",
    }

    def __init__(self, policy: AdapterPolicy | None = None):
        self.policy = policy or AdapterPolicy()

    def adapt_record(self, source: Any) -> AdapterOutcome:
        source_hash = _safe_source_hash(source)
        if not isinstance(source, dict):
            return self._reject(source_hash, "ROOT_NOT_OBJECT", "schema_validation")
        try:
            schema = _schema_node(source)
            schema_signature = checksum_value({
                "adapter_schema_version": ADAPTER_SCHEMA_VERSION,
                "schema": schema,
            })
        except (TypeError, ValueError, UnicodeEncodeError):
            return self._reject(source_hash, "UNSUPPORTED_SCHEMA", "schema_validation")

        if "text" not in source:
            return self._reject(source_hash, "TEXT_FIELD_MISSING", "text_validation", schema_signature)
        text = source["text"]
        if not isinstance(text, str):
            return self._reject(source_hash, "TEXT_NOT_STRING", "text_validation", schema_signature)
        if text == "":
            return self._reject(source_hash, "TEXT_EMPTY", "text_validation", schema_signature)
        if text.isspace():
            return self._reject(source_hash, "TEXT_WHITESPACE_ONLY", "text_validation", schema_signature)
        if "\x00" in text:
            return self._reject(source_hash, "TEXT_CONTAINS_NUL", "text_validation", schema_signature)
        try:
            text.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            return self._reject(source_hash, "INVALID_UNICODE", "text_validation", schema_signature)
        if len(text) > self.policy.maximum_text_characters:
            return self._reject(source_hash, "TEXT_TOO_LONG", "length_validation", schema_signature)
        if len(text) < self.policy.minimum_text_characters:
            return self._reject(source_hash, "TEXT_TOO_SHORT", "length_validation", schema_signature)

        try:
            normalized = normalize_text(text)
        except ValueError:
            return self._reject(source_hash, "TEXT_WHITESPACE_ONLY", "normalization", schema_signature)
        if len(normalized) > self.policy.maximum_text_characters:
            return self._reject(source_hash, "TEXT_TOO_LONG", "length_validation", schema_signature)
        if len(normalized) < self.policy.minimum_text_characters:
            return self._reject(source_hash, "TEXT_TOO_SHORT", "length_validation", schema_signature)

        text_original_hash = _hash_text(text)
        normalized_text_hash = _hash_text(normalized)
        record_id = checksum_value({
            "adapter_version": self.version,
            "dataset_id": self.dataset_id,
            "normalized_text_hash": normalized_text_hash,
            "schema_signature": schema_signature,
            "source_record_hash": source_hash,
        })
        output = {
            "record_id": record_id,
            "dataset_id": self.dataset_id,
            "source_record_hash": source_hash,
            "text_original_hash": text_original_hash,
            "text_normalized": normalized,
            "normalization_applied": normalized != text,
            "text_character_count": len(normalized),
            "text_byte_count": len(normalized.encode("utf-8")),
            "schema_signature": schema_signature,
            "schema_warnings": _schema_warnings(source),
            "adapter_status": "adapted",
            "usage_status": self.usage_status,
            "usage_block_reasons": list(self.usage_block_reasons),
            "license_status": self.license_status,
            "approval_status": self.approval_status,
            "pii_status": self.pii_status,
            "split_eligibility": "blocked_pending_approval",
            "lineage": {
                "source_record_hash": source_hash,
                "adapter_version": self.version,
                "normalization_version": self.normalization_policy["normalization_version"],
                "schema_signature": schema_signature,
                "output_record_hash": None,
            },
        }
        hashable = {**output, "lineage": {**output["lineage"], "output_record_hash": None}}
        output["lineage"]["output_record_hash"] = checksum_value(hashable)
        return AdapterOutcome(accepted=output)

    @staticmethod
    def _reject(
        source_hash: str,
        reason_code: str,
        stage: str,
        schema_signature: str | None = None,
    ) -> AdapterOutcome:
        return AdapterOutcome(rejected={
            "adapter_status": "rejected",
            "source_record_hash": source_hash,
            "schema_signature": schema_signature,
            "reason_code": reason_code,
            "rejection_stage": stage,
            "source_value_stored": False,
        })
