"""Build or validate the immutable DohaLM v0.2 weighted tokenized package."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from src.training.v02_weighted import V02WeightedError, build_v02_tokenized_package


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def validate_git(repository: Path, expected_head: str) -> dict[str, object]:
    try:
        branch = _git(repository, "branch", "--show-current")
        head = _git(repository, "rev-parse", "HEAD")
        origin = _git(repository, "rev-parse", "origin/develop")
        status = _git(repository, "status", "--porcelain=v1")
    except (OSError, subprocess.CalledProcessError):
        raise V02WeightedError("GIT_STATE_INVALID") from None
    if branch != "develop" or head != expected_head or origin != head or status:
        raise V02WeightedError("GIT_STATE_INVALID")
    return {"branch": branch, "head": head, "origin_develop": origin, "clean": True}


def validate_paths(repository: Path, source: Path, reuse: Path, output: Path) -> None:
    values = [path.resolve() for path in (repository, source, reuse, output)]
    if not all(path.is_absolute() for path in values) or not all(path.is_dir() for path in values[:3]):
        raise V02WeightedError("PATH_INVALID")
    for protected in values[:3]:
        if output.resolve() == protected or output.resolve() in protected.parents or protected in output.resolve().parents:
            raise V02WeightedError("PATH_OVERLAP")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repository", type=Path, required=True)
    value.add_argument("--source-root", type=Path, required=True)
    value.add_argument("--reuse-root", type=Path, required=True)
    value.add_argument("--output-root", type=Path, required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--execute", action="store_true")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        git = validate_git(arguments.repository, arguments.expected_head)
        validate_paths(arguments.repository, arguments.source_root, arguments.reuse_root, arguments.output_root)
        if not arguments.execute:
            result: dict[str, object] = {"status": "validated_not_executed", "git": git, "training_started": False}
        else:
            result = {"status": "completed", "git": git, **build_v02_tokenized_package(
                source_root=arguments.source_root,
                reuse_root=arguments.reuse_root,
                output_root=arguments.output_root,
                git_head=str(git["head"]),
            )}
    except V02WeightedError as exc:
        print(json.dumps({"status": "failed_closed", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
