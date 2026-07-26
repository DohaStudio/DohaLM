"""Refresh aggregate metrics and validate existing operating tokenizer candidates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.tokenizer.operating import compare_candidates, refresh_candidate_evaluation, validate_operating_candidate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        roots = [args.tokenizer_root / "unigram-16k", args.tokenizer_root / "bpe-16k"]
        for root in roots:
            validate_operating_candidate(root)
            refresh_candidate_evaluation(args.corpus_dir, root)
        comparison = compare_candidates(roots[0], roots[1], args.tokenizer_root / "comparison.json")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    summary = {
        "validated_candidates": 2,
        "recommended_model_type": comparison["recommended_model_type"],
        "gate3_status": comparison["gate3_status"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
