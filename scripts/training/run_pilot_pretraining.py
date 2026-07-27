"""Run a bounded pilot from an explicit local configuration."""

from __future__ import annotations

import argparse

from src.runtime.paths import repository_root, resolve_repository_path
from src.training.pilot_config import PilotPretrainingConfig
from src.training.pilot_execution import inspect_pilot_execution, require_pilot_execution_approval
from src.training.pilot_pretraining import run_pilot_pretraining

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pilot Pretraining 계획을 검사하며 명시적 승인 manifest 없이는 실행하지 않습니다.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--execute", action="store_true", help="승인 manifest 검증 후에만 설정 그대로 실행")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config_path = resolve_repository_path(args.config)
        manifest_path = resolve_repository_path(args.manifest)
        report = inspect_pilot_execution(config_path, manifest_path, repository_root() / "docs/quality/development-roadmap.md")
        if not args.execute:
            print_result(report, json_output=args.json)
            return 0
        require_pilot_execution_approval(report)
        config = PilotPretrainingConfig.from_yaml(config_path)
        print_result(run_pilot_pretraining(config), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
