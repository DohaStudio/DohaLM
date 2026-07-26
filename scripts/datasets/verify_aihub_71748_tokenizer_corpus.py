"""Read-only integrity verification for the approved AIHUB-71748 tokenizer corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.data.aihub_71748_tokenizer_corpus import resolve_local_paths, verify_existing_tokenizer_corpus


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/local-datasets.yaml"))
    parser.add_argument("--package-manifest", type=Path, default=Path("docs/data/aihub-71748-local-package.manifest.yaml"))
    parser.add_argument("--checksum-inventory", type=Path, default=Path("docs/data/aihub-71748-zip-checksums.manifest.yaml"))
    parser.add_argument("--corpus-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        external_root, _ = resolve_local_paths(args.config)
        corpus = args.corpus_dir or external_root / "analysis/tokenizer-development/AIHUB-71748/operating-16k-v1/corpus"
        result = verify_existing_tokenizer_corpus(
            local_config=args.config,
            package_manifest=args.package_manifest,
            checksum_inventory=args.checksum_inventory,
            corpus_dir=corpus,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
