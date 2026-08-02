"""Validate or execute the single DohaLM v0.3 tokenization run."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from src.training.sft_tokenization import SFTTokenizationError
from src.training.v03_tokenization import V03TokenizationError, build_package, validate_source


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True, text=True).stdout.strip()


def validate_git(repository: Path, expected_head: str) -> dict[str, object]:
    try:
        branch = _git(repository, "branch", "--show-current")
        head = _git(repository, "rev-parse", "HEAD")
        origin = _git(repository, "rev-parse", "origin/develop")
        status = _git(repository, "status", "--porcelain=v1")
    except (OSError, subprocess.CalledProcessError):
        raise V03TokenizationError("GIT_STATE_INVALID") from None
    if branch != "develop" or head != expected_head or origin != head or status:
        raise V03TokenizationError("GIT_STATE_INVALID")
    return {"branch": branch, "head": head, "origin_develop": origin, "clean": True}


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repository", type=Path, required=True)
    value.add_argument("--source-root", type=Path, required=True)
    value.add_argument("--reuse-root", type=Path, required=True)
    value.add_argument("--tokenizer-root", type=Path, required=True)
    value.add_argument("--output-root", type=Path, required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--execute", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        git = validate_git(args.repository.resolve(), args.expected_head)
        if not args.source_root.resolve().is_dir() or not args.reuse_root.resolve().is_dir() or not args.tokenizer_root.resolve().is_dir() or not args.output_root.resolve().is_absolute():
            raise V03TokenizationError("PATH_INVALID")
        validate_source(args.source_root.resolve())
        result = ({"status": "validated_not_executed"} if not args.execute else build_package(source_root=args.source_root.resolve(), reuse_root=args.reuse_root.resolve(), tokenizer_root=args.tokenizer_root.resolve(), output_root=args.output_root.resolve(), git_head=str(git["head"])))
        result = {**result, "git": git, "training_started": False, "optimizer_steps": 0}
    except (V03TokenizationError, SFTTokenizationError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed_closed", "error": str(exc), "training_started": False, "optimizer_steps": 0}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
