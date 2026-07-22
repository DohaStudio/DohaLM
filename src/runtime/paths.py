"""현재 작업 디렉터리와 무관한 저장소 경로 정책."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath


def repository_root(start: str | Path | None = None) -> Path:
    candidates = [Path(start).resolve()] if start is not None else []
    candidates.append(Path(__file__).resolve())
    for candidate in candidates:
        current = candidate if candidate.is_dir() else candidate.parent
        for parent in (current, *current.parents):
            if (parent / "pyproject.toml").is_file() and (parent / ".git").exists():
                return parent
    raise RuntimeError("pyproject.toml과 .git을 포함한 저장소 루트를 찾지 못했습니다.")


def resolve_repository_path(relative_path: str | Path, root: str | Path | None = None) -> Path:
    raw = str(relative_path)
    if PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute():
        raise ValueError(f"저장소 상대 경로만 허용됩니다: {relative_path}")
    parts = PureWindowsPath(raw.replace("/", "\\")).parts
    if ".." in parts:
        raise ValueError(f"저장소 밖으로 나가는 경로는 허용되지 않습니다: {relative_path}")
    base = repository_root(root)
    candidate = (base / Path(raw)).resolve()
    if candidate != base and base not in candidate.parents:
        raise ValueError(f"저장소 밖으로 나가는 경로는 허용되지 않습니다: {relative_path}")
    return candidate


def project_paths(root: str | Path | None = None) -> dict[str, Path]:
    base = repository_root(root)
    relative_paths = {
        "repository": ".",
        "configs": "configs",
        "data_raw": "data/raw",
        "data_cleaned": "data/cleaned",
        "data_tokenized": "data/tokenized",
        "data_sft": "data/sft",
        "checkpoints": "checkpoints",
        "logs": "logs",
        "artifacts": "artifacts",
        "experiments": "experiments",
        "tests": "tests",
    }
    return {name: (base / relative).resolve() for name, relative in relative_paths.items()}


def inspect_paths(root: str | Path | None = None) -> dict[str, dict[str, object]]:
    return {
        name: {"path": str(path), "exists": path.exists(), "is_directory": path.is_dir()}
        for name, path in project_paths(root).items()
    }


def tracked_artifact_violations(root: str | Path | None = None) -> list[str]:
    base = repository_root(root)
    result = subprocess.run(
        ["git", "ls-files", "--", "data", "checkpoints", "logs", "artifacts", "experiments"],
        cwd=base,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Git 추적 파일을 확인하지 못했습니다: {result.stderr.strip()}")
    allowed = {
        "data/raw/.gitkeep",
        "data/cleaned/.gitkeep",
        "data/tokenized/.gitkeep",
        "data/sft/.gitkeep",
        "checkpoints/.gitkeep",
    }
    tracked = [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]
    return sorted(set(tracked) - allowed)
