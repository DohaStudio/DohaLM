"""Prepare local-only token JSONL without persisting source text."""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
from pathlib import Path
from typing import Any, Iterable

import sentencepiece as spm

from src.data.checksums import checksum_value, file_checksum
from src.data.pilot_corpus import PilotCorpusPolicy, inspect_pilot_corpus, iter_pilot_records, stable_split
from src.data.sequence_packing import PackingPolicy, pack_sequences
from src.runtime.paths import resolve_repository_path
from src.tokenizer import DohaTokenizer, validate_pilot_tokenizer
from src.tokenizer.tokenizer import SPECIAL_TOKEN_IDS, USER_DEFINED_SYMBOLS

from ._common import cli_error, print_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="명시적으로 지정한 UTF-8 corpus를 local-only pilot token으로 준비합니다.")
    parser.add_argument("--input", required=True, help="사용자가 지정한 UTF-8 TXT/JSONL 경로")
    parser.add_argument("--output", required=True, help="Git 제외 저장소 상대 출력 디렉터리")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-purpose", required=True, choices=("development_train",))
    parser.add_argument("--license-status", required=True)
    parser.add_argument("--local-experiment-only", action="store_true")
    parser.add_argument("--text-field", default="text_normalized")
    parser.add_argument("--minimum-records", type=int, default=2)
    parser.add_argument("--tokenizer-model")
    parser.add_argument("--train-tokenizer", action="store_true")
    parser.add_argument("--tokenizer-output")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--train-percent", type=int, default=95)
    parser.add_argument("--packing-mode", choices=("continuous", "record_boundary"), default="continuous")
    parser.add_argument("--remainder", choices=("drop", "pad"), default="drop")
    parser.add_argument("--json", action="store_true")
    return parser


def _ignored_output(path: Path) -> Path:
    root = resolve_repository_path(".")
    relative = path.relative_to(root).as_posix()
    allowed = relative.startswith(("data/tokenized/", "artifacts/", "experiments/", "tests/output/"))
    if not allowed:
        raise ValueError("pilot output은 Git 제외 data/tokenized, artifacts, experiments 또는 tests/output 아래여야 합니다.")
    return path


