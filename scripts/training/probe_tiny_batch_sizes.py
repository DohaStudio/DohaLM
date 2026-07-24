"""Probe bounded full-scale Tiny batch candidates without source data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from src.data.checksums import checksum_value
from src.runtime.paths import resolve_repository_path
from src.training import DEFAULT_BATCH_CANDIDATES, TrainingError, probe_batch_candidates

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RTX 3060 Ti용 합성 Tiny batch 후보를 1-step씩 검증합니다.")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--dtype", choices=("float32", "float16"), default="float16")
    parser.add_argument("--output", default="tests/output/tiny-batch-probe")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--json", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    use_amp = args.dtype == "float16"
    if args.device == "cpu" and use_amp:
        raise TrainingError("AMP_NOT_AVAILABLE", "CPU probe는 float32만 지원합니다.")
    payload = {"device": args.device, "dtype": args.dtype, "seed": args.seed}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    digest = checksum_value(payload).split(":", 1)[-1]
    run_name = f"probe-{stamp}-{digest[:10]}"
    report = probe_batch_candidates(
        DEFAULT_BATCH_CANDIDATES,
        device=args.device,
        use_amp=use_amp,
        output_root=resolve_repository_path(args.output) / run_name,
        seed=args.seed,
    )
    return {"status": "probe_complete", "run_directory_name": run_name, **report}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print_result(run(args), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
