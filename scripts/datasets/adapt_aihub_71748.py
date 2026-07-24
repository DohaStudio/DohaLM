"""CLI for the synthetic AIHUB-71748 corpus adapter contract."""

from __future__ import annotations

import argparse
import json
import sys
from itertools import islice
from pathlib import Path
from typing import Any

from src.data.adapters.aihub_71748 import AIHub71748Adapter, DATASET_ID
from src.data.adapters.base import AdapterArtifactWriter, iter_adapted, load_synthetic_json_records
from src.data.errors import DataPipelineError


DEFAULT_MAX_READ_BYTES = 16 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AIHUB-71748 합성 fixture 어댑터를 검증하거나 실제 실행 차단 상태를 확인합니다."
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dataset", default=DATASET_ID)
    parser.add_argument("--manual-mapping", type=Path)
    parser.add_argument("--approval-log", type=Path)
    parser.add_argument("--max-records", type=int)
    parser.add_argument("--max-read-bytes", type=int, default=DEFAULT_MAX_READ_BYTES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _synthetic_run(args: argparse.Namespace) -> dict[str, Any]:
    if args.input is None or args.output is None:
        raise ValueError("--synthetic requires both --input and --output")
    if args.config is not None or args.manual_mapping is not None or args.approval_log is not None:
        raise ValueError("synthetic mode does not accept actual dataset configuration")
    if args.dry_run:
        raise ValueError("synthetic mode publishes only bounded test artifacts; omit --dry-run")
    if args.max_read_bytes <= 0 or (args.max_records is not None and args.max_records <= 0):
        raise ValueError("read and record limits must be positive")

    root = Path.cwd().resolve()
    fixture_root = root / "tests" / "fixtures" / "data" / "aihub_71748"
    output_root = root / "tests" / "output"
    if not _inside(args.input, fixture_root):
        raise ValueError("synthetic mode accepts only tests/fixtures/data/aihub_71748 inputs")
    if not _inside(args.output, output_root):
        raise ValueError("synthetic mode writes only below tests/output")

    records = load_synthetic_json_records(args.input, max_read_bytes=args.max_read_bytes)
    if args.max_records is not None:
        records = islice(records, args.max_records)
    adapter = AIHub71748Adapter()
    manifest = AdapterArtifactWriter(args.output, adapter).publish(
        iter_adapted(records, adapter), source_path=args.input
    )
    return {
        "status": "synthetic_adapter_completed",
        "dataset_id": DATASET_ID,
        "output": args.output.resolve().relative_to(root).as_posix(),
        "accepted_record_count": manifest["accepted_record_count"],
        "rejected_record_count": manifest["rejected_record_count"],
        "usage_status": manifest["usage_status"],
        "actual_dataset_execution": "blocked",
        "development_corpus_publish": "blocked",
    }


def _actual_dry_run(args: argparse.Namespace) -> dict[str, Any]:
    if args.dataset != DATASET_ID:
        raise ValueError(f"only {DATASET_ID} is supported")
    if not args.dry_run:
        raise ValueError("actual dataset execution is blocked; use --dry-run")
    if args.input is not None or args.output is not None:
        raise ValueError("actual dry-run does not accept --input or --output")
    if args.config is None or args.manual_mapping is None:
        raise ValueError("actual dry-run requires --config and --manual-mapping")
    # Deliberately do not open config, mapping, approval log, ZIP, or record content.
    return {
        "status": "blocked_pending_approval",
        "dataset_id": DATASET_ID,
        "actual_dataset_execution": "blocked",
        "development_corpus_publish": "blocked",
        "records_read": 0,
        "content_bytes_read": 0,
        "artifacts_published": 0,
        "license_status": "pending_terms_review",
        "approval_status": "pending",
        "pii_status": "review_required",
        "private_preview_review": "not_approved",
        "tokenizer_development_approval": "pending",
        "blocked_reasons": [
            "LICENSE_NOT_APPROVED",
            "APPROVAL_NOT_APPROVED",
            "PII_REVIEW_REQUIRED",
            "PRIVATE_PREVIEW_REVIEW_NOT_APPROVED",
            "TOKENIZER_DEVELOPMENT_NOT_APPROVED",
        ],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    return _synthetic_run(args) if args.synthetic else _actual_dry_run(args)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run(args)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            for key, value in result.items():
                print(f"{key}: {value}")
        return 0
    except (DataPipelineError, OSError, RuntimeError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
