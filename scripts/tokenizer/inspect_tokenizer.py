"""Tokenizer model의 비원문 구조 정보를 출력하는 CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import sentencepiece as spm

from src.tokenizer.errors import TokenizerError
from src.tokenizer.tokenizer import DohaTokenizer, SPECIAL_TOKEN_IDS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.tokenizer.inspect_tokenizer",
        description="Tokenizer model의 piece 수와 ADR-003 special token mapping을 검사합니다.",
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, object]:
    tokenizer = DohaTokenizer(Path(args.model))
    return {
        "success": True,
        "model_type": "unigram",
        "actual_piece_count": tokenizer.vocab_size,
        "special_tokens": SPECIAL_TOKEN_IDS,
        "sentencepiece_version": spm.__version__,
        "approval_effect": "none",
    }


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
        print(f"SentencePiece {result['sentencepiece_version']}, piece {result['actual_piece_count']}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
