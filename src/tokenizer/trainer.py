"""Synthetic corpus 전용 SentencePiece Unigram smoke trainer."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import sentencepiece as spm

from .errors import TokenizerError
from .fingerprint import build_fingerprint
from .manifest import build_manifest, write_json
from .statistics import collect_statistics
from .tokenizer import DohaTokenizer, SPECIAL_TOKEN_IDS, USER_DEFINED_SYMBOLS


SMOKE_VOCAB_SIZES = frozenset({128, 256, 512})
ARTIFACT_FILES = (
    "tokenizer.model",
    "tokenizer.vocab",
    "manifest.json",
    "fingerprint.json",
    "statistics.json",
)


@dataclass(frozen=True)
class TrainerConfig:
    vocab_size: int = 256
    character_coverage: float = 1.0
    hard_vocab_limit: bool = True
    model_type: str = "unigram"
    user_defined_symbols: tuple[str, ...] = USER_DEFINED_SYMBOLS
    normalization_rule_name: str = "identity"
    byte_fallback: bool = False
    shuffle_input_sentence: bool = False
    num_threads: int = 1

    def validate(self) -> None:
        if self.vocab_size not in SMOKE_VOCAB_SIZES:
            raise TokenizerError("TOKENIZER_CONFIG_ERROR", "smoke vocab_size는 128, 256, 512만 허용합니다.")
        if self.model_type != "unigram":
            raise TokenizerError("TOKENIZER_CONFIG_ERROR", "model_type은 unigram이어야 합니다.")
        if not 0.98 <= self.character_coverage <= 1.0:
            raise TokenizerError("TOKENIZER_CONFIG_ERROR", "character_coverage 범위가 올바르지 않습니다.")
        if tuple(self.user_defined_symbols) != USER_DEFINED_SYMBOLS:
            raise TokenizerError("TOKENIZER_CONFIG_ERROR", "ADR-003 user-defined symbol과 순서가 일치해야 합니다.")
        if len(set(self.user_defined_symbols)) != len(self.user_defined_symbols):
            raise TokenizerError("TOKENIZER_CONFIG_ERROR", "user-defined symbol이 중복됩니다.")

    def resolved(self) -> dict[str, Any]:
        value = asdict(self)
        value["user_defined_symbols"] = list(self.user_defined_symbols)
        return value


@dataclass(frozen=True)
class CorpusInfo:
    path: Path
    records: tuple[str, ...]
    fingerprint: str
    character_count: int
    byte_count: int


def validate_synthetic_corpus(path: str | Path, synthetic_root: str | Path) -> CorpusInfo:
    corpus = Path(path).resolve()
    allowed = Path(synthetic_root).resolve()
    if not corpus.is_file() or (corpus != allowed and allowed not in corpus.parents):
        raise TokenizerError("TOKENIZER_CORPUS_NOT_SYNTHETIC", "허용된 synthetic fixture root의 파일만 사용할 수 있습니다.")
    if corpus.suffix.lower() != ".txt":
        raise TokenizerError("TOKENIZER_CORPUS_NOT_SYNTHETIC", "smoke corpus는 UTF-8 TXT만 허용합니다.")
    try:
        raw = corpus.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise TokenizerError("TOKENIZER_CORPUS_ERROR", "synthetic corpus를 UTF-8로 읽을 수 없습니다.") from exc
    if "\x00" in text:
        raise TokenizerError("TOKENIZER_CORPUS_ERROR", "synthetic corpus에 NUL이 있습니다.")
    records = tuple(line for line in text.splitlines() if line.strip())
    if not records:
        raise TokenizerError("TOKENIZER_CORPUS_EMPTY", "synthetic corpus가 비어 있습니다.")
    return CorpusInfo(
        corpus,
        records,
        f"sha256:{hashlib.sha256(raw).hexdigest()}",
        sum(len(record) for record in records),
        len(raw),
    )


def _train_sentencepiece(corpus: CorpusInfo, staging: Path, config: TrainerConfig) -> None:
    kwargs = {
        "sentence_iterator": iter(corpus.records),
        "model_type": config.model_type,
        "vocab_size": config.vocab_size,
        "character_coverage": config.character_coverage,
        "hard_vocab_limit": config.hard_vocab_limit,
        "normalization_rule_name": config.normalization_rule_name,
        "byte_fallback": config.byte_fallback,
        "shuffle_input_sentence": config.shuffle_input_sentence,
        "num_threads": config.num_threads,
        "pad_id": 0,
        "unk_id": 1,
        "bos_id": 2,
        "eos_id": 3,
        "pad_piece": "<pad>",
        "unk_piece": "<unk>",
        "bos_piece": "<bos>",
        "eos_piece": "<eos>",
        "user_defined_symbols": list(config.user_defined_symbols),
    }
    model_writer = io.BytesIO()
    kwargs["model_writer"] = model_writer
    try:
        spm.SentencePieceTrainer.train(**kwargs)
    except (RuntimeError, OSError, ValueError) as exc:
        raise TokenizerError("TOKENIZER_TRAINING_ERROR", "SentencePiece smoke 학습에 실패했습니다.") from exc
    model_bytes = model_writer.getvalue()
    if not model_bytes:
        raise TokenizerError("TOKENIZER_TRAINING_ERROR", "SentencePiece model bytes가 생성되지 않았습니다.")
    (staging / "tokenizer.model").write_bytes(model_bytes)
    processor = spm.SentencePieceProcessor(model_proto=model_bytes)
    vocab_rows = [
        f"{processor.id_to_piece(token_id)}\t{processor.get_score(token_id)}"
        for token_id in range(processor.get_piece_size())
    ]
    (staging / "tokenizer.vocab").write_text("\n".join(vocab_rows) + "\n", encoding="utf-8", newline="\n")


def train_smoke_tokenizer(
    corpus_path: str | Path,
    output_dir: str | Path,
    *,
    synthetic_root: str | Path,
    config: TrainerConfig,
) -> dict[str, Any]:
    config.validate()
    corpus = validate_synthetic_corpus(corpus_path, synthetic_root)
    output = Path(output_dir).resolve()
    staging = output.with_name(f".{output.name}.staging")
    if output.exists() or staging.exists():
        raise TokenizerError("TOKENIZER_ARTIFACT_EXISTS", "기존 tokenizer output을 덮어쓰지 않습니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        _train_sentencepiece(corpus, staging, config)
        model_path = staging / "tokenizer.model"
        vocab_path = staging / "tokenizer.vocab"
        tokenizer = DohaTokenizer(model_path)
        if config.hard_vocab_limit and tokenizer.vocab_size != config.vocab_size:
            raise TokenizerError("TOKENIZER_VOCAB_SIZE_MISMATCH", "실제 piece 수가 요청 vocab_size와 다릅니다.")
        if {piece: tokenizer.processor.piece_to_id(piece) for piece in SPECIAL_TOKEN_IDS} != SPECIAL_TOKEN_IDS:
            raise TokenizerError("TOKENIZER_SPECIAL_TOKEN_MISMATCH", "special token mapping이 일치하지 않습니다.")
        fingerprint = build_fingerprint(
            model_path,
            config.resolved(),
            SPECIAL_TOKEN_IDS,
            spm.__version__,
        )
        statistics = collect_statistics(
            tokenizer,
            corpus.records,
            character_coverage=config.character_coverage,
            byte_fallback=config.byte_fallback,
        )
        manifest = build_manifest(
            requested_vocab_size=config.vocab_size,
            actual_piece_count=tokenizer.vocab_size,
            trainer_config=config.resolved(),
            special_tokens=SPECIAL_TOKEN_IDS,
            sentencepiece_version=spm.__version__,
            corpus_fingerprint=corpus.fingerprint,
            corpus_record_count=len(corpus.records),
            corpus_character_count=corpus.character_count,
            corpus_byte_count=corpus.byte_count,
            model_path=model_path,
            vocab_path=vocab_path,
            tokenizer_fingerprint=fingerprint["fingerprint"],
        )
        write_json(staging / "fingerprint.json", fingerprint)
        write_json(staging / "statistics.json", statistics)
        write_json(staging / "manifest.json", manifest)
        if {path.name for path in staging.iterdir()} != set(ARTIFACT_FILES):
            raise TokenizerError("TOKENIZER_ARTIFACT_ERROR", "smoke artifact 구성이 올바르지 않습니다.")
        os.replace(staging, output)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "success": True,
        "status": "smoke_only_not_approved",
        "vocab_size": config.vocab_size,
        "actual_piece_count": tokenizer.vocab_size,
        "fingerprint": fingerprint["fingerprint"],
        "artifact_files": list(ARTIFACT_FILES),
        "output": output.as_posix(),
        "approval_effect": "none",
        "gate3_effect": "none",
    }
