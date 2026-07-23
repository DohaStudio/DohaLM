"""Phase 1 데이터 pipeline 내부 데이터 모델."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InputSource:
    path: Path
    relative_path: str
    format: str
    size_bytes: int
    file_checksum: str


@dataclass(frozen=True)
class RawRecord:
    source_path: str
    source_record_id: str | None
    source_name: str | None
    text: Any
    group_id: Any = None
    metadata: Any = field(default_factory=dict)
    file_checksum: str = ""
    line_number: int | None = None
    provided_fields: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class CanonicalRecord:
    record_id: str
    source_record_id: str
    source_name: str
    source_path: str
    group_id: str
    text_raw: str
    text_normalized: str
    file_checksum: str
    raw_record_checksum: str
    normalized_record_checksum: str
    metadata: dict[str, Any]
    license_status: str
    approval_status: str
    pii_status: str
    processing_status: str = "accepted"
    rejection_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RejectedRecord:
    source_path: str
    source_record_id: str | None
    record_id: str | None
    stage: str
    reason_code: str
    reason_message: str
    raw_record_checksum: str | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DuplicateRecord:
    duplicate_type: str
    duplicate_record_id: str
    canonical_record_id: str
    checksum: str
    source_path: str
    source_record_id: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class SplitAssignment:
    record_id: str
    split: str
    group_id: str


@dataclass(frozen=True)
class SourceManifest:
    value: dict[str, Any]


@dataclass(frozen=True)
class DatasetStatistics:
    value: dict[str, Any]


@dataclass(frozen=True)
class DatasetLineage:
    value: dict[str, Any]


@dataclass(frozen=True)
class PipelineResult:
    output_dir: Path | None
    dataset_fingerprint: str
    source_count: int
    record_count: int
    accepted_count: int
    rejected_count: int
    duplicate_count: int
    split_counts: dict[str, int]
    artifact_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["output_dir"] = str(self.output_dir) if self.output_dir is not None else None
        value["artifact_paths"] = list(self.artifact_paths)
        return value
