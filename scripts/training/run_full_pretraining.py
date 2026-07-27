"""Inspect, dry-run, or explicitly execute Full Pretraining Candidate A."""

from __future__ import annotations

import argparse

from src.runtime.paths import resolve_repository_path
from src.training.errors import TrainingError
from src.training.full_pretraining import inspect_full_pretraining_readiness, require_full_pretraining_approval
from src.training.full_pretraining_backend import dry_run_full_pretraining, run_full_pretraining

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or run the fail-closed Candidate A package.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--probe-output", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.dry_run and args.execute:
            raise TrainingError("FULL_PRETRAINING_MODE_CONFLICT", "--dry-run and --execute are mutually exclusive.")
        config_path = resolve_repository_path(args.config)
        manifest_path = resolve_repository_path(args.manifest)
        if args.dry_run:
            print_result(
                dry_run_full_pretraining(config_path, manifest_path, probe_output=args.probe_output),
                json_output=args.json,
            )
            return 0
        report = inspect_full_pretraining_readiness(
            config_path,
            manifest_path,
            probe_output=args.probe_output,
        )
        if not args.execute:
            print_result(report, json_output=args.json)
            return 0
        require_full_pretraining_approval(report)
        print_result(run_full_pretraining(config_path, manifest_path, report), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
