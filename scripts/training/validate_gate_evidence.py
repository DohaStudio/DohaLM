"""Validate ignored Tiny runs and publish a Gate 4-6 review bundle."""

from __future__ import annotations

import argparse

from src.runtime.paths import repository_root, resolve_repository_path
from src.training.gate_evidence import build_gate_evidence, collect_test_suite_evidence, publish_evidence_bundle
from src.training.pilot_readiness import validate_pilot_readiness

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ignored Tiny 산출물을 검증하여 Gate 4·5·6 검토 bundle을 생성합니다.")
    parser.add_argument("--tiny-validation", required=True)
    parser.add_argument("--tiny-overfit", required=True)
    parser.add_argument("--batch-probe", required=True)
    parser.add_argument("--output", default="tests/output/gate-evidence")
    parser.add_argument("--config", default="configs/pretrain.yaml")
    parser.add_argument("--run-id")
    parser.add_argument("--json", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    root = repository_root()
    tests = collect_test_suite_evidence(root)
    gates = build_gate_evidence(
        tiny_validation_dir=resolve_repository_path(args.tiny_validation),
        tiny_overfit_dir=resolve_repository_path(args.tiny_overfit),
        batch_probe_dir=resolve_repository_path(args.batch_probe),
        test_evidence=tests,
    )
    pilot = validate_pilot_readiness(resolve_repository_path(args.config), root / "docs/quality/development-roadmap.md")
    return publish_evidence_bundle(output_root=resolve_repository_path(args.output), gates=gates, pilot_readiness=pilot, run_id=args.run_id)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print_result(run(args), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
