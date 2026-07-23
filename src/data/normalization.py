"""Phase 1 고정 순서 텍스트 정규화."""

from __future__ import annotations

import unicodedata


def decode_utf8(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="strict")
    if text.startswith("\ufeff"):
        text = text[1:]
    return text


def normalize_text(text: str) -> str:
    if "\x00" in text:
        raise ValueError("NUL 문자는 허용되지 않습니다.")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = unicodedata.normalize("NFC", normalized)
    normalized = "\n".join(line.rstrip(" \t\v\f") for line in normalized.split("\n"))
    if normalized.endswith("\n"):
        normalized = normalized.rstrip("\n") + "\n"
    if not normalized.strip():
        raise ValueError("정규화 후 text가 비어 있습니다.")
    return normalized
