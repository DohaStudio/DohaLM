"""Private, sanitized Git source-state inspection for training gates."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from src.runtime.paths import repository_root


_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


class _SourceStateInspectionError(RuntimeError):
    """Internal marker whose message never contains Git output or paths."""


@dataclass(frozen=True)
class _SourceState:
    commit: str
    branch: str
    clean: bool


def _fixed_git_value(arguments: tuple[str, ...]) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository_root(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
        )
    except OSError as exc:
        raise _SourceStateInspectionError("Git source state is unavailable.") from exc
    if result.returncode != 0:
        raise _SourceStateInspectionError("Git source state is unavailable.")
    return result.stdout.strip()


def _inspect_source_state() -> _SourceState:
    commit = _fixed_git_value(("rev-parse", "HEAD"))
    branch = _fixed_git_value(("branch", "--show-current"))
    status = _fixed_git_value(("status", "--porcelain", "--untracked-files=normal"))
    if _COMMIT_PATTERN.fullmatch(commit) is None:
        raise _SourceStateInspectionError("Git source state is unavailable.")
    return _SourceState(commit=commit, branch=branch, clean=status == "")


__all__: list[str] = []
