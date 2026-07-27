"""Inspect and validate Candidate B; execution is explicit and fail-closed."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from src.runtime.paths import resolve_repository_path
from src.training.candidate_b import (
    inspect_candidate_b_readiness,
    inspect_candidate_b_runtime,
    load_resolved_candidate_b_config,
    probe_candidate_b_output,
    require_candidate_b_execution,
    resolve_candidate_b_config,
    write_resolved_candidate_b_config,
)
from src.training.candidate_b_backend import (
    candidate_b_execution_plan,
    run_candidate_b,
    run_candidate_b_cpu_smoke,
)
from src.training.errors import TrainingError

from ._common import cli_error, print_result


MODES = ("inspect", "resolve-config", "validate", "cpu-smoke", "preflight", "execute")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Candidate B inspection-first orchestration backend.")
    parser.add_argument("mode", nargs="?", default="inspect", choices=MODES)
    parser.add_argument("--example-config", default="configs/candidate-b.example.yaml")
    parser.add_argument("--local-binding", default="configs/candidate-b.local.yaml")
    parser.add_argument("--readiness-manifest", default="docs/training/candidate-b-readiness.manifest.yaml")
    parser.add_argument("--resolved-config", default="configs/candidate-b-resolved.yaml")
    parser.add_argument("--approval", default="configs/candidate-b-approval.yaml")
    parser.add_argument("--cpu-validation-result", default="docs/training/candidate-b-cpu-validation.manifest.yaml")
    parser.add_argument("--output-probe-result", default="docs/training/candidate-b-output-probe.manifest.yaml")
    parser.add_argument("--probe-output", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _repository_path(value: str) -> Path:
    return resolve_repository_path(value)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        example_path = _repository_path(args.example_config)
        binding_path = _repository_path(args.local_binding)
        readiness_manifest_path = _repository_path(args.readiness_manifest)
        resolved_path = _repository_path(args.resolved_config)
        approval_path = _repository_path(args.approval)
        cpu_validation_path = _repository_path(args.cpu_validation_result)
        output_probe_path = _repository_path(args.output_probe_result)

        if args.mode != "execute" and args.execute:
            raise TrainingError("CANDIDATE_B_MODE_CONFLICT", "--execute는 execute mode에서만 허용됩니다.")
        if args.mode == "resolve-config":
            resolved = resolve_candidate_b_config(
                example_path, binding_path, readiness_manifest_path,
                allow_placeholder_run_id=False,
            )
            write_resolved_candidate_b_config(resolved_path, resolved["document"])
            print_result({
                "status": "resolved_config_created",
                "resolved_config": str(Path(args.resolved_config).as_posix()),
                "resolved_config_fingerprint": resolved["resolved_config_fingerprint"],
                "training_started": False,
            }, json_output=args.json)
            return 0

        resolved = load_resolved_candidate_b_config(resolved_path, allow_placeholder_run_id=False)
        if args.mode == "validate":
            print_result({
                "status": "validated",
                "plan": candidate_b_execution_plan(resolved),
                "training_started": False,
                "execution_allowed": False,
            }, json_output=args.json)
            return 0
        if args.mode == "cpu-smoke":
            print_result(run_candidate_b_cpu_smoke(resolved), json_output=args.json)
            return 0

        runtime = inspect_candidate_b_runtime() if args.mode == "preflight" else None
        cpu_validation = yaml.safe_load(cpu_validation_path.read_text(encoding="utf-8")) if cpu_validation_path.is_file() else None
        probe = (
            probe_candidate_b_output(resolved) if args.probe_output
            else yaml.safe_load(output_probe_path.read_text(encoding="utf-8")) if output_probe_path.is_file()
            else None
        )
        report = inspect_candidate_b_readiness(
            resolved_config_path=resolved_path,
            approval_path=approval_path if approval_path.is_file() else None,
            cpu_validation=cpu_validation,
            output_probe=probe,
            physical_preflight=None,
        )
        if args.mode == "preflight":
            print_result({**report, "runtime": runtime}, json_output=args.json)
            return 0
        if args.mode == "inspect":
            print_result(report, json_output=args.json)
            return 0
        if not args.execute:
            raise TrainingError("CANDIDATE_B_EXPLICIT_EXECUTE_REQUIRED", "execute mode에는 --execute가 필요합니다.")
        require_candidate_b_execution(report)
        approval = yaml.safe_load(approval_path.read_text(encoding="utf-8"))
        print_result(run_candidate_b(
            resolved=resolved,
            resolved_config_path=resolved_path,
            approval=approval,
            approval_path=approval_path,
            readiness_report=report,
        ), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
