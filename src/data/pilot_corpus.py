"""Streaming corpus contract for bounded, local-only pilot pretraining."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator


class PilotCorpusError(RuntimeError):
    """Fail closed without including corpus text in the error message."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class PilotCorpusPolicy:
    source_id: str
    license_status: str
    local_experiment_only: bool
    publish_allowed: bool = False
    redistribution_allowed: bool = False
    model_release_allowed: bool = False

    def validate(self) -> None:
        if not self.source_id.strip():
            raise PilotCorpusError("PILOT_SOURCE_REQUIRED", "source_id가 필요합니다.")
        if self.publish_allowed or self.redistribution_allowed or self.model_release_allowed:
            raise PilotCorpusError("PILOT_LOCAL_ONLY_VIOLATION", "pilot 산출물의 공개·재배포·모델 배포는 금지됩니다.")
        if self.license_status != "approved" and not self.local_experiment_only:
            raise PilotCorpusError(
                "PILOT_LICENSE_NOT_APPROVED",
                "승인되지 않은 이용조건은 local_experiment_only 모드에서만 사용할 수 있습니다.",
            )


@dataclass(frozen=True)
class PilotRecord:
    record_id: str
    text: str
    text_fingerprint: str


@dataclass(frozen=True)
class CorpusSummary:
    source_id: str
    format: str
    record_count: int
    character_count: int
    byte_count: int
    corpus_fingerprint: str
    license_status: str
    local_experiment_only: bool
    publish_allowed: bool
    redistribution_allowed: bool
    model_release_allowed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _safe_text(text: object, *, line_number: int) -> str:
    if not isinstance(text, str):
        raise PilotCorpusError("PILOT_TEXT_INVALID", f"line {line_number}의 text field는 문자열이어야 합니다.")
    if not text.strip():
        raise PilotCorpusError("PILOT_TEXT_EMPTY", f"line {line_number}에 빈 text가 있습니다.")
    if "\x00" in text:
        raise PilotCorpusError("PILOT_TEXT_NUL", f"line {line_number}에 NUL 문자가 있습니다.")
    if unicodedata.normalize("NFC", text) != text:
        raise PilotCorpusError("PILOT_TEXT_NOT_NFC", f"line {line_number}이 NFC 정규화 상태가 아닙니다.")
    return text


def iter_pilot_records(path: str | Path, *, text_field: str = "text_normalized") -> Iterator[PilotRecord]:
    source = Path(path)
    if not source.is_file():
        raise PilotCorpusError("PILOT_CORPUS_NOT_FOUND", "지정한 corpus 파일이 없습니다.")
    suffix = source.suffix.lower()
    if suffix not in {".txt", ".jsonl"}:
        raise PilotCorpusError("PILOT_CORPUS_FORMAT", "UTF-8 TXT 또는 JSONL만 지원합니다.")
    try:
        with source.open("r", encoding="utf-8", errors="strict", newline=None) as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.rstrip("\r\n")
                if not line.strip():
                    continue
                if suffix == ".jsonl":
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise PilotCorpusError("PILOT_JSONL_INVALID", f"line {line_number}이 유효한 JSON이 아닙니다.") from exc
                    if not isinstance(value, dict) or text_field not in value:
                        raise PilotCorpusError("PILOT_TEXT_FIELD_MISSING", f"line {line_number}에 지정 text field가 없습니다.")
                    forbidden = {"metadata", "source"}.intersection(value)
                    if forbidden:
                        raise PilotCorpusError("PILOT_FIELD_MIXING", f"line {line_number}에 금지된 metadata/source field가 있습니다.")
                    text = _safe_text(value[text_field], line_number=line_number)
                else:
                    text = _safe_text(line, line_number=line_number)
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                yield PilotRecord(f"sha256:{digest}", text, f"sha256:{digest}")
    except UnicodeDecodeError as exc:
        raise PilotCorpusError("PILOT_CORPUS_ENCODING", "corpus는 엄격한 UTF-8이어야 합니다.") from exc
    except OSError as exc:
        raise PilotCorpusError("PILOT_CORPUS_READ", "corpus를 읽을 수 없습니다.") from exc


def inspect_pilot_corpus(
    path: str | Path,
    *,
    policy: PilotCorpusPolicy,
    text_field: str = "text_normalized",
    minimum_records: int = 2,
) -> CorpusSummary:
    policy.validate()
    if minimum_records < 1:
        raise PilotCorpusError("PILOT_MIN_RECORDS_INVALID", "minimum_records는 1 이상이어야 합니다.")
    digest = hashlib.sha256()
    count = characters = byte_count = 0
    for record in iter_pilot_records(path, text_field=text_field):
        payload = record.text.encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        count += 1
        characters += len(record.text)
        byte_count += len(payload)
    if count < minimum_records:
        raise PilotCorpusError("PILOT_CORPUS_TOO_SMALL", "corpus record 수가 최소 요구량보다 적습니다.")
    return CorpusSummary(
        source_id=policy.source_id,
        format=Path(path).suffix.lower().lstrip("."),
        record_count=count,
        character_count=characters,
        byte_count=byte_count,
        corpus_fingerprint=f"sha256:{digest.hexdigest()}",
        license_status=policy.license_status,
        local_experiment_only=policy.local_experiment_only,
        publish_allowed=policy.publish_allowed,
        redistribution_allowed=policy.redistribution_allowed,
        model_release_allowed=policy.model_release_allowed,
    )


def stable_split(text_fingerprint: str, *, seed: int, train_percent: int = 95) -> str:
    if not 1 <= train_percent <= 99:
        raise PilotCorpusError("PILOT_SPLIT_INVALID", "train_percent는 1~99여야 합니다.")
    material = f"pilot-split-v1\0{seed}\0{text_fingerprint}".encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % 100
    return "train" if bucket < train_percent else "validation"
