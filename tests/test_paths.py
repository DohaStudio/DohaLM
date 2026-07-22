from pathlib import Path

import pytest

from src.runtime.paths import (
    inspect_paths,
    project_paths,
    repository_root,
    resolve_repository_path,
    tracked_artifact_violations,
)


def test_repository_root_is_independent_of_cwd(tmp_path, monkeypatch):
    expected = repository_root()
    monkeypatch.chdir(tmp_path)
    assert repository_root() == expected
    assert project_paths()["configs"] == expected / "configs"


@pytest.mark.parametrize("path", ["C:\\outside", "/outside", "../outside"])
def test_absolute_or_parent_path_is_rejected(path):
    with pytest.raises(ValueError):
        resolve_repository_path(path)


def test_windows_and_posix_relative_paths_are_supported():
    root = repository_root()
    assert resolve_repository_path("data/raw") == root / "data" / "raw"
    assert resolve_repository_path("data\\raw") == root / "data" / "raw"


def test_read_only_inspection_does_not_create_directories(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    report = inspect_paths(tmp_path)
    assert report["logs"]["exists"] is False
    assert not (tmp_path / "logs").exists()


def test_large_artifact_paths_are_not_tracked():
    assert tracked_artifact_violations() == []
