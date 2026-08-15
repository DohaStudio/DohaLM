"""Inspect legacy Candidate A or run the local single-user activation boundary."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.runtime.paths import resolve_repository_path
from src.training.errors import TrainingError
from src.training.full_pretraining import inspect_full_pretraining_readiness
from src.training.full_pretraining_backend import dry_run_full_pretraining
from src.training.local_activation import (
    LocalDurablePostgresBootstrapper,
    bootstrap_local_postgres,
    execute_local_training,
    inspect_local_training_readiness,
    load_local_activation_configuration,
    load_local_role_credentials,
    result_json,
)

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or run the fail-closed Candidate A package."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--probe-output", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _local_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operate the explicit local single-user activation profile."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("bootstrap", "readiness", "execute", "stop", "destroy"):
        subparser = commands.add_parser(command)
        subparser.add_argument("--config", required=True)
        if command == "destroy":
            subparser.add_argument("--confirm-correlation-id", required=True)
    return parser


def _local_main(argv: list[str]) -> int:
    args = _local_parser().parse_args(argv)
    configuration = load_local_activation_configuration(Path(args.config).resolve())
    if args.command == "bootstrap":
        print(result_json(bootstrap_local_postgres(configuration)))
        return 0
    if args.command == "readiness":
        print(result_json(inspect_local_training_readiness(configuration)))
        return 0
    if args.command == "execute":
        print(result_json(execute_local_training(configuration)))
        return 0
    credentials, directory = load_local_role_credentials(configuration)
    bootstrapper = LocalDurablePostgresBootstrapper(
        configuration, credentials, directory
    )
    if args.command == "stop":
        bootstrapper.stop()
    else:
        bootstrapper.destroy(confirm_correlation_id=args.confirm_correlation_id)
    print(result_json({"status": "COMPLETED", "command": args.command}))
    return 0


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    try:
        if values and values[0] in {
            "bootstrap",
            "readiness",
            "execute",
            "stop",
            "destroy",
        }:
            return _local_main(values)
        args = _parser().parse_args(values)
        if args.dry_run and args.execute:
            raise TrainingError(
                "FULL_PRETRAINING_MODE_CONFLICT",
                "--dry-run and --execute are mutually exclusive.",
            )
        if args.execute:
            raise TrainingError(
                "TRAINING_EXECUTION_APPROVAL_REQUIRED",
                "CLI execution cannot issue a production Training Execution Approval.",
            )
        config_path = resolve_repository_path(args.config)
        manifest_path = resolve_repository_path(args.manifest)
        if args.dry_run:
            print_result(
                dry_run_full_pretraining(
                    config_path, manifest_path, probe_output=args.probe_output
                ),
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
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
