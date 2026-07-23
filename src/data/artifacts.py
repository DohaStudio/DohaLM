"""Deterministic artifact serialization and atomic publication."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .checksums import artifact_checksum, canonical_json_bytes
from .errors import DataIssue, DataPipelineError


def write_json(path: Path, value: Any) -> None:
    try:
        path.write_bytes(canonical_json_bytes(value))
    except OSError as exc:
        raise DataPipelineError(DataIssue("ARTIFACT_WRITE_ERROR", "artifact_write", f"산출물을 쓸 수 없습니다: {path.name}")) from exc


def write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    try:
        with path.open("wb") as handle:
            for value in values:
                handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise DataPipelineError(DataIssue("ARTIFACT_WRITE_ERROR", "artifact_write", f"산출물을 쓸 수 없습니다: {path.name}")) from exc


def write_yaml(path: Path, value: Any) -> None:
    rendered = yaml.safe_dump(value, allow_unicode=True, sort_keys=True, default_flow_style=False)
    try:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise DataPipelineError(DataIssue("ARTIFACT_WRITE_ERROR", "artifact_write", f"산출물을 쓸 수 없습니다: {path.name}")) from exc


def count_jsonl(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return sum(1 for _ in handle)


def artifact_entry(path: Path, artifact_type: str, record_count: int) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "relative_path": path.name,
        "checksum": artifact_checksum(path),
        "record_count": record_count,
    }


class AtomicArtifactDirectory:
    def __init__(self, final_path: Path):
        self.final_path = final_path
        self.staging_path: Path | None = None

    def __enter__(self) -> Path:
        if self.final_path.exists():
            raise DataPipelineError(DataIssue("ARTIFACT_WRITE_ERROR", "artifact_write", "최종 출력 경로가 이미 존재합니다."))
        try:
            self.final_path.parent.mkdir(parents=True, exist_ok=True)
            staging = tempfile.mkdtemp(prefix=f".{self.final_path.name}.staging-", dir=self.final_path.parent)
        except OSError as exc:
            raise DataPipelineError(DataIssue("ARTIFACT_WRITE_ERROR", "artifact_write", "staging 디렉터리를 만들 수 없습니다.")) from exc
        self.staging_path = Path(staging).resolve()
        if self.staging_path.parent != self.final_path.parent.resolve():
            raise DataPipelineError(DataIssue("ARTIFACT_WRITE_ERROR", "artifact_write", "안전하지 않은 staging 경로입니다."))
        return self.staging_path

    def publish(self) -> None:
        if self.staging_path is None:
            raise RuntimeError("staging 디렉터리가 준비되지 않았습니다.")
        try:
            os.replace(self.staging_path, self.final_path)
        except OSError as exc:
            raise DataPipelineError(DataIssue("ARTIFACT_WRITE_ERROR", "artifact_write", "최종 산출물을 게시할 수 없습니다.")) from exc
        self.staging_path = None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.staging_path is not None and self.staging_path.exists():
            if self.staging_path.parent == self.final_path.parent.resolve():
                shutil.rmtree(self.staging_path)
