"""Repository-confined and deterministic input discovery."""

from __future__ import annotations

from pathlib import Path

from src.runtime.paths import repository_root

from .checksums import file_checksum
from .config import DataConfig
from .errors import DataIssue, DataPipelineError
from .models import InputSource


def _issue(code: str, message: str, path: Path | None = None) -> DataPipelineError:
    return DataPipelineError(DataIssue(code, "discovery", message, str(path) if path else None))


def _is_hidden_or_temporary(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts) or path.name.startswith("~") or path.suffix.lower() in {
        ".tmp", ".temp", ".swp", ".bak"
    }


def discover_inputs(config: DataConfig, root: Path | None = None) -> list[InputSource]:
    repo = (root or repository_root()).resolve()
    output = (repo / config.output_dir / config.dataset_id / config.dataset_version).resolve()
    if output == repo or repo not in output.parents:
        raise _issue("FILE_READ_ERROR", "출력 경로는 저장소 내부여야 합니다.", output)

    files: dict[Path, Path] = {}
    for raw_path in config.input_paths:
        candidate = repo / raw_path.replace("\\", "/")
        if not candidate.exists():
            raise _issue("FILE_NOT_FOUND", "입력 경로가 존재하지 않습니다.", candidate)
        resolved = candidate.resolve()
        if resolved != repo and repo not in resolved.parents:
            raise _issue("FILE_READ_ERROR", "입력 경로가 저장소 밖을 가리킵니다.", candidate)
        if resolved == output or resolved in output.parents or output in resolved.parents:
            raise _issue("FILE_READ_ERROR", "입력과 출력 경로가 겹칩니다.", candidate)
        candidates = [resolved] if resolved.is_file() else sorted(resolved.rglob("*"), key=lambda p: p.as_posix())
        for found in candidates:
            if not found.is_file() or _is_hidden_or_temporary(found.relative_to(repo)):
                continue
            real = found.resolve()
            if real != repo and repo not in real.parents:
                raise _issue("FILE_READ_ERROR", "symlink가 저장소 밖을 가리킵니다.", found)
            if real in files:
                raise _issue("FILE_READ_ERROR", "동일한 입력 파일이 중복 지정됐습니다.", found)
            if found.suffix.lower() not in config.allowed_formats:
                raise _issue("UNSUPPORTED_FORMAT", "지원하지 않는 입력 확장자입니다.", found)
            files[real] = found
    if not files:
        raise _issue("FILE_NOT_FOUND", "처리할 입력 파일이 없습니다.")
    result = []
    for real, original in sorted(files.items(), key=lambda item: item[0].relative_to(repo).as_posix()):
        relative = real.relative_to(repo).as_posix()
        result.append(InputSource(real, relative, real.suffix.lower()[1:], real.stat().st_size, file_checksum(real)))
    return result