def _train_candidate(source: Path, text_field: str, output: Path) -> Path:
    if output.exists():
        raise ValueError("기존 tokenizer output을 덮어쓸 수 없습니다.")
    staging = output.with_name(f".{output.name}.staging")
    if staging.exists():
        raise ValueError("tokenizer staging 경로가 이미 존재합니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    writer = io.BytesIO()
    try:
        try:
            spm.SentencePieceTrainer.train(
                sentence_iterator=(record.text for record in iter_pilot_records(source, text_field=text_field)),
                model_writer=writer,
                model_type="unigram",
                vocab_size=16_000,
                character_coverage=1.0,
                hard_vocab_limit=True,
                normalization_rule_name="identity",
                byte_fallback=False,
                shuffle_input_sentence=False,
                num_threads=1,
                pad_id=0,
                unk_id=1,
                bos_id=2,
                eos_id=3,
                pad_piece="<pad>",
                unk_piece="<unk>",
                bos_piece="<bos>",
                eos_piece="<eos>",
                user_defined_symbols=list(USER_DEFINED_SYMBOLS),
            )
        except RuntimeError as exc:
            raise ValueError(
                "PILOT_TOKENIZER_CORPUS_TOO_SMALL: 16,000 vocabulary를 만들 수 없으며 자동 축소하지 않습니다."
            ) from exc
        model = writer.getvalue()
        if not model:
            raise ValueError("SentencePiece model이 생성되지 않았습니다.")
        model_path = staging / "tokenizer.model"
        model_path.write_bytes(model)
        tokenizer = DohaTokenizer(model_path)
        if tokenizer.vocab_size != 16_000:
            raise ValueError("PILOT_TOKENIZER_CORPUS_TOO_SMALL: 16,000 piece를 생성하지 못했습니다.")
        rows = [f"{tokenizer.processor.id_to_piece(index)}\t{tokenizer.processor.get_score(index)}" for index in range(tokenizer.vocab_size)]
        (staging / "tokenizer.vocab").write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
        manifest = {
            "schema_version": "1.0",
            "status": "development_candidate_not_approved",
            "model_type": "unigram",
            "vocab_size": 16_000,
            "normalization_rule_name": "identity",
            "hard_vocab_limit": True,
            "special_tokens": SPECIAL_TOKEN_IDS,
            "model_checksum": file_checksum(model_path),
            "approval_effect": "none",
            "gate3_effect": "none",
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(staging, output)
        return output / "tokenizer.model"
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _write_sequences(path: Path, records: Iterable[list[int]], policy: PackingPolicy) -> tuple[int, int]:
    count = targets = 0
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for sequence in pack_sequences(records, policy):
            handle.write(json.dumps(sequence, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
            targets += sum(label != policy.ignore_index for label in sequence["labels"][1:])
    return count, targets


def run(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.input).expanduser().resolve()
    output = _ignored_output(resolve_repository_path(args.output))
    if output.exists():
        raise ValueError("기존 pilot corpus output을 덮어쓸 수 없습니다.")
    policy = PilotCorpusPolicy(args.source_id, args.license_status, args.local_experiment_only)
    source_checksum_before = file_checksum(source)
    summary = inspect_pilot_corpus(source, policy=policy, text_field=args.text_field, minimum_records=args.minimum_records)
    if args.train_tokenizer == bool(args.tokenizer_model):
        raise ValueError("--tokenizer-model 또는 --train-tokenizer 중 정확히 하나가 필요합니다.")
    if args.train_tokenizer:
        if not args.tokenizer_output:
            raise ValueError("--train-tokenizer에는 --tokenizer-output이 필요합니다.")
        tokenizer_model = _train_candidate(source, args.text_field, _ignored_output(resolve_repository_path(args.tokenizer_output)))
        tokenizer_status = "development_candidate_not_approved"
    else:
        tokenizer_model = resolve_repository_path(args.tokenizer_model)
        tokenizer_status = "user_designated_existing"
    tokenizer, tokenizer_report = validate_pilot_tokenizer(tokenizer_model)
    packing = PackingPolicy(mode=args.packing_mode, remainder=args.remainder)
    staging = output.with_name(f".{output.name}.staging")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        token_statistics = {"train": {"tokens": 0, "unknown": 0, "records": 0}, "validation": {"tokens": 0, "unknown": 0, "records": 0}}

        def token_stream(split: str):
            for record in iter_pilot_records(source, text_field=args.text_field):
                if stable_split(record.text_fingerprint, seed=args.seed, train_percent=args.train_percent) == split:
                    encoded = tokenizer.encode(record.text)
                    token_statistics[split]["records"] += 1
                    token_statistics[split]["tokens"] += len(encoded.ids)
                    token_statistics[split]["unknown"] += encoded.ids.count(tokenizer.unk_id)
                    yield encoded.ids

        train_count, train_targets = _write_sequences(staging / "train.jsonl", token_stream("train"), packing)
        validation_count, validation_targets = _write_sequences(staging / "validation.jsonl", token_stream("validation"), packing)
        if train_count == 0 or validation_count == 0:
            raise ValueError("packing 후 train/validation sequence가 모두 최소 1개 이상이어야 합니다.")
        source_checksum_after = file_checksum(source)
        if source_checksum_after != source_checksum_before:
            raise ValueError("PILOT_SOURCE_MUTATED: corpus가 준비 중 변경되었습니다.")
        corpus_manifest = {
            **summary.to_dict(),
            "source_purpose": args.source_purpose,
            "source_checksum": source_checksum_before,
            "source_path_recorded": False,
            "raw_text_persisted": False,
        }
        split_manifest = {
            "schema_version": "1.0",
            "algorithm": "sha256-record-fingerprint-v1",
            "seed": args.seed,
            "train_percent": args.train_percent,
            "train_sequences": train_count,
            "validation_sequences": validation_count,
            "train_target_tokens": train_targets,
            "validation_target_tokens": validation_targets,
            "packing": packing.to_dict(),
            "tokenizer_status": tokenizer_status,
            "tokenizer_fingerprint": file_checksum(tokenizer_model),
            "tokenizer_compatibility": tokenizer_report,
            "token_statistics": {
                split: {
                    **counts,
                    "unknown_ratio": counts["unknown"] / max(1, counts["tokens"]),
                }
                for split, counts in token_statistics.items()
            },
            "approval_effect": "none",
            "gate3_effect": "none",
        }
        tokenization_manifest = {
            "schema_version": "1.0",
            "corpus_fingerprint": summary.corpus_fingerprint,
            "tokenizer_fingerprint": file_checksum(tokenizer_model),
            "packing_policy": packing.to_dict(),
            "bos_inserted": False,
            "eos_inserted_by_packer": True,
            "raw_text_persisted": False,
            "train_artifact_checksum": file_checksum(staging / "train.jsonl"),
            "validation_artifact_checksum": file_checksum(staging / "validation.jsonl"),
        }
        (staging / "corpus-manifest.json").write_text(json.dumps(corpus_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (staging / "split-manifest.json").write_text(json.dumps(split_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (staging / "tokenization-manifest.json").write_text(json.dumps(tokenization_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (staging / "token-statistics.json").write_text(json.dumps(split_manifest["token_statistics"], ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        (staging / "corpus-fingerprint.json").write_text(json.dumps({"algorithm": "sha256", "fingerprint": summary.corpus_fingerprint}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        artifact_fingerprint = checksum_value({path.name: file_checksum(path) for path in sorted(staging.iterdir())})
        os.replace(staging, output)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "status": "prepared_local_only",
        "train_sequences": train_count,
        "validation_sequences": validation_count,
        "artifact_fingerprint": artifact_fingerprint,
        "raw_text_persisted": False,
        "approval_effect": "none",
        "gate3_effect": "none",
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print_result(run(args), json_output=args.json)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return cli_error(exc)


if __name__ == "__main__":
    raise SystemExit(main())
