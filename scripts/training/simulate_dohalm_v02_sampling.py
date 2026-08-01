"""Run the model-free DohaLM v0.2 weighted sampling simulation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from scripts.training.build_dohalm_v02_tokenized import validate_git
from src.training.v02_weighted import V02WeightedError, simulate_sampling


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repository", type=Path, required=True)
    value.add_argument("--tokenized-root", type=Path, required=True)
    value.add_argument("--sidecar-root", type=Path, required=True)
    value.add_argument("--output-root", type=Path, required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--execute", action="store_true")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        git = validate_git(arguments.repository, arguments.expected_head)
        for path in (arguments.tokenized_root, arguments.sidecar_root):
            if not path.resolve().is_dir():
                raise V02WeightedError("PATH_INVALID")
        if not arguments.output_root.resolve().is_absolute():
            raise V02WeightedError("PATH_INVALID")
        if not arguments.execute:
            result: dict[str, object] = {"status": "validated_not_executed", "git": git, "training_started": False}
        else:
            result = {"status": "completed", "git": git, **simulate_sampling(
                tokenized_root=arguments.tokenized_root,
                sidecar_root=arguments.sidecar_root,
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
