"""Synthetic corpus 전용 tokenizer smoke 학습 CLI."""

from __future__ import annotations

import argparse
import json
import sys

from src.runtime.paths import repository_root, resolve_repository_path
from src.tokenizer.errors import TokenizerError
from src.tokenizer.trainer import TrainerConfig, train_smoke_tokenizer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.tokenizer.train_tokenizer",
        description="추적 가능한 synthetic fixture만으로 SentencePiece Unigram smoke tokenizer를 학습합니다.",
    )
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--vocab-size", required=True, type=int, choices=(128, 256, 512))
    parser.add_argument("--character-coverage", type=float, default=1.0)
    parser.add_argument("--hard-vocab-limit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--json", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    root = repository_root()
    corpus = resolve_repository_path(args.corpus, root)
    output = resolve_repository_path(args.output, root)
    synthetic_root = root / "tests" / "fixtures" / "tokenizer"
    smoke_output_root = (root / "tests" / "output").resolve()
    if output == smoke_output_root or smoke_output_root not in output.parents:
        raise TokenizerError("TOKENIZER_OUTPUT_PATH_ERROR", "smoke output은 tests/output의 하위 디렉터리여야 합니다.")
    config = TrainerConfig(
        vocab_size=args.vocab_size,
        character_coverage=args.character_coverage,
        hard_vocab_limit=args.hard_vocab_limit,
    )
    return train_smoke_tokenizer(corpus, output, synthetic_root=synthetic_root, config=config)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run(args)
    except (TokenizerError, OSError, ValueError, RuntimeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Synthetic tokenizer smoke 완료: piece {result['actual_piece_count']}개")
        print(f"Fingerprint: {result['fingerprint']}")
        print("승인·Gate 3 상태에는 영향을 주지 않습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
