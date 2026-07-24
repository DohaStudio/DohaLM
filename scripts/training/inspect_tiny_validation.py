"""Inspect a Tiny validation artifact without exposing local absolute paths."""

from __future__ import annotations

import argparse
import json

from src.runtime.paths import resolve_repository_path
from src.training import CheckpointManager, TrainingError

from ._common import cli_error, print_result


REQUIRED = (
    "run-summary.json",
    "batch-probe.json",
    "throughput.json",
    "memory.json",
    "training-metrics.jsonl",
    "resume-validation.json",
    "sampler-state.json",
    "validation-manifest.json",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tiny validation 산출물과 checkpoint 무결성을 검사합니다.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def inspect(path_value: str) -> dict[str, object]:
    run_dir = resolve_repository_path(path_value)
    if not run_dir.is_dir():
        raise TrainingError("RESUME_STATE_MISMATCH", "Tiny validation run 디렉터리가 없습니다.")
    missing = [name for name in REQUIRED if not (run_dir / name).is_file()]
    if missing:
        raise TrainingError("RESUME_STATE_MISMATCH", f"Tiny validation 필수 산출물이 없습니다: {missing}")
    documents = {}
    for name in REQUIRED:
        if name.endswith(".json"):
            documents[name] = json.loads((run_dir / name).read_text(encoding="utf-8"))
    checkpoints = [CheckpointManager.inspect(path).to_dict() for path in sorted(run_dir.glob("checkpoint-*")) if path.is_dir()]
    if not checkpoints:
        raise TrainingError("RESUME_STATE_MISMATCH", "검증할 checkpoint가 없습니다.")
    return {
        "status": "tiny_validation_valid",
        "run_directory_name": run_dir.name,
        "run_summary": documents["run-summary.json"],
        "checkpoint_count": len(checkpoints),
        "checkpoints": checkpoints,
        "synthetic_only": documents["validation-manifest.json"].get("synthetic_only") is True,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print_result(inspect(args.run_dir), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
