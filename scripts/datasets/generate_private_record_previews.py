"""승인된 정책으로만 private record preview를 생성하는 CLI."""

from __future__ import annotations

import argparse
import json
import sys

from src.config.errors import ConfigError
from src.runtime.paths import repository_root

from .analyzer import DATASET_IDS, load_dataset_config
from .manual_path_mapping import load_manual_mapping
from .private_preview_policy import load_private_preview_policy
from .private_record_preview import generate_private_previews, private_review_output_root
from .safe_sampler import SamplerError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.datasets.generate_private_record_previews",
        description="명시적으로 승인된 정책에서만 외부 redacted 최소 text preview를 생성합니다.",
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--dataset", required=True, choices=DATASET_IDS)
    parser.add_argument("--manual-mapping", required=True)
    parser.add_argument("--preview-policy", required=True)
    parser.add_argument("--dry-run", action="store_true", help="content를 읽지 않고 승인·선택·출력 계획만 검증")
    parser.add_argument("--json", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    config = load_dataset_config(args.config)
    if args.dataset not in config.entries:
        raise SamplerError("선택한 데이터셋이 설정에 없습니다.")
    mapping = load_manual_mapping(args.manual_mapping, args.dataset)
    policy = load_private_preview_policy(
        args.preview_policy,
        args.dataset,
        require_approved=not args.dry_run,
    )
    output_root = private_review_output_root(config, None, repository_root())
    return generate_private_previews(
        config.entries[args.dataset], output_root, mapping, policy, dry_run=args.dry_run,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run(args)
    except (SamplerError, ConfigError, OSError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"{result['dataset_id']}: entry 계획 {result['entries_selected']}개, "
            f"검사 {result['entries_inspected']}개, preview {result['preview_count']}개"
        )
        print(f"상태: {result['run_status']}")
        print("산출물: 저장소 외부 analysis/private-review 경로")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
