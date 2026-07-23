"""AI Hub 데이터셋 구조 분석 CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.config.errors import ConfigError
from src.runtime.paths import repository_root

from .analyzer import (
    DATASET_IDS,
    AnalyzerError,
    analyze_dataset,
    load_dataset_config,
    safe_output_root,
    write_reports,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.datasets.analyze_aihub_dataset",
        description="외부 AI Hub 데이터셋의 구조를 원문 노출 없이 읽기 전용으로 분석합니다.",
    )
    parser.add_argument("--config", required=True, help="로컬 데이터셋 YAML 경로")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--dataset", choices=DATASET_IDS)
    selection.add_argument("--all", action="store_true", help="설정에 등록된 5개 데이터셋을 모두 분석")
    parser.add_argument("--inventory-only", action="store_true", help="inventory와 ZIP 중앙 디렉터리만 분석")
    parser.add_argument("--sample-files", type=int, default=20, help="JSON/JSONL/TXT 최대 표본 파일 수")
    parser.add_argument("--max-json-bytes", type=int, default=10 * 1024 * 1024, help="JSON 계열 파일당 최대 읽기 byte")
    parser.add_argument("--output-dir", help="외부 root 기준 상대 경로 또는 저장소 밖 절대 경로")
    parser.add_argument("--json", action="store_true", help="안전한 실행 요약을 JSON으로 출력")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.sample_files <= 0 or args.max_json_bytes <= 0:
        raise AnalyzerError("sample-files와 max-json-bytes는 0보다 커야 합니다.")
    config = load_dataset_config(args.config)
    selected = list(config.entries) if args.all else [args.dataset]
    if set(selected) - set(config.entries):
        raise AnalyzerError("선택한 데이터셋이 설정에 없습니다.")
    output_root = safe_output_root(config, args.output_dir, repository_root())
    reports = []
    for dataset_id in selected:
        print(f"분석 시작: {dataset_id}", file=sys.stderr)
        report = analyze_dataset(
            config.entries[dataset_id],
            sample_files=args.sample_files,
            max_json_bytes=args.max_json_bytes,
            inventory_only=args.inventory_only,
        )
        written = write_reports(report, output_root)
        reports.append({
            "dataset_id": dataset_id,
            "analysis_mode": report["analysis_mode"],
            "file_count": report["inventory"]["file_count"],
            "total_bytes": report["inventory"]["total_bytes"],
            "archive_count": len(report["archive_inventory"]["archives"]),
            "artifacts_written": [path.name for path in written],
            "source_mutation_detected": report["source_mutation_detected"],
        })
        print(f"분석 완료: {dataset_id}", file=sys.stderr)
    return {"success": True, "output_location": "external_analysis_root", "datasets": reports}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except (AnalyzerError, ConfigError, OSError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in result["datasets"]:
            print(
                f"{item['dataset_id']}: 파일 {item['file_count']}개, "
                f"ZIP {item['archive_count']}개, 모드 {item['analysis_mode']}"
            )
        print("분석 산출물: 저장소 외부 analysis 경로")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
