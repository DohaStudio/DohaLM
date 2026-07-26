"""Build the approved, restricted AIHUB-71748 tokenizer development corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.data.aihub_71748_tokenizer_corpus import CorpusBuildConfig, build_tokenizer_corpus, resolve_local_paths


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/local-datasets.yaml"))
    parser.add_argument("--package-manifest", type=Path, default=Path("docs/data/aihub-71748-local-package.manifest.yaml"))
    parser.add_argument("--checksum-inventory", type=Path, default=Path("docs/data/aihub-71748-zip-checksums.manifest.yaml"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--records-per-archive", type=int, default=8_192)
    parser.add_argument("--bytes-per-archive", type=int, default=20 * 1024 * 1024)
    parser.add_argument("--max-record-bytes", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        external_root, _ = resolve_local_paths(args.config)
        output = args.output or external_root / "analysis/tokenizer-development/AIHUB-71748/operating-16k-v1/corpus"
        result = build_tokenizer_corpus(
            local_config=args.config,
            package_manifest=args.package_manifest,
            checksum_inventory=args.checksum_inventory,
            output_dir=output,
            config=CorpusBuildConfig(args.records_per_archive, args.bytes_per_archive, args.max_record_bytes),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2
    summary = {key: result[key] for key in ("status", "archive_count", "record_count", "character_count", "byte_count", "corpus_sha256", "corpus_fingerprint")}
    print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else "\n".join(f"{key}: {value}" for key, value in summary.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
