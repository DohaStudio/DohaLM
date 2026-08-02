"""Dry-run or build the immutable DohaLM v0.3 short-answer Dataset."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

from src.data.v03_short_answer import (
    DATASET_ID,
    QwenSemanticEvaluator,
    V03ShortAnswerError,
    generate_candidates,
    load_policy,
    publish_package,
    validate_dry_run,
)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--config", type=Path, required=True)
    value.add_argument("--source-root", type=Path, required=True)
    value.add_argument("--model-root", type=Path, required=True)
    value.add_argument("--output-root", type=Path)
    value.add_argument("--repository", type=Path, required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--mode", choices=("dry-run", "full"), required=True)
    value.add_argument("--execute", action="store_true")
    return value


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def validate_git(
    repository: Path, expected_head: str, *, full: bool
) -> dict[str, object]:
    try:
        branch = _git(repository, "branch", "--show-current")
        head = _git(repository, "rev-parse", "HEAD")
        origin = _git(repository, "rev-parse", "origin/develop")
        status = _git(repository, "status", "--porcelain=v1")
    except (OSError, subprocess.CalledProcessError):
        raise V03ShortAnswerError("GIT_STATE_INVALID") from None
    if (
        head != expected_head
        or status
        or (full and (branch != "develop" or origin != head))
    ):
        raise V03ShortAnswerError("GIT_STATE_INVALID")
    return {"branch": branch, "head": head, "origin_develop": origin, "clean": True}


def run(arguments: argparse.Namespace) -> dict[str, object]:
    policy = load_policy(arguments.config)
    git = validate_git(
        arguments.repository.resolve(),
        arguments.expected_head,
        full=arguments.mode == "full",
    )
    semantic = policy["semantic_evaluator"]
    assert isinstance(semantic, dict)
    evaluator = QwenSemanticEvaluator(
        arguments.model_root,
        revision=str(semantic["model_revision"]),
        seed=int(semantic["seed"]),
    )
    if arguments.mode == "dry-run":
        result = generate_candidates(
            source_root=arguments.source_root,
            evaluator=evaluator,
            policy=policy,
            dry_run=True,
        )
        rates = validate_dry_run(result, policy)
        return {
            "status": "dry_run_passed",
            "dataset_id": DATASET_ID,
            "git": git,
            "model": evaluator.identity,
            "rates": rates,
            "tokenization_started": False,
            "training_started": False,
            "optimizer_steps": 0,
        }
    if not arguments.execute or arguments.output_root is None:
        return {
            "status": "validated_not_executed",
            "dataset_id": DATASET_ID,
            "git": git,
            "model": evaluator.identity,
            "tokenization_started": False,
            "training_started": False,
            "optimizer_steps": 0,
        }
    result = publish_package(
        source_root=arguments.source_root,
        output_root=arguments.output_root,
        policy=policy,
        evaluator=evaluator,
        git_head=str(git["head"]),
    )
    return {
        **result,
        "git": git,
        "model": evaluator.identity,
        "tokenization_started": False,
        "training_started": False,
        "optimizer_steps": 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        result = run(arguments)
    except V03ShortAnswerError as exc:
        print(
            json.dumps({"status": "failed_closed", "error": str(exc)}, sort_keys=True)
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
