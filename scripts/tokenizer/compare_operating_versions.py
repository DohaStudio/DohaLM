"""Compare immutable v1 and v2 operating tokenizer candidates on one sample."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.data.aihub_71748_tokenizer_corpus import resolve_local_paths
from src.tokenizer.operating import compare_candidate_set


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/local-datasets.yaml"))
    parser.add_argument("--corpus-dir", type=Path)
    parser.add_argument("--v1-root", type=Path)
    parser.add_argument("--v2-root", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        external_root, _ = resolve_local_paths(args.config)
        base = external_root / "analysis/tokenizer-development/AIHUB-71748"
        corpus = (args.corpus_dir or base / "operating-16k-v1/corpus").resolve()
        v1 = (args.v1_root or base / "operating-16k-v1/tokenizers").resolve()
        v2 = (args.v2_root or base / "operating-16k-v2/tokenizers").resolve()
        output = (args.output or base / "operating-16k-v2/comparison-v1-v2.json").resolve()
        if external_root not in output.parents:
            raise ValueError("comparison output must be below configured external_root")
        candidates = {
            "operating-16k-v1/unigram-16k": v1 / "unigram-16k",
            "operating-16k-v1/bpe-16k": v1 / "bpe-16k",
            "operating-16k-v2/unigram-16k": v2 / "unigram-16k",
            "operating-16k-v2/bpe-16k": v2 / "bpe-16k",
        }
        result = compare_candidate_set(corpus, candidates, output)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "candidate_count": len(result["candidates"]),
        "recommended_candidate_id": result["recommended_candidate_id"],
        "sample_fingerprint": result["evaluation_sample"]["sample_fingerprint"],
        "gate3_status": result["gate3_status"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
