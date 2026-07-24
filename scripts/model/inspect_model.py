"""Inspect the approved DohaLM-Tiny config and unique parameter count."""

from __future__ import annotations

import argparse

from src.model import DohaLMTiny, ModelConfig, ParameterCounter

from ._common import cli_error, print_result, smoke_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DohaLM-Tiny 설정과 파라미터 구성을 출력합니다.")
    parser.add_argument("--small", action="store_true", help="합성 smoke용 작은 config를 사용합니다.")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    config = smoke_config() if args.small else ModelConfig()
    model = DohaLMTiny(config)
    return {
        "status": "inspection_complete",
        "config": config.to_dict(),
        "parameter_breakdown": model.parameter_breakdown(),
        "expected_parameter_count": ParameterCounter.expected_tiny_total(config),
        "weight_tied": model.token_embedding.weight is model.lm_head.weight,
        "full_model_integration": True,
        "trainer_implemented": False,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        print_result(run(_parser().parse_args(argv)))
        return 0
    except (RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
