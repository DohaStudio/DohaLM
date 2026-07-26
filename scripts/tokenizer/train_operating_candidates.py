"""Train and compare approved AIHUB-71748 operating 16k tokenizer candidates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.data.aihub_71748_tokenizer_corpus import resolve_local_paths
from src.tokenizer.operating import OperatingTrainerConfig, compare_candidates, train_operating_candidate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/local-datasets.yaml"))
    parser.add_argument("--corpus-dir", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--num-threads", type=int, default=1)
    parser.add_argument("--profile", choices=("v1", "v2"), default="v1")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        external_root, _ = resolve_local_paths(args.config)
        corpus_root = external_root / "analysis/tokenizer-development/AIHUB-71748/operating-16k-v1/corpus"
        run_root = external_root / f"analysis/tokenizer-development/AIHUB-71748/operating-16k-{args.profile}"
        corpus = (args.corpus_dir or corpus_root).resolve()
        output = (args.output_root or run_root / "tokenizers").resolve()
        if external_root not in output.parents:
            raise ValueError("tokenizer output must be below configured external_root")
        profile = {}
        if args.profile == "v2":
            profile = {
                "character_coverage": 1.0,
                "byte_fallback": True,
                "remove_extra_whitespaces": False,
                "add_dummy_prefix": False,
                "allow_whitespace_only_pieces": True,
                "treat_whitespace_as_suffix": False,
            }
        unigram = train_operating_candidate(
            corpus,
            output / "unigram-16k",
            OperatingTrainerConfig("unigram", num_threads=args.num_threads, **profile),
        )
        bpe = train_operating_candidate(
            corpus,
            output / "bpe-16k",
            OperatingTrainerConfig("bpe", num_threads=args.num_threads, **profile),
        )
        comparison = compare_candidates(output / "unigram-16k", output / "bpe-16k", output / "comparison.json")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    result = {
        "unigram_fingerprint": unigram["tokenizer_fingerprint"],
        "bpe_fingerprint": bpe["tokenizer_fingerprint"],
        "recommended_model_type": comparison["recommended_model_type"],
        "gate3_status": comparison["gate3_status"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else "\n".join(f"{key}: {value}" for key, value in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
