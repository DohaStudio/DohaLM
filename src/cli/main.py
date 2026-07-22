"""Phase 0 진단 및 설정 검증 CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from src.config.errors import ConfigError
from src.config.loader import load_resolved_config, mask_secrets, parse_overrides
from src.runtime.environment import collect_environment, cpu_smoke_test, cuda_smoke_test, python_supported
from src.runtime.paths import inspect_paths, repository_root, tracked_artifact_violations


def _default_config(name: str) -> str:
    return str(repository_root() / "configs" / name)


def _print(value: Any, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    else:
        print(yaml.safe_dump(value, allow_unicode=True, sort_keys=False).rstrip())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dohalm", description="DohaLM Phase 0 도구")
    commands = parser.add_subparsers(dest="command", required=True)

    environment = commands.add_parser("environment", help="실행 환경을 읽기 전용으로 진단합니다.")
    environment.add_argument("--cuda-smoke", action="store_true", help="작은 CUDA 텐서를 생성하고 해제합니다.")
    environment.add_argument("--json", action="store_true")

    config = commands.add_parser("config", help="설정 파일을 검증하거나 병합합니다.")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    for name in ("validate", "resolve"):
        command = config_commands.add_parser(name)
        command.add_argument("--model", default=None, help="모델 YAML 경로 (기본: configs/tiny.yaml)")
        command.add_argument("--run", default=None, help="목적별 실행 YAML 경로")
        command.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
        command.add_argument("--allow-incomplete", action="store_true")
        command.add_argument("--json", action="store_true")

    paths = commands.add_parser("paths", help="저장소 기준 경로를 생성하지 않고 확인합니다.")
    paths.add_argument("--json", action="store_true")
    return parser


def _environment_command(args: argparse.Namespace) -> int:
    environment = collect_environment()
    cpu_smoke = cpu_smoke_test()
    required_fields = ("os", "python_version", "pytorch_version", "git_commit", "git_branch", "git_dirty")
    diagnostic_success = cpu_smoke["success"] and python_supported() and all(
        environment[field]["error"] is None for field in required_fields
    )
    report: dict[str, Any] = {
        "python_supported": python_supported(),
        "diagnostic_success": diagnostic_success,
        "cpu_smoke": cpu_smoke,
        "environment": environment,
    }
    if args.cuda_smoke:
        report["cuda_smoke"] = cuda_smoke_test()
    _print(report, as_json=args.json)
    if not diagnostic_success:
        return 2
    if args.cuda_smoke and not report["cuda_smoke"]["success"]:
        return 2
    return 0


def _config_command(args: argparse.Namespace) -> int:
    model = args.model or _default_config("tiny.yaml")
    resolved = load_resolved_config(
        model,
        args.run,
        overrides=parse_overrides(args.set),
        require_complete=not args.allow_incomplete,
    )
    if args.config_command == "validate":
        _print({"valid": True, "model": str(model), "run": args.run}, as_json=args.json)
    else:
        _print(mask_secrets(resolved), as_json=args.json)
    return 0


def _paths_command(args: argparse.Namespace) -> int:
    report = {
        "paths": inspect_paths(),
        "tracked_artifact_violations": tracked_artifact_violations(),
    }
    _print(report, as_json=args.json)
    return 2 if report["tracked_artifact_violations"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "environment":
            return _environment_command(args)
        if args.command == "config":
            return _config_command(args)
        if args.command == "paths":
            return _paths_command(args)
    except (ConfigError, RuntimeError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    parser.error("지원하지 않는 명령입니다.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
