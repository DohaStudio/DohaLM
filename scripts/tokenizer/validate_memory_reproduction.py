"""Validate tokenizer fingerprint reproduction and record aggregate peak RSS."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from src.tokenizer.operating import _sample_lines, validate_operating_candidate
from src.tokenizer.tokenizer import DohaTokenizer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-root", type=Path, required=True)
    parser.add_argument("--reproduction-root", type=Path, required=True)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _manifest(candidate: Path) -> dict[str, object]:
    value = json.loads((candidate / "tokenizer-manifest.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("tokenizer manifest must be an object")
    return value


def _encode_digest(tokenizer: DohaTokenizer, rows: list[str]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        token_ids = tokenizer.processor.encode(row, out_type=int)
        digest.update(len(token_ids).to_bytes(8, "big"))
        for token_id in token_ids:
            digest.update(token_id.to_bytes(4, "big"))
    return f"sha256:{digest.hexdigest()}"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    rows = _sample_lines(args.corpus_dir.resolve() / "corpus.txt")
    candidates: dict[str, dict[str, object]] = {}
    for name in ("unigram-16k", "bpe-16k"):
        original = args.original_root.resolve() / name
        reproduction = args.reproduction_root.resolve() / name
        original_validation = validate_operating_candidate(original)
        reproduction_validation = validate_operating_candidate(reproduction)
        original_manifest = _manifest(original)
        reproduction_manifest = _manifest(reproduction)
        if original_manifest.get("trainer_config") != reproduction_manifest.get("trainer_config"):
            raise ValueError(f"trainer config reproduction mismatch: {name}")
        original_vocab_sha256 = original_manifest.get("vocab_checksum")
        reproduction_vocab_sha256 = reproduction_manifest.get("vocab_checksum")
        if original_vocab_sha256 != reproduction_vocab_sha256:
            raise ValueError(f"vocabulary reproduction mismatch: {name}")
        original_encode_digest = _encode_digest(DohaTokenizer(original / "tokenizer.model"), rows)
        reproduction_encode_digest = _encode_digest(DohaTokenizer(reproduction / "tokenizer.model"), rows)
        if original_encode_digest != reproduction_encode_digest:
            raise ValueError(f"sample encoding reproduction mismatch: {name}")
        peak = reproduction_manifest.get("peak_process_rss_bytes")
        if not isinstance(peak, int) or peak <= 0:
            raise ValueError(f"peak RSS was not measured: {name}")
        candidates[name] = {
            "original_tokenizer_fingerprint": original_validation["tokenizer_fingerprint"],
            "reproduction_tokenizer_fingerprint": reproduction_validation["tokenizer_fingerprint"],
            "binary_fingerprint_matches_original": (
                original_validation["tokenizer_fingerprint"]
                == reproduction_validation["tokenizer_fingerprint"]
            ),
            "vocab_sha256": original_vocab_sha256,
            "vocabulary_matches_original": True,
            "sample_line_count": len(rows),
            "sample_encode_id_digest": original_encode_digest,
            "sample_encode_ids_match_original": True,
            "piece_count": reproduction_validation["piece_count"],
            "byte_piece_count": reproduction_validation["byte_piece_count"],
            "peak_process_rss_bytes": peak,
            "sampling_interval_seconds": reproduction_manifest["peak_process_rss_sampling_interval_seconds"],
            "training_seconds": reproduction_manifest["training_seconds"],
        }
    result = {
        "schema_version": "1.0",
        "artifact_kind": "operating_tokenizer_memory_reproduction",
        "measurement": "process_rss_sampled_during_same_config_reproduction_training",
        "binary_fingerprint_note": (
            "SentencePiece model binaries include output-specific trainer metadata; "
            "vocabulary and sample encode IDs are compared separately."
        ),
        "candidates": candidates,
        "model_training_allowed": False,
        "gate3_effect": "evidence_only_pending_user_approval",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
