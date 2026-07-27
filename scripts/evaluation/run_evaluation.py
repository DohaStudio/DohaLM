"""Inspection-first CLI for the DohaLM evaluation framework."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.evaluation import (
    ARTIFACT_ORDER,
    ArtifactRegistry,
    EvaluationConfig,
    EvaluationError,
    publish_failure,
    publish_quick_comparison,
    run_evaluation,
)
from src.evaluation.reporting import compare_completed_results, leaderboard_row, load_completed_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DohaLM evaluation-only runner")
    parser.add_argument("--config", default="configs/evaluation.example.yaml")
    parser.add_argument("--mode", choices=("inspect", "quick", "full", "compare", "report"), default="inspect")
    parser.add_argument("--artifact-id", default="candidate-a-final")
    parser.add_argument("--evaluation-id")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--result", action="append", default=[], help="artifact-id:evaluation-id")
    parser.add_argument("--comparison-id")
    parser.add_argument("--quick-reference", help="immutable artifact-id:evaluation-id Quick result for Full comparison")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = None
    try:
        config = EvaluationConfig.from_yaml(Path(args.config), profile=args.mode if args.mode in {"quick", "full"} else None)
        registry = ArtifactRegistry.load(config.repository_path(config.artifact_registry))
        if args.mode == "inspect":
            result = {"mode": "inspection_only", "training_started": False, "artifacts": [registry.inspect(config, artifact_id) for artifact_id in registry.artifacts]}
        elif args.mode in {"quick", "full"}:
            if not args.execute:
                raise EvaluationError("EXPLICIT_EXECUTE_REQUIRED", "quick/full evaluation requires --execute")
            if not args.evaluation_id:
                raise EvaluationError("EVALUATION_ID_REQUIRED", "quick/full evaluation requires --evaluation-id")
            quick_reference = None
            if args.mode == "full":
                if not args.quick_reference:
                    raise EvaluationError("QUICK_REFERENCE_REQUIRED", "full evaluation requires --quick-reference")
                quick_reference = load_completed_result(config, args.quick_reference)
            result = run_evaluation(
                config, registry, args.artifact_id,
                evaluation_id=args.evaluation_id, quick_reference=quick_reference,
            )
        elif args.mode == "compare":
            if args.comparison_id:
                references = dict(item.split(":", 1) for item in args.result if ":" in item)
                if tuple(references) != ARTIFACT_ORDER:
                    raise EvaluationError("COMPARISON_ORDER_INVALID", "--result order must be Initial, Pilot, Mid, Final")
                result = publish_quick_comparison(
                    config, registry, comparison_id=args.comparison_id, evaluation_ids=references,
                )
            else:
                result = compare_completed_results([load_completed_result(config, item) for item in args.result])
        else:
            completed = [load_completed_result(config, item) for item in args.result]
            if not completed:
                raise EvaluationError("EVALUATION_REPORT_INCOMPLETE", "report requires at least one --result")
            result = {"mode": "report", "status": "completed", "rows": [leaderboard_row(item["manifest"], item["metrics"]) for item in completed], "raw_text_stored": False}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        if args.execute and args.evaluation_id and config is not None:
            try:
                publish_failure(config, args.artifact_id, args.evaluation_id, exc)
            except Exception:
                pass
        print(json.dumps({"status": "failed", "error_code": getattr(exc, "code", type(exc).__name__), "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
