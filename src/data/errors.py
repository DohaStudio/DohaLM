"""원문을 노출하지 않는 Phase 1 데이터 오류 계약."""

from __future__ import annotations

from dataclasses import asdict, dataclass


ERROR_CODES = frozenset(
    {
        "UNSUPPORTED_FORMAT",
        "FILE_NOT_FOUND",
        "FILE_READ_ERROR",
        "INVALID_ENCODING",
        "RAW_FILE_MUTATED",
        "INVALID_JSONL",
        "UNKNOWN_FIELD",
        "MISSING_REQUIRED_FIELD",
        "INVALID_FIELD_TYPE",
        "DUPLICATE_RECORD_ID",
        "EMPTY_TEXT",
        "TEXT_TOO_LONG",
        "NUL_CHARACTER",
        "UNAPPROVED_SOURCE",
        "UNAPPROVED_LICENSE",
        "PII_NOT_CLEAR",
        "DUPLICATE_RECORD",
        "INVALID_SPLIT_RATIO",
        "SPLIT_LEAKAGE",
        "ARTIFACT_WRITE_ERROR",
        "CHECKSUM_MISMATCH",
        "MANIFEST_MISMATCH",
    }
)


@dataclass(frozen=True)
class DataIssue:
    """안전한 오류·거부 정보."""

    code: str
    stage: str
    message: str
    source_path: str | None = None
    source_record_id: str | None = None
    line_number: int | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        if self.code not in ERROR_CODES:
            raise ValueError(f"정의되지 않은 데이터 오류 코드입니다: {self.code}")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DataPipelineError(RuntimeError):
    """전체 pipeline을 중단해야 하는 계약 오류."""

    def __init__(self, issue: DataIssue):
        self.issue = issue
        location = f" ({issue.source_path})" if issue.source_path else ""
        super().__init__(f"{issue.code} [{issue.stage}]{location}: {issue.message}")
