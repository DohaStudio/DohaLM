"""Validate or execute the single DohaLM v0.3 sampler simulation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.training.build_dohalm_v03_tokenized import validate_git
from src.training.v03_sampler import V03SamplerError, publish_simulation
from src.training.v03_tokenization import V03TokenizationError


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repository", type=Path, required=True)
    value.add_argument("--tokenized-root", type=Path, required=True)
    value.add_argument("--output-root", type=Path, required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--execute", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        git = validate_git(args.repository.resolve(), args.expected_head)
        if not args.tokenized_root.resolve().is_dir() or not args.output_root.resolve().is_absolute():
            raise V03SamplerError("PATH_INVALID")
        result = ({"status": "validated_not_executed"} if not args.execute else publish_simulation(tokenized_root=args.tokenized_root.resolve(), output_root=args.output_root.resolve(), git_head=str(git["head"])))
        result = {**result, "git": git, "training_started": False, "optimizer_steps": 0}
    except (V03SamplerError, V03TokenizationError, OSError, ValueError) as exc:
        print(json.dumps({"status": "failed_closed", "error": str(exc), "training_started": False, "optimizer_steps": 0}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
