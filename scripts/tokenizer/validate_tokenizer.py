"""Tokenizer smoke bundle 무결성 검증 CLI."""

from __future__ import annotations

import argparse
import json
import sys

from src.tokenizer.errors import TokenizerError
from src.tokenizer.manifest import validate_bundle


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.tokenizer.validate_tokenizer",
        description="Tokenizer smoke bundle의 checksum, fingerprint, vocabulary와 special token을 검증합니다.",
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = validate_bundle(args.model)
    except (TokenizerError, OSError, ValueError, RuntimeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"유효한 synthetic smoke bundle: piece {result['actual_piece_count']}개")
        print("운영 tokenizer 승인 또는 Gate 3 통과를 의미하지 않습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
