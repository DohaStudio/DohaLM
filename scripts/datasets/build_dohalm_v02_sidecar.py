"""Build the immutable DohaLM v0.2 quality-sidecar Dataset package."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from src.data.v02_sidecar import (
    V02SidecarError,
    build_v02_sidecar_package,
    load_policy,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--tokenized-root", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--execute", action="store_true")
    return parser


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def validate_git(repository: Path, expected_head: str) -> dict[str, object]:
    try:
        branch = _git(repository, "branch", "--show-current")
        head = _git(repository, "rev-parse", "HEAD")
        origin = _git(repository, "rev-parse", "origin/develop")
        status = _git(repository, "status", "--porcelain=v1")
    except (OSError, subprocess.CalledProcessError):
        raise V02SidecarError("GIT_STATE_INVALID") from None
    if branch != "develop" or head != expected_head or origin != head or status:
        raise V02SidecarError("GIT_STATE_INVALID")
    return {"branch": branch, "head": head, "origin_develop": origin, "clean": True}


def validate_paths(
    *,
    repository: Path,
    source: Path,
    tokenized: Path,
    raw: Path,
    output: Path,
) -> None:
    resolved = [path.resolve() for path in (repository, source, tokenized, raw, output)]
    repository_value, source_value, tokenized_value, raw_value, output_value = resolved
    if not all(path.is_absolute() for path in resolved):
        raise V02SidecarError("PATH_INVALID")
    if not all(
        path.is_dir()
        for path in (repository_value, source_value, tokenized_value, raw_value)
    ):
        raise V02SidecarError("PATH_INVALID")
    for protected in (repository_value, source_value, tokenized_value, raw_value):
        if (
            output_value == protected
            or output_value in protected.parents
            or protected in output_value.parents
        ):
            raise V02SidecarError("PATH_OVERLAP")


def run(arguments: argparse.Namespace) -> dict[str, object]:
    policy = load_policy(arguments.config)
    git = validate_git(arguments.repository.resolve(), arguments.expected_head)
    validate_paths(
        repository=arguments.repository,
        source=arguments.source_root,
        tokenized=arguments.tokenized_root,
        raw=arguments.raw_root,
        output=arguments.output_root,
    )
    if not arguments.execute:
        return {
            "status": "validated_not_executed",
            "git": git,
            "dataset_id": policy["dataset_id"],
            "tokenization_started": False,
            "training_started": False,
        }
    result = build_v02_sidecar_package(
        source_root=arguments.source_root,
        tokenized_root=arguments.tokenized_root,
        raw_root=arguments.raw_root,
        output_root=arguments.output_root,
        policy=policy,
        git_head=str(git["head"]),
    )
    return {"status": "completed", "git": git, **result}


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = run(arguments)
    except V02SidecarError as exc:
        print(
            json.dumps({"status": "failed_closed", "error": str(exc)}, sort_keys=True)
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
